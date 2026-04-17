from __future__ import annotations

from pathlib import Path


class PromptLoader:
    def __init__(self, prompt_dir: Path) -> None:
        self.prompt_dir = prompt_dir

    def load(self, filename: str, **kwargs: str) -> str:
        template = (self.prompt_dir / filename).read_text(encoding="utf-8").strip()
        if kwargs:
            template = template.format(**kwargs)
        return template
