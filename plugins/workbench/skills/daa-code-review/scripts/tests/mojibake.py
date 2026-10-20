"""Test helper: build real cp1252 mojibake from ordinary text.

``mojibake(text)`` is what Word, Excel and Notepad show when a UTF-8 file is
opened as Windows-1252: the text is encoded to UTF-8 and each byte is mapped
through Windows-1252 to a character.

Python's strict ``cp1252`` decode raises on the five bytes Windows-1252 leaves
undefined (0x81, 0x8D, 0x8F, 0x90, 0x9D). Following WHATWG windows-1252, which
is what browsers and Word emit, each of those maps to the C1 control of the
same number (U+0081, U+008D, U+008F, U+0090, U+009D).

Parent issue: cdcoonce/the-workshop#777 (ENCODING_CORRUPTION_MAP keys were
hand-typed Latin-1-style code points, not real mojibake).
"""

_UNDEFINED_CP1252 = frozenset({0x81, 0x8D, 0x8F, 0x90, 0x9D})


def mojibake(text: str) -> str:
    """Return ``text`` as it appears when its UTF-8 bytes are read as cp1252."""
    return "".join(
        chr(b) if b in _UNDEFINED_CP1252 else bytes([b]).decode("cp1252")
        for b in text.encode("utf-8")
    )
