from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

from cosci.models import RuntimeProfile
from cosci.prompts import SYSTEM_INSTRUCTIONS


@dataclass
class AgyClient:
    profile: RuntimeProfile
    workspace: Path

    async def ask(self, prompt: str) -> str:
        agy = shutil.which(self.profile.agy_path) or self.profile.agy_path
        full_prompt = f"{SYSTEM_INSTRUCTIONS.strip()}\n\nUser task:\n{prompt.strip()}"
        args = [
            agy,
            "--print-timeout",
            self.profile.print_timeout,
            "--model",
            self.profile.model,
            "--add-dir",
            str(self.workspace),
            "--print",
            full_prompt,
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self.workspace),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            raise

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            detail = err or out or f"exit code {proc.returncode}"
            raise RuntimeError(f"agy failed: {detail}")
        return out


