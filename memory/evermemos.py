"""EverMemOS memory backend — persistent, semantically-searchable memory.

Supports both local (Docker/open-source) and cloud deployments:
  - Local:  http://localhost:1995/api/v1   (set EVERMEMOS_BASE_URL in config.py)
  - Cloud:  https://api.evermind.ai/api/v0 (set EVERMEMOS_API_KEY in env)

Memory types used:
  - episodic_memory : analytical findings, session summaries, labelling history
  - profile         : user preferences (plot styles, channel selections)
  - event_log       : discrete facts (accuracy numbers, rule strings, file paths)

Each project maps to a group_id so memories are scoped per-project.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from memory.backend import MemoryBackend

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_RETRIEVE_METHOD = "hybrid"
_DEFAULT_TOP_K = 10
_SEARCH_TIMEOUT = 30.0
_STORE_TIMEOUT = 60.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_group_id(project_dir: Path) -> str:
    """Deterministic group_id from project path so memories are project-scoped."""
    return "adt_" + hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:12]


def _make_message_id() -> str:
    return f"adt_{uuid.uuid4().hex[:16]}"


class EverMemOSBackend(MemoryBackend):
    """Memory backend backed by EverMemOS (local or cloud).

    Implements the three MemoryBackend methods:
      store()       → POST /memories  (add a message for extraction)
      get_summary() → GET  /memories/search  (episodic_memory, broad query)
      retrieve()    → GET  /memories/search  (targeted semantic search)
    """

    def __init__(self, project_dir: str | Path) -> None:
        import config

        self.project_dir = Path(project_dir).resolve()
        self.group_id = _make_group_id(self.project_dir)
        self.project_name = self.project_dir.name

        # Endpoint config
        self.base_url = getattr(config, "EVERMEMOS_BASE_URL", "http://localhost:1995/api/v1")
        self.api_key: str | None = getattr(config, "EVERMEMOS_API_KEY", None)
        self.is_cloud = "evermind.ai" in self.base_url

        # Build headers
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

        # Track whether we've sent conversation metadata this session
        self._meta_sent = False

        # httpx async client (lazy init)
        self._client: httpx.AsyncClient | None = None

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers,
                timeout=httpx.Timeout(_STORE_TIMEOUT, connect=10.0),
            )
        return self._client

    async def _post(self, path: str, json: dict, timeout: float | None = None) -> dict:
        client = await self._get_client()
        try:
            resp = await client.post(path, json=json, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("EverMemOS POST %s failed: %s — %s", path, e.response.status_code, e.response.text[:300])
            return {"status": "failed", "message": str(e)}
        except httpx.RequestError as e:
            logger.error("EverMemOS POST %s connection error: %s", path, e)
            return {"status": "failed", "message": str(e)}

    async def _get(self, path: str, params: dict | None = None, json: dict | None = None,
                   timeout: float | None = None) -> dict:
        """GET request — uses query params for local, JSON body for cloud."""
        client = await self._get_client()
        try:
            if self.is_cloud and json:
                # Cloud search endpoint expects JSON body with GET
                req = client.build_request("GET", path, json=json, timeout=timeout)
                resp = await client.send(req)
            else:
                resp = await client.get(path, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("EverMemOS GET %s failed: %s — %s", path, e.response.status_code, e.response.text[:300])
            return {"status": "failed", "message": str(e)}
        except httpx.RequestError as e:
            logger.error("EverMemOS GET %s connection error: %s", path, e)
            return {"status": "failed", "message": str(e)}

    async def _delete(self, path: str, json: dict) -> dict:
        client = await self._get_client()
        try:
            req = client.build_request("DELETE", path, json=json)
            resp = await client.send(req)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.error("EverMemOS DELETE %s error: %s", path, e)
            return {"status": "failed", "message": str(e)}

    # ── Conversation metadata (once per session) ──────────────────────────────

    async def ensure_conversation_meta(self) -> None:
        """Send conversation metadata for this project's group_id if not yet sent."""
        if self._meta_sent:
            return
        meta: dict[str, Any] = {
            "name": f"ADT: {self.project_name}",
            "description": f"EEG/neural signal analysis project: {self.project_name}",
            "group_id": self.group_id,
            "created_at": _now_iso(),
            "default_timezone": "UTC",
            "user_details": {
                "adt_system": {"full_name": "AI Data Technician", "role": "assistant", "extra": {}},
                "user": {"full_name": "Researcher", "role": "user", "extra": {}},
            },
            "tags": ["ai-data-technician", self.project_name],
        }
        if not self.is_cloud:
            # Local API allows scene at group level; cloud inherits from global config
            meta["scene"] = "assistant"
            meta["scene_desc"] = {"description": f"AI Data Technician — {self.project_name}"}
        result = await self._post("/memories/conversation-meta", meta)
        if result.get("status") in ("ok", "queued"):
            self._meta_sent = True
            logger.info("EverMemOS conversation meta set for group %s", self.group_id)
        else:
            logger.warning("EverMemOS conversation meta failed: %s", result.get("message", ""))

    # ── MemoryBackend interface ───────────────────────────────────────────────

    async def store(self, content: str, metadata: dict) -> None:
        """Store content as a memory message.

        metadata keys:
            section  (str): used as a tag and prefix for the message
            role     (str): "user" or "assistant" (default: "assistant")
            memory_type (str): hint — not directly used by the API but useful for tagging
        """
        await self.ensure_conversation_meta()

        section = metadata.get("section", "Notes")
        role = metadata.get("role", "assistant")
        sender = "adt_system" if role == "assistant" else "user"

        payload = {
            "message_id": _make_message_id(),
            "create_time": _now_iso(),
            "sender": sender,
            "sender_name": "AI Data Technician" if role == "assistant" else "Researcher",
            "role": role,
            "content": f"[{section}] {content}",
            "group_id": self.group_id,
            "flush": True,  # trigger immediate extraction
        }

        result = await self._post("/memories", payload, timeout=_STORE_TIMEOUT)
        status = result.get("status", "failed")
        if status in ("ok", "queued"):
            logger.info("EverMemOS stored memory (section=%s, %d chars)", section, len(content))
        else:
            logger.warning("EverMemOS store failed: %s", result.get("message", ""))

    async def get_summary(self) -> str:
        """Retrieve a broad project summary from episodic memories.

        Fetches the most recent episodic memories and concatenates them.
        Falls back to empty string if EverMemOS is unreachable.
        """
        return await self.retrieve(
            query=f"project summary findings analysis {self.project_name}",
            top_k=15,
        )

    async def retrieve(self, query: str, top_k: int = 5) -> str:
        """Semantic search over stored memories.

        Returns a formatted string of the most relevant memories,
        ready to inject into an LLM context window.
        """
        await self.ensure_conversation_meta()

        # Build search request
        # Cloud only supports episodic_memory + profile; local also supports event_log
        memory_types = (
            ["episodic_memory", "profile"] if self.is_cloud
            else ["episodic_memory", "event_log"]
        )
        search_body: dict[str, Any] = {
            "query": query,
            "group_ids": [self.group_id],
            "memory_types": memory_types,
            "retrieve_method": _DEFAULT_RETRIEVE_METHOD,
            "top_k": top_k,
            "include_metadata": True,
        }

        # Local API uses query params; cloud uses JSON body
        if self.is_cloud:
            result = await self._get("/memories/search", json=search_body, timeout=_SEARCH_TIMEOUT)
        else:
            # Local open-source API — flatten for query params
            params = {
                "query": query,
                "group_id": self.group_id,
                "memory_types": "episodic_memory,event_log",
                "retrieve_method": _DEFAULT_RETRIEVE_METHOD,
                "top_k": str(top_k),
            }
            result = await self._get("/memories/search", params=params, timeout=_SEARCH_TIMEOUT)

        if result.get("status") != "ok":
            logger.warning("EverMemOS search failed: %s", result.get("message", ""))
            return ""

        return self._format_search_results(result)

    # ── Result formatting ─────────────────────────────────────────────────────

    @staticmethod
    def _format_search_results(result: dict) -> str:
        """Convert EverMemOS search response into a compact text block.

        Handles both cloud and local response shapes.
        """
        res = result.get("result", {})
        parts: list[str] = []

        # Cloud format: memories is a list of memory objects with summary field
        memories = res.get("memories", [])
        for mem in memories:
            # Cloud shape: each item is a dict with summary, keywords, etc.
            if isinstance(mem, dict) and "summary" in mem:
                summary = mem.get("summary", "")
                keywords = mem.get("keywords", [])
                timestamp = mem.get("timestamp", "")
                if summary:
                    line = summary.strip()
                    if keywords:
                        line += f"  [keywords: {', '.join(keywords)}]"
                    if timestamp:
                        line += f"  ({timestamp[:10]})"
                    parts.append(f"- {line}")

            # Local format: memories is a list of {group_id: [mem, ...]} dicts
            elif isinstance(mem, dict):
                for _gid, mems in mem.items():
                    if isinstance(mems, list):
                        for m in mems:
                            content = m.get("content", m.get("summary", m.get("text", str(m))))
                            if content:
                                parts.append(f"- {content.strip()}")

        # Also pull from profiles if present
        for profile in res.get("profiles", []):
            desc = profile.get("description", "")
            if desc:
                parts.append(f"- [profile] {desc.strip()}")

        if not parts:
            return ""

        return "\n".join(parts)

    # ── Extended operations (not in base ABC, but useful) ─────────────────────

    async def store_chat_turn(self, role: str, content: str, sender_name: str = "") -> None:
        """Store a raw chat turn as a memory (for main chat history integration).

        Unlike store(), this doesn't prefix with a section tag — it sends the
        message as-is so EverMemOS can extract memories naturally from the
        conversation flow.
        """
        await self.ensure_conversation_meta()

        sender = "user" if role == "user" else "adt_system"
        payload = {
            "message_id": _make_message_id(),
            "create_time": _now_iso(),
            "sender": sender,
            "sender_name": sender_name or ("Researcher" if role == "user" else "AI Data Technician"),
            "role": role,
            "content": content,
            "group_id": self.group_id,
        }
        await self._post("/memories", payload, timeout=_STORE_TIMEOUT)

    async def search_profiles(self, user_id: str = "user", top_k: int = 5) -> str:
        """Search profile memories (user preferences, identity attributes)."""
        search_body: dict[str, Any] = {
            "query": "",
            "user_id": user_id,
            "group_ids": [self.group_id],
            "memory_types": ["profile"],
            "retrieve_method": "keyword",
            "top_k": top_k,
        }
        if self.is_cloud:
            result = await self._get("/memories/search", json=search_body, timeout=_SEARCH_TIMEOUT)
        else:
            params = {
                "query": "",
                "group_id": self.group_id,
                "memory_types": "profile",
                "retrieve_method": "keyword",
                "top_k": str(top_k),
            }
            result = await self._get("/memories/search", params=params, timeout=_SEARCH_TIMEOUT)

        if result.get("status") != "ok":
            return ""
        return self._format_search_results(result)

    async def get_all_memories(
        self, memory_type: str = "episodic_memory", page: int = 1, page_size: int = 20
    ) -> dict:
        """List all memories (paginated) — useful for debugging and review."""
        body = {
            "group_ids": [self.group_id],
            "memory_type": memory_type,
            "page": page,
            "page_size": page_size,
        }
        if self.is_cloud:
            return await self._get("/memories", json=body, timeout=_SEARCH_TIMEOUT)
        else:
            params = {
                "group_id": self.group_id,
                "memory_type": memory_type,
                "page": str(page),
                "page_size": str(page_size),
            }
            return await self._get("/memories", params=params, timeout=_SEARCH_TIMEOUT)

    async def delete_project_memories(self) -> dict:
        """Delete all memories for this project's group_id. Use with caution."""
        return await self._delete("/memories", {
            "memory_id": "__all__",
            "user_id": "__all__",
            "group_id": self.group_id,
        })

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
