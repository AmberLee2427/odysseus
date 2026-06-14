"""Minimal async client for using the authenticated Codex CLI as an LLM provider."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import websockets


class CodexAppServerError(RuntimeError):
    pass


def _conversation_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    system_parts: list[str] = []
    transcript: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        text = str(content or "").strip()
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
        else:
            transcript.append(f"{role.upper()}:\n{text}")

    instructions = "\n\n".join(system_parts)
    instructions += (
        "\n\nYou are serving as a conversational model inside Odysseus. "
        "Do not call Codex app-server tools directly. When the supplied "
        "instructions describe Odysseus tools, request them by emitting the "
        "exact textual tool syntax they specify; Odysseus will execute them "
        "and return their results. Do not claim those tools or the active "
        "workspace are unavailable merely because you cannot call Codex tools. "
        "Follow the supplied conversation and return the assistant's next response."
    )
    return instructions.strip(), "\n\n".join(transcript).strip()


class CodexAppServerProcess:
    def __init__(self, binary: str | None = None):
        self.binary = binary or os.getenv("CODEX_BIN", "codex")
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._cwd: tempfile.TemporaryDirectory | None = None
        self._websocket = None

    async def __aenter__(self):
        self._cwd = tempfile.TemporaryDirectory(prefix="odysseus-codex-provider-")
        remote_url = os.getenv("CODEX_APP_SERVER_URL", "").strip()
        if remote_url:
            token = os.getenv("CODEX_APP_SERVER_TOKEN", "").strip()
            token_file = os.getenv("CODEX_APP_SERVER_TOKEN_FILE", "").strip()
            if not token and token_file:
                token = Path(token_file).read_text(encoding="utf-8").strip()
            headers = {"Authorization": f"Bearer {token}"} if token else None
            self._websocket = await websockets.connect(
                remote_url,
                additional_headers=headers,
                open_timeout=5,
            )
            self._reader_task = asyncio.create_task(self._read_websocket_messages())
        else:
            self.process = await asyncio.create_subprocess_exec(
                self.binary,
                "app-server",
                cwd=self._cwd.name,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(self._read_stdio_messages())
            self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "odysseus",
                    "title": "Odysseus",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized", {})
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._websocket:
            await self._websocket.close()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self._reader_task:
            self._reader_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._cwd:
            self._cwd.cleanup()

    async def _send(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message)
        if self._websocket:
            await self._websocket.send(encoded)
            return
        if not self.process or not self.process.stdin:
            raise CodexAppServerError("Codex app-server is not running")
        self.process.stdin.write((encoded + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": params})
        return await future

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def _handle_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id in self._pending and ("result" in message or "error" in message):
            future = self._pending.pop(request_id)
            if "error" in message:
                future.set_exception(CodexAppServerError(str(message["error"])))
            else:
                future.set_result(message.get("result"))
            return
        if request_id is not None and message.get("method"):
            await self._respond_to_server_request(message)
            return
        if message.get("method"):
            await self._notifications.put(message)

    async def _read_stdio_messages(self) -> None:
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            await self._handle_message(message)
        self._fail_pending()

    async def _read_websocket_messages(self) -> None:
        try:
            async for raw in self._websocket:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle_message(message)
        finally:
            self._fail_pending()

    async def _drain_stderr(self) -> None:
        assert self.process and self.process.stderr
        while await self.process.stderr.readline():
            pass

    def _fail_pending(self) -> None:
        error = CodexAppServerError("Codex app-server connection closed unexpectedly")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _respond_to_server_request(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "applyPatchApproval",
            "execCommandApproval",
        }:
            result = {"decision": "decline"}
        elif method == "item/tool/requestUserInput":
            result = {"answers": {}}
        elif method == "item/tool/call":
            result = {
                "success": False,
                "contentItems": [{"type": "inputText", "text": "Tool is unavailable in provider mode."}],
            }
        else:
            await self._send(
                {"id": message["id"], "error": {"code": -32601, "message": f"Unsupported: {method}"}}
            )
            return
        await self._send({"id": message["id"], "result": result})

    async def models(self) -> list[str]:
        account = await self.request("account/read", {})
        if account.get("requiresOpenaiAuth") and not account.get("account"):
            raise CodexAppServerError("Codex is not authenticated; run `codex login`")
        models: list[str] = []
        cursor = None
        while True:
            result = await self.request("model/list", {"cursor": cursor} if cursor else {})
            models.extend(item["model"] for item in result.get("data", []) if item.get("model"))
            cursor = result.get("nextCursor")
            if not cursor:
                return models

    async def stream_chat(
        self, messages: list[dict[str, Any]], model: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        instructions, prompt = _conversation_prompt(messages)
        thread_result = await self.request(
            "thread/start",
            {
                "cwd": str(Path(self._cwd.name)),
                "model": model,
                "ephemeral": True,
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "developerInstructions": instructions,
            },
        )
        thread_id = thread_result["thread"]["id"]
        await self.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt or "Respond to the conversation."}],
                "model": model,
                "approvalPolicy": "never",
            },
        )

        while True:
            event = await self._notifications.get()
            method = event.get("method")
            params = event.get("params") or {}
            if params.get("threadId") not in {None, thread_id}:
                continue
            if method == "item/agentMessage/delta" and params.get("delta"):
                yield {"type": "text", "text": params["delta"]}
            elif method == "thread/tokenUsage/updated":
                usage = (params.get("tokenUsage") or {}).get("last") or {}
                yield {"type": "usage", "usage": usage}
            elif method == "error":
                raise CodexAppServerError((params.get("error") or {}).get("message") or "Codex failed")
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("status") == "failed":
                    raise CodexAppServerError((turn.get("error") or {}).get("message") or "Codex turn failed")
                return


async def list_codex_models() -> list[str]:
    async with CodexAppServerProcess() as client:
        return await client.models()


async def stream_codex_chat(messages: list[dict[str, Any]], model: str):
    async with CodexAppServerProcess() as client:
        async for event in client.stream_chat(messages, model):
            yield event
