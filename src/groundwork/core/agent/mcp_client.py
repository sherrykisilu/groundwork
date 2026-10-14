"""MCP client plumbing.

`Toolkit` connects to one or more MCP servers over stdio, aggregates their tools into
a single namespace, and dispatches calls. Tool failures are converted into tool
results with `is_error` set rather than raised, because an agent that cannot survive a
failing tool is useless on a real engagement: in production, tools time out, return
403, and get rate limited, and the agent has to notice and change course.
"""

from __future__ import annotations

import json
import shlex
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import Client, StdioServerParameters

from .providers import ToolSpec

MAX_RESULT_CHARS = 20_000


class ToolkitError(RuntimeError):
    """Raised when a server cannot be started."""


@dataclass(frozen=True)
class ServerConfig:
    """How to launch one MCP server over stdio."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ServerConfig:
        """Build a config from suite YAML.

        `{python}` in the command or args expands to the interpreter running
        groundwork, so suites work inside a virtualenv without hardcoded paths.
        """
        if "name" not in raw:
            raise ToolkitError("server config is missing 'name'")
        raw_args = raw.get("args") or []
        if isinstance(raw_args, str):
            raw_args = shlex.split(raw_args)
        return cls(
            name=str(raw["name"]),
            command=_expand(str(raw.get("command") or "{python}")),
            args=[_expand(str(arg)) for arg in raw_args],
            env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        )


def _expand(value: str) -> str:
    return value.replace("{python}", sys.executable)


@dataclass
class ToolInvocation:
    """A recorded tool call plus its outcome."""

    name: str
    arguments: dict[str, Any]
    output: str
    is_error: bool
    duration_ms: float
    server: str


def flatten_content(content: Any) -> str:
    """Render MCP content blocks as plain text for the model."""
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
            continue
        if getattr(block, "data", None) is not None:
            parts.append(f"[{getattr(block, 'mime_type', 'binary')} content omitted]")
            continue
        parts.append(json.dumps(block, default=str))
    return "\n".join(parts)


class Toolkit:
    """An aggregated view over several MCP servers.

    Use as an async context manager::

        async with Toolkit.connect(configs) as toolkit:
            specs = toolkit.tool_specs()
            text, is_error = await toolkit.call("list_pipelines", {"factory": "..."})
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._clients: dict[str, Client] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._owner: dict[str, str] = {}
        self._real_name: dict[str, str] = {}

    @classmethod
    def connect(cls, servers: list[ServerConfig]) -> _ToolkitContext:
        """Return an async context manager that starts `servers` and yields a Toolkit."""
        return _ToolkitContext(cls, servers)

    async def start(self, servers: list[ServerConfig]) -> None:
        """Launch every server and register its tools."""
        await self._stack.__aenter__()
        for server in servers:
            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env=server.env or None,
            )
            try:
                client = await self._stack.enter_async_context(Client(params))
            except Exception as exc:  # pragma: no cover - depends on the local machine
                await self._stack.aclose()
                raise ToolkitError(f"could not start MCP server '{server.name}': {exc}") from exc
            self._clients[server.name] = client
            await self._register_tools(server.name, client)

    async def _register_tools(self, server_name: str, client: Client) -> None:
        listed = await client.list_tools()
        for tool in listed.tools:
            name = tool.name
            if name in self._specs:
                # Namespace a collision rather than silently shadowing a tool.
                name = f"{server_name}__{tool.name}"
            self._specs[name] = ToolSpec(
                name=name,
                description=tool.description or "",
                input_schema=dict(tool.input_schema or {"type": "object", "properties": {}}),
            )
            self._owner[name] = server_name
            self._real_name[name] = tool.name

    async def aclose(self) -> None:
        """Shut down every server."""
        await self._stack.aclose()

    def tool_specs(self) -> list[ToolSpec]:
        """Every tool, in the format the model expects."""
        return [self._specs[name] for name in sorted(self._specs)]

    def tool_names(self) -> list[str]:
        """Every registered tool name, sorted."""
        return sorted(self._specs)

    def has_tool(self, name: str) -> bool:
        """Whether `name` resolves to a known tool."""
        return name in self._specs

    def server_for(self, name: str) -> str:
        """Which server owns `name`."""
        return self._owner.get(name, "unknown")

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Invoke a tool. Returns `(text, is_error)` and never raises for tool failures."""
        if name not in self._specs:
            known = ", ".join(sorted(self._specs)) or "none"
            return (f"Unknown tool '{name}'. Available tools: {known}.", True)
        client = self._clients[self._owner[name]]
        try:
            result = await client.call_tool(self._real_name[name], arguments or {})
        except Exception as exc:
            return (f"Tool '{name}' raised {type(exc).__name__}: {exc}", True)
        text = flatten_content(getattr(result, "content", None))
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n...[truncated]"
        return (text, bool(getattr(result, "is_error", False)))


class _ToolkitContext:
    """Async context manager returned by `Toolkit.connect`."""

    def __init__(self, factory: type[Toolkit], servers: list[ServerConfig]) -> None:
        self._factory = factory
        self._servers = servers
        self._toolkit: Toolkit | None = None

    async def __aenter__(self) -> Toolkit:
        toolkit = self._factory()
        await toolkit.start(self._servers)
        self._toolkit = toolkit
        return toolkit

    async def __aexit__(self, *exc_info: object) -> None:
        if self._toolkit is not None:
            await self._toolkit.aclose()
