"""URL slugs."""

import re


def slugify(text: str) -> str:
    """Lowercase *text* and join its alphanumeric runs with single hyphens."""
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))
