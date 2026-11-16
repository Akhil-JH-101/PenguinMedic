"""Load required Markdown skills from the PenguinMedic project directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = PROJECT_ROOT / "skills"


def load_skill(skill_name: str) -> str:
    """Load a non-empty skill file or fail closed with a clear error."""
    allowed = {"diagnostics.md", "recovery.md"}
    if skill_name not in allowed:
        raise ValueError(f"Unsupported PenguinMedic skill: {skill_name}")

    skill_path = SKILL_DIR / skill_name
    if skill_path.is_symlink() or not skill_path.is_file():
        raise RuntimeError(f"Required skill file is missing or invalid: {skill_path}")

    content = skill_path.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError(f"Required skill file is empty: {skill_path}")

    return content
