"""Customer-name cleanup."""


def normalize_name(raw: str) -> str:
    """Return *raw* trimmed and title-cased."""
    return raw.strip().title()
