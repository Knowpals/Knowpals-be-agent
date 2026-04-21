from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillSpec:
    name: str
    description: str
    when_to_call: str
    system_prompt: str
    dir_name: str
    start_prompt: str = ""
    continue_prompt: str = ""


def _extract_section(text: str, header: str) -> str:
    marker = f"## {header}"
    if marker not in text:
        return ""
    after = text.split(marker, 1)[1]
    # stop at next section
    next_idx = after.find("\n## ")
    chunk = after if next_idx == -1 else after[:next_idx]
    return chunk.strip()


def load_skill_spec(skill_dir: Path) -> SkillSpec:
    text = skill_dir.joinpath("SKILL.md").read_text(encoding="utf-8")
    name = _extract_section(text, "Name").splitlines()[0].strip() if _extract_section(text, "Name") else skill_dir.name
    desc = _extract_section(text, "Purpose").strip()
    when = _extract_section(text, "When to call").strip()

    system_prompt = _extract_section(text, "Prompt (system)")
    start_prompt = _extract_section(text, "Prompt (system) - Start")
    continue_prompt = _extract_section(text, "Prompt (system) - Continue")
    if not system_prompt and not start_prompt and not continue_prompt:
        system_prompt = text.strip()

    return SkillSpec(
        name=name,
        description=desc,
        when_to_call=when,
        system_prompt=system_prompt,
        dir_name=skill_dir.name,
        start_prompt=start_prompt,
        continue_prompt=continue_prompt,
    )


def load_skill_catalog(skills_root: Path) -> list[SkillSpec]:
    out: list[SkillSpec] = []
    for p in sorted(skills_root.iterdir()):
        if not p.is_dir():
            continue
        if not (p / "SKILL.md").exists():
            continue
        out.append(load_skill_spec(p))
    return out

