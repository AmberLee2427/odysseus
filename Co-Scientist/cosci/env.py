from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_env(path: Path | str = ".env") -> None:
    load_dotenv(path, override=False)

