from textkit import slugify


def test_lowercases_and_joins_words_with_hyphens():
    assert slugify("Hello World") == "hello-world"


def test_drops_punctuation_and_collapses_runs():
    assert slugify("  Rock & Roll!! ") == "rock-roll"


def test_empty_text_gives_an_empty_slug():
    assert slugify("") == ""
