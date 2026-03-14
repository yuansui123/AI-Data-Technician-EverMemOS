"""Unified subagent invocation layer.

All subagent calls go through invoke().  Primitives call this with max_iterations=1
and no tools.  Reasoners call it with a tool list and a ToolExecutor instance.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
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


# ── Tool executor protocol ─────────────────────────────────────────────────────

ToolExecutorFn = Callable[[str, dict], Awaitable[str]]


class ToolExecutor:
    """Dispatches tool_use blocks to the appropriate primitive handler.

    Extend by registering additional handlers for domain tools.
    """

    def __init__(self, project_dir: str | None = None):
        self.project_dir = project_dir
        self._handlers: dict[str, ToolExecutorFn] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._handlers["bash_execute"] = self._bash
        self._handlers["vision_analyze"] = self._vision

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
        from subagents.primitives.bash import bash
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
        from subagents.primitives.vision import vision
        result = await vision(
            image_path=inp["image_path"],
            context=inp.get("context", {}),
        )
        return json.dumps(result, indent=2)


# ── Core invoke ───────────────────────────────────────────────────────────────

EventCallback = Callable[[dict], Awaitable[None]] | None


async def invoke(
    config: SubagentConfig,
    messages: list[dict],
    tool_executor: ToolExecutor | None = None,
    on_event: EventCallback = None,
) -> SubagentResult:
    """Call the LLM with a tool-use loop up to config.max_iterations.

    For single-pass subagents (Plan, Think, Code) use max_iterations=1.
    For tool-use reasoners (Explore, Statistics) pass a ToolExecutor.
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

        # API call — stream text deltas when on_event is provided
        def _retry_delay(_exc, _attempt: int) -> float:
            if isinstance(_exc, anthropic.InternalServerError):
                return 3.0 * (_attempt + 1)   # 3s, 6s, 9s, 12s
            return 10.0 * (2 ** _attempt)      # 10s, 20s, 40s …

        _debug_log_request(config, all_messages, iteration)
        text_parts: list[str] = []
        _api_exc: Exception | None = None
        if on_event:
            for _attempt in range(6):
                try:
                    async with client.messages.stream(**kwargs) as stream:
                        async for text in stream.text_stream:
                            await on_event({"type": "text_delta", "delta": text})
                            text_parts.append(text)
                        response = await stream.get_final_message()
                    _api_exc = None
                    break
                except (anthropic.RateLimitError, anthropic.InternalServerError) as _exc:
                    _api_exc = _exc
                    if _attempt == 5:
                        _debug_log_error(config, _exc)
                        raise
                    text_parts.clear()
                    await asyncio.sleep(_retry_delay(_exc, _attempt))
        else:
            for _attempt in range(6):
                try:
                    response = await client.messages.create(**kwargs)
                    _api_exc = None
                    break
                except (anthropic.RateLimitError, anthropic.InternalServerError) as _exc:
                    _api_exc = _exc
                    if _attempt == 5:
                        _debug_log_error(config, _exc)
                        raise
                    await asyncio.sleep(_retry_delay(_exc, _attempt))
        iteration += 1

        # accumulate usage
        if hasattr(response, "usage") and response.usage:
            total_usage["input_tokens"] += getattr(response.usage, "input_tokens", 0)
            total_usage["output_tokens"] += getattr(response.usage, "output_tokens", 0)

        # extract thinking and tool_use blocks from response
        # (text_parts already populated from stream; for non-streaming, extract from content)
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
            final_text = iteration_text  # keep last non-empty text across iterations

        # single-pass or no tool calls → done
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        # max iterations reached → stop even if model wants more tools
        if iteration >= config.max_iterations:
            hit_iteration_limit = True
            break

        # no executor → can't run tools
        if tool_executor is None:
            break

        # execute tools and continue loop
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

    # If we exited the loop mid-tool-use (hit max_iterations while still calling tools,
    # or produced no text at all), make one final no-tools call to get a summary response.
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


# ── Debug logging helpers ──────────────────────────────────────────────────────

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
    """Log what is about to be sent to the LLM."""
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

    sep = "─" * 60
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [
        "",
        "=" * 80,
        f"[{ts}] REQUEST  model={config.model}  iter={iteration+1}/{config.max_iterations}",
        "=" * 80,
        "SYSTEM:",
        (config.system_prompt[:800] + "…") if len(config.system_prompt) > 800 else config.system_prompt,
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
    """Log the final result after a successful invoke()."""
    if not _dbg_path():
        return
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    sep = "─" * 60
    lines = [
        sep,
        f"[{ts}] RESULT  iters={result.iterations}  tokens={result.usage.get('total_tokens','?')}",
    ]
    if result.thinking:
        lines += ["THINKING:", result.thinking[:600] + ("…" if len(result.thinking) > 600 else "")]
    for tc in result.tool_calls:
        inp_str = json.dumps(tc.get("input", {}), ensure_ascii=False)[:300]
        res_str = str(tc.get("result", ""))[:300]
        lines.append(f"  TOOL → {tc.get('tool')}  {inp_str}")
        lines.append(f"       ← {res_str}")
    lines += [
        "RESPONSE:",
        result.text[:2000] + ("…" if len(result.text) > 2000 else ""),
        "",
    ]
    _dbg_write("\n".join(lines) + "\n")


def _debug_log_error(config: "SubagentConfig", exc: Exception) -> None:
    """Log an API error."""
    if not _dbg_path():
        return
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    _dbg_write(f"\n[{ts}] ERROR  model={config.model}  {type(exc).__name__}: {exc}\n")
