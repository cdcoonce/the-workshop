This is a small Python library of text helpers called `textkit`, and its tests run with `uv run pytest`. Please add a function `truncate_words(text, limit)` in `src/textkit/truncate.py` and export it from the `textkit` package.

It returns `text` unchanged when it is `limit` characters or fewer. Otherwise it cuts the text at a word boundary and appends `...`, and the result, `...` included, is never longer than `limit`. Whitespace left dangling before the `...` is trimmed. If even the first word is too long to fit with the `...`, cut that word short to fit instead. For example, `truncate_words("the quick brown fox", 12)` gives `the quick...`.

I would like this built test-first. Nobody is around to answer questions, so make the calls yourself.
