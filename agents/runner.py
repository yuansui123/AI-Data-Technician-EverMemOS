"""Agent runner — the LLM loop engine.

All LLM calls go through invoke(). Single-pass agents use max_iterations=1.
Multi-pass agents use max_iterations>1 with a ToolExecutor.

run_agent() is the high-level interface for spawning a fresh agent with
a prompt, tools, and iteration limit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable


@dataclass
class SubagentConfig:
    model: str
    system_prompt: str
    tools: list[dict] = field(default_factory=list)
    thinking_budget: int = 0          # 0 = disabled
    max_iterations: int = 1           # 1 = single-pass; >1 = tool-use loop
    max_tokens: int = 8192


@dataclass
class SubagentResult:
    text: str                          # final assistant text response
    thinking: str                      # concatenated thinking blocks (may be empty)
    tool_calls: list[dict]             # all tool calls made during the run
    iterations: int
    usage: dict                        # prompt_tokens, output_tokens, total_tokens


# -- Tool executor -----------------------------------------------------------

ToolExecutorFn = Callable[[str, dict], Awaitable[str]]


class ToolExecutor:
    """Dispatches tool_use blocks to the appropriate tool handler.

    Handles bash, vision, read by default.
    Extend by registering additional handlers.
    """

    def __init__(self, project_dir: str | None = None):
        self.project_dir = project_dir
        self._handlers: dict[str, ToolExecutorFn] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._handlers["bash"] = self._bash
        self._handlers["vision"] = self._vision
        self._handlers["read"] = self._read_file
        self._handlers["write"] = self._write_file

    def register(self, name: str, fn: ToolExecutorFn) -> None:
        self._handlers[name] = fn

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        handler = self._handlers.get(tool_name)
        if handler is None:
            return f"[ToolExecutor] Unknown tool: {tool_name}"
        try:
            return await handler(tool_input)
        except Exception as exc:  # noqa: BLE001
            return f"[ToolExecutor] Error in {tool_name}: {exc}"

    async def _bash(self, inp: dict) -> str:
        from tools.bash import bash
        result = await bash(
            cmd=inp["command"],
            cwd=inp.get("cwd", self.project_dir),
            timeout=inp.get("timeout", 60),
        )
        out = result.stdout or ""
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        return out or "(no output)"

    async def _vision(self, inp: dict) -> str:
        from tools.vision import vision
        result = await vision(
            image_path=inp.get("image_path"),
            images=inp.get("images"),
            context=inp.get("context"),
        )
        return json.dumps(result, indent=2)

    async def _read_file(self, inp: dict) -> str:
        from tools.read import read
        result = read(
            path=inp["path"],
            max_chars=int(inp.get("max_chars", 8000)),
            offset_chars=int(inp.get("offset_chars", 0)),
        )
        return result.get("response", "")

    async def _write_file(self, inp: dict) -> str:
        from tools.write import write
        result = write(
            path=inp["path"],
            content=inp["content"],
            project_dir=self.project_dir,
        )
        return result.get("response", "")


# -- Core invoke -------------------------------------------------------------

EventCallback = Callable[[dict], Awaitable[None]] | None


async def invoke(
    config: SubagentConfig,
    messages: list[dict],
    tool_executor: ToolExecutor | None = None,
    on_event: EventCallback = None,
) -> SubagentResult:
    """Call the LLM with a tool-use loop up to config.max_iterations.

    For single-pass agents (think) use max_iterations=1.
    For tool-use agents (explore, statistics) pass a ToolExecutor.
    """
    import asyncio
    import anthropic
    import config as cfg

    client = anthropic.AsyncAnthropic(api_key=cfg.ANTHROPIC_API_KEY)

    all_messages = list(messages)
    all_tool_calls: list[dict] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0}
    thinking_parts: list[str] = []
    iteration = 0
    final_text = ""
    hit_iteration_limit = False

    while True:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "system": config.system_prompt,
            "messages": all_messages,
        }

        if config.thinking_budget > 0:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": config.thinking_budget}

        if config.tools:
            kwargs["tools"] = config.tools

        # API call with retry
        def _retry_delay(_exc, _attempt: int) -> float:
            if isinstance(_exc, anthropic.InternalServerError):
                return 3.0 * (_attempt + 1)
            return 10.0 * (2 ** _attempt)

        _debug_log_request(config, all_messages, iteration)
        text_parts: list[str] = []

        if on_event:
            for _attempt in range(6):
                try:
                    async with client.messages.stream(**kwargs) as stream:
                        async for text in stream.text_stream:
                            await on_event({"type": "text_delta", "delta": text})
                            text_parts.append(text)
                        response = await stream.get_final_message()
                    break
                except (anthropic.RateLimitError, anthropic.InternalServerError) as _exc:
                    if _attempt == 5:
                        _debug_log_error(config, _exc)
                        raise
                    text_parts.clear()
                    await asyncio.sleep(_retry_delay(_exc, _attempt))
        else:
            for _attempt in range(6):
                try:
                    response = await client.messages.create(**kwargs)
                    break
                except (anthropic.RateLimitError, anthropic.InternalServerError) as _exc:
                    if _attempt == 5:
                        _debug_log_error(config, _exc)
                        raise
                    await asyncio.sleep(_retry_delay(_exc, _attempt))
        iteration += 1

        # Accumulate usage
        if hasattr(response, "usage") and response.usage:
            total_usage["input_tokens"] += getattr(response.usage, "input_tokens", 0)
            total_usage["output_tokens"] += getattr(response.usage, "output_tokens", 0)

        # Extract thinking and tool_use blocks
        tool_use_blocks: list[Any] = []
        for block in response.content:
            if block.type == "thinking":
                thinking_parts.append(getattr(block, "thinking", ""))
            elif block.type == "text" and not on_event:
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        iteration_text = "".join(text_parts)
        if iteration_text:
            final_text = iteration_text

        # Done conditions
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break
        if iteration >= config.max_iterations:
            hit_iteration_limit = True
            break
        if tool_executor is None:
            break

        # Execute tools and continue loop
        tool_results = []
        for block in tool_use_blocks:
            if on_event:
                await on_event({"type": "tool_call", "tool": block.name, "input": block.input})
            result_text = await tool_executor.execute(block.name, block.input)
            if on_event:
                await on_event({"type": "tool_result", "tool": block.name, "result": result_text[:2000]})
            all_tool_calls.append({"tool": block.name, "input": block.input, "result": result_text})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        all_messages.append({"role": "assistant", "content": response.content})
        all_messages.append({"role": "user", "content": tool_results})

    # Force a summary if we hit the limit mid-tool-use
    if (not final_text or hit_iteration_limit) and all_tool_calls and tool_executor is not None:
        summary_kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "system": config.system_prompt,
            "messages": all_messages + [{
                "role": "user",
                "content": "You have reached the iteration limit. Based on all the tool results above, write a concise summary of your findings for the user."
            }],
        }
        if on_event:
            for _attempt in range(6):
                try:
                    async with client.messages.stream(**summary_kwargs) as stream:
                        async for text in stream.text_stream:
                            await on_event({"type": "text_delta", "delta": text})
                            final_text += text
                        break
                except (anthropic.RateLimitError, anthropic.InternalServerError):
                    if _attempt == 5:
                        break
                    final_text = ""
                    await asyncio.sleep(10 * (2 ** _attempt))
        else:
            for _attempt in range(6):
                try:
                    summary_response = await client.messages.create(**summary_kwargs)
                    break
                except (anthropic.RateLimitError, anthropic.InternalServerError):
                    if _attempt == 5:
                        break
                    await asyncio.sleep(10 * (2 ** _attempt))
            else:
                summary_response = None
            if summary_response:
                for block in summary_response.content:
                    if block.type == "text" and block.text.strip():
                        final_text = block.text
                        break
                if hasattr(summary_response, "usage") and summary_response.usage:
                    total_usage["input_tokens"] += getattr(summary_response.usage, "input_tokens", 0)
                    total_usage["output_tokens"] += getattr(summary_response.usage, "output_tokens", 0)

    result = SubagentResult(
        text=final_text,
        thinking="\n\n".join(thinking_parts),
        tool_calls=all_tool_calls,
        iterations=iteration,
        usage={
            **total_usage,
            "total_tokens": total_usage["input_tokens"] + total_usage["output_tokens"],
        },
    )
    _debug_log_result(config, result)
    return result


# -- run_agent: high-level agent spawner ------------------------------------

async def run_agent(
    message: str,
    prompt: str,
    tools: list[dict] | None = None,
    max_iterations: int = 1,
    thinking_budget: int = 0,
    max_tokens: int = 4096,
    model: str | None = None,
    project_dir: str | Path | None = None,
    on_event: EventCallback = None,
    agent_name: str | None = None,
) -> SubagentResult:
    """Spawn a fresh agent with the given configuration.

    Args:
        message: The task/user message to send.
        prompt: Either a prompt filename (loads agents/prompts/{prompt}.md)
                or raw prompt text if the file doesn't exist.
        tools: Anthropic tool schemas. None = no tools (single-pass).
        max_iterations: 1 = single-pass, >1 = tool-use loop.
        thinking_budget: Extended thinking token budget. 0 = disabled.
        max_tokens: Max response tokens.
        model: Model ID override. Defaults to config.ORCHESTRATOR_MODEL.
        project_dir: Working directory for tool execution.
        on_event: Callback for streaming events.
        agent_name: Label for sub-events (e.g. "explore", "statistics").
    """
    import config as cfg

    # Load prompt from file or use raw text
    prompt_file = Path(__file__).parent / "prompts" / f"{prompt}.md"
    if prompt_file.exists():
        system_prompt = prompt_file.read_text(encoding="utf-8")
    else:
        system_prompt = prompt

    agent_config = SubagentConfig(
        model=model or cfg.ORCHESTRATOR_MODEL,
        system_prompt=system_prompt,
        tools=tools or [],
        thinking_budget=thinking_budget,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
    )

    executor = ToolExecutor(project_dir=str(project_dir) if project_dir else None) if tools else None

    # Wrap on_event to label sub-agent events
    sub_on_event = None
    if on_event and agent_name:
        async def sub_on_event(event: dict):
            if event["type"] == "tool_call":
                await on_event({"type": "sub_tool_call", "subagent": agent_name,
                                "tool": event["tool"], "input": event["input"]})
            elif event["type"] == "tool_result":
                await on_event({"type": "sub_tool_result", "subagent": agent_name,
                                "tool": event["tool"], "result": event["result"]})
    elif on_event:
        sub_on_event = on_event

    return await invoke(agent_config, [{"role": "user", "content": message}],
                        tool_executor=executor, on_event=sub_on_event)


# -- Debug logging helpers ---------------------------------------------------

def _dbg_path() -> str | None:
    import os
    return os.environ.get("AI_DT_DEBUG_LOG")


def _dbg_write(text: str) -> None:
    path = _dbg_path()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _debug_log_request(config: "SubagentConfig", messages: list, iteration: int) -> None:
    if not _dbg_path():
        return
    from datetime import datetime

    def _fmt_content(content: Any) -> str:
        if isinstance(content, list):
            parts = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type", "")
                if btype == "text":
                    parts.append(b.get("text", "")[:400])
                elif btype == "tool_use":
                    parts.append(f"[tool_use: {b.get('name')} input={json.dumps(b.get('input',{}))[:200]}]")
                elif btype == "tool_result":
                    parts.append(f"[tool_result: {str(b.get('content',''))[:200]}]")
                else:
                    parts.append(str(b)[:100])
            return " | ".join(parts)
        return str(content)[:600]

    sep = "\u2500" * 60
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [
        "",
        "=" * 80,
        f"[{ts}] REQUEST  model={config.model}  iter={iteration+1}/{config.max_iterations}",
        "=" * 80,
        "SYSTEM:",
        (config.system_prompt[:800] + "\u2026") if len(config.system_prompt) > 800 else config.system_prompt,
        sep,
        "MESSAGES:",
    ]
    for msg in messages:
        role = msg.get("role", "?")
        content = _fmt_content(msg.get("content", ""))
        lines.append(f"  [{role}] {content}")
    if config.tools:
        lines.append(f"{sep}\nTOOLS: {[t.get('name') for t in config.tools]}")
    _dbg_write("\n".join(lines) + "\n")


def _debug_log_result(config: "SubagentConfig", result: "SubagentResult") -> None:
    if not _dbg_path():
        return
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    sep = "\u2500" * 60
    lines = [
        sep,
        f"[{ts}] RESULT  iters={result.iterations}  tokens={result.usage.get('total_tokens','?')}",
    ]
    if result.thinking:
        lines += ["THINKING:", result.thinking[:600] + ("\u2026" if len(result.thinking) > 600 else "")]
    for tc in result.tool_calls:
        inp_str = json.dumps(tc.get("input", {}), ensure_ascii=False)[:300]
        res_str = str(tc.get("result", ""))[:300]
        lines.append(f"  TOOL -> {tc.get('tool')}  {inp_str}")
        lines.append(f"       <- {res_str}")
    lines += [
        "RESPONSE:",
        result.text[:2000] + ("\u2026" if len(result.text) > 2000 else ""),
        "",
    ]
    _dbg_write("\n".join(lines) + "\n")


def _debug_log_error(config: "SubagentConfig", exc: Exception) -> None:
    if not _dbg_path():
        return
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    _dbg_write(f"\n[{ts}] ERROR  model={config.model}  {type(exc).__name__}: {exc}\n")
