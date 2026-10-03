"""Customer-name cleanup."""


def normalize_name(raw: str) -> str:
    """Return *raw* with whitespace collapsed to single spaces and title-cased."""
    return " ".join(raw.split()).title()
