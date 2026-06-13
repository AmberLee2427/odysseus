from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity import types as ag_types
from google.antigravity.hooks import policy

from cosci.models import RuntimeProfile
from cosci.prompts import SYSTEM_INSTRUCTIONS


@dataclass
class AntigravityClient:
    profile: RuntimeProfile
    workspace: Path
    save_dir: Path
    api_key: str | None = None

    async def ask(self, prompt: str) -> str:
        api_key = self.api_key or os.environ.get(self.profile.api_key_env)
        if not self.profile.vertex and not api_key:
            raise RuntimeError(
                "Antigravity SDK does not expose Google AI subscription auth. "
                f"Set {self.profile.api_key_env}, pass an API key explicitly, "
                "or use Vertex with --vertex --project --location."
            )
        if self.profile.vertex and not api_key:
            if not (self.profile.project and self.profile.location):
                raise RuntimeError(
                    "Vertex mode requires either an API key or both "
                    "--project and --location."
                )
        config = LocalAgentConfig(
            system_instructions=SYSTEM_INSTRUCTIONS,
            capabilities=ag_types.CapabilitiesConfig(
                enabled_tools=[
                    ag_types.BuiltinTools.LIST_DIR,
                    ag_types.BuiltinTools.SEARCH_DIR,
                    ag_types.BuiltinTools.FIND_FILE,
                    ag_types.BuiltinTools.VIEW_FILE,
                    ag_types.BuiltinTools.FINISH,
                ],
                enable_subagents=False,
            ),
            policies=policy.deny_all(),
            workspaces=[str(self.workspace)],
            save_dir=str(self.save_dir),
            gemini_config=ag_types.GeminiConfig(
                api_key=api_key,
                vertex=self.profile.vertex,
                project=self.profile.project,
                location=self.profile.location,
                models=ag_types.ModelConfig(
                    default=ag_types.ModelEntry(
                        name=self.profile.model,
                        generation=ag_types.GenerationConfig(
                            thinking_level=ag_types.ThinkingLevel(
                                self.profile.thinking_level
                            )
                        ),
                    )
                ),
            ),
        )
        async with Agent(config) as agent:
            response = await agent.chat(prompt)
            return await response.text()
