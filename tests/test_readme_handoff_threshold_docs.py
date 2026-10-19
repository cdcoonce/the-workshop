"""The README documents the context-warning hook's token override honestly."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugins/workbench/hooks/scripts/suggest-handoff-on-context.py"
README = (ROOT / "README.md").read_text()


def _hand_written_hooks_section() -> str:
    start = README.index("<!-- END GENERATED: hooks-table -->")
    return README[start : README.index("\n## Methodology", start)]


def test_readme_documents_env_var_default_and_example() -> None:
    default = int(re.search(r"DEFAULT_THRESHOLD = ([\d_]+)", HOOK.read_text()).group(1).replace("_", ""))
    section = _hand_written_hooks_section()
    assert "WORKSHOP_HANDOFF_CONTEXT_TOKENS" in section
    assert f"{default // 1000}k" in section
    assert re.search(r"WORKSHOP_HANDOFF_CONTEXT_TOKENS=\d+", section)
