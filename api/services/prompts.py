"""PromptLibrary — renders the Jinja2 prompt templates in the top-level ``prompts/``
directory (09). Prompts live outside the app code so they're easy to edit.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

# repo_root/prompts  (this file is repo_root/api/services/prompts.py)
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class PromptLibrary:
    def __init__(self, prompts_dir: Path | str = PROMPTS_DIR) -> None:
        self.dir = Path(prompts_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.dir)),
            autoescape=select_autoescape(enabled_extensions=()),  # plain text, no HTML escaping
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, name: str, /, **vars) -> str:
        """Render ``<name>.md.j2`` with the given variables."""
        template = self.env.get_template(f"{name}.md.j2")
        return template.render(**vars).strip()
