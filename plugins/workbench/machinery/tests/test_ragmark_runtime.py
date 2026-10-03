"""The primary gate requires the coordinated Ragmark scope/compatibility API.

Use ordinary imports deliberately: missing or older packages must fail the
gate, rather than skip the integration suite and report a misleading green.
No model, index, or server is constructed by these capability checks.
"""

from dataclasses import fields

import pytest
from ragmark import compat, search
from ragmark.config import RagmarkConfig


@pytest.mark.parametrize(
    "name", ["scoped_folders", "excluded_filenames", "excluded_path_prefixes"]
)
def test_ragmark_has_owner_scope_fields(name: str) -> None:
    assert name in {field.name for field in fields(RagmarkConfig)}, (
        "The machinery gate requires the coordinated Ragmark scope release "
        "or its explicitly selected reviewed source."
    )


@pytest.mark.parametrize(
    ("module", "name"),
    [(compat, "note_results"), (compat, "status"), (search, "similar_notes")],
)
def test_ragmark_has_public_compatibility_api(module, name: str) -> None:
    assert callable(getattr(module, name, None)), (
        f"The machinery gate requires {module.__name__}.{name}; "
        "select the coordinated Ragmark release or reviewed source."
    )
