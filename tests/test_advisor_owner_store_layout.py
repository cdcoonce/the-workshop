"""The advisor SKILL.md files name the owner store as the ``local/`` folder."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ADVISORS = ["advisor-product-design", "advisor-product-strategy"]


@pytest.mark.parametrize("name", ADVISORS)
def test_skill_store_path_is_local_folder(name: str) -> None:
    """Load order points at ``personas/<name>/local/``, not the bare root."""
    text = (ROOT / f"plugins/{name}/skills/{name}/SKILL.md").read_text()
    assert f"~/.workshop/personas/{name}/local/" in text
