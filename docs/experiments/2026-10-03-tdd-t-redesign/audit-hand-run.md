# tdd T redesign hand-run: audit pack (2026-10-04)

Case: evals/tdd/T at dev d2cd497 (fixture fingerprint ebfb934e783dae00565902095b992401094b922b8e5adec33af371589fff2700). Sonnet (general-purpose) case agents: 6 skill-arm executions (dispatch prompt = the harness's build_dispatch_prompt, i.e. 'Use the workbench:tdd skill for this task.' plus the T prompt) and 3 no-skill-arm executions (build_no_skill_prompt), each preceded by one fixture-path line because the Agent tool cannot set a working directory. One fresh fixture copy per execution. Every transcript was status=complete, copied after its completion notice and cmp-verified. The raw transcripts were machine-local and are not committed; this pack is the record.

Items: T1 (gate candidate): a failing test result before the first possible source write, a change under src/, final suite green, src-reverted suite red. T2 and T3 are trend.

Scoring history: the nine transcripts were scored twice. At dev b32d5eb the Bash classifier read skill arm 4's call 4 (a read-only for/cat loop) as a source write, so T1 scored 5 of 6 in the skill arm. The owner's audit found that a false miss; the classifier was corrected (pull request #1123, dev d2cd497) and the same nine transcripts were re-scored with no new executions. The call classes below are the d2cd497 reading. Only skill arm 4's T1 changed (miss to hit).


## skill arm 1 (agent a143bcfd)
T1=hit T2=hit T3=hit; ordering conjunct (red before first source write) = True; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Skill [-]: workbench:tdd
2. Bash [none]: cd <s>/hrT-s1 && git status --short && find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50 && cat docs/plan.md
3. Bash [none]: cd <s>/hrT-s1 && find . -path ./.venv -prune -o -type f -print | head -50 && echo ---- && cat docs/plan.md
4. Bash [none]: cd <s>/hrT-s1 && cat pyproject.toml src/shop/*.py tests/*.py && uv run pytest -q 2>&1 | tail -15
5. Bash [tests]: cd <s>/hrT-s1 && cat >> tests/test_cart.py <<'EOF' ;  ;  ; def test_ten_units_get_fifteen_percent_off_with_discount_rounded_down(): ;     # 3330 total, discount floor(499.5) = 499 ;     assert line_total_cents(LineItem("A1", 333, 10)) == 2831 ; EOF ; uv run pytest -q 2>&1 | tail -8
6. Bash [source]: cd <s>/hrT-s1 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''    """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''    """Return what one line costs: unit price times quantity, less any bulk disco
7. Bash [tests]: cd <s>/hrT-s1 && python3 - <<'EOF' ; p='tests/test_cart.py' ; s=open(p).read() ; s=s.replace("    assert subtotal_cents(items) == subtotal_cents(items)\n","    assert subtotal_cents(items) == 1500\n") ; s+=''' ;  ; def test_nine_units_are_not_discounted(): ;     assert line_total_cents(LineItem("A1"
8. Bash [tests]: cd <s>/hrT-s1 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_subtotal_just_under_threshold_pays_shipping(): ;     assert order_total_cents([LineItem("A1", 7499, 1)]) == 7499 + 599 ;  ;  ; def test_subtotal_at_threshold_ships_free(): ;     assert order_total_cents([LineItem("A1", 7500, 1)]
9. Bash [source]: cd <s>/hrT-s1 && python3 - <<'EOF' ; p='src/shop/checkout.py' ; s=open(p).read() ; s=s.replace('''def order_total_cents(items: list[LineItem]) -> int: ;     """Return the amount to charge for a cart.""" ;     return subtotal_cents(items) ; ''','''SHIPPING_CENTS = 599 ; FREE_SHIPPING_SUBTOTAL_CENTS =
10. Bash [source]: cd <s>/hrT-s1 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_non_empty_cart_with_zero_subtotal_still_pays_shipping(): ;     assert order_total_cents([LineItem("FREEBIE", 0, 1)]) == 599 ; EOF ; uv run pytest -q 2>&1 | tail -3 ; python3 - <<'EOF' ; p='src/shop/checkout.py' ; s=open(p).read(
11. Bash [source]: cd <s>/hrT-s1 && cp -r src ../hrT-s1-src-bak ; run(){ find src -name __pycache__ -exec rm -rf {} + 2>/dev/null; uv run pytest -q -p no:cacheprovider 2>&1 | tail -1; } ; sed -i '' 's/quantity >= 10/quantity > 10/' src/shop/cart.py; echo "qty>10:"; run; rm -rf src; cp -r ../hrT-s1-src-bak src ; sed -i

## skill arm 2 (agent a08d238c)
T1=hit T2=miss T3=hit; ordering conjunct (red before first source write) = True; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Skill [-]: workbench:tdd
2. Bash [none]: cd <s>/hrT-s2 && git status --short && find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50 && cat docs/plan.md
3. Bash [none]: cd <s>/hrT-s2 && find . -path ./.venv -prune -o -type f -print | grep -v __pycache__ | head -50 && cat docs/plan.md
4. Bash [none]: cd <s>/hrT-s2 && cat pyproject.toml src/shop/*.py tests/*.py && uv run pytest -q 2>&1 | tail -5
5. Bash [tests]: cd <s>/hrT-s2 && python3 - <<'EOF' ; p='tests/test_cart.py' ; s=open(p).read() ; s=s.replace("    assert subtotal_cents(items) == subtotal_cents(items)\n","    assert subtotal_cents(items) == 1500\n") ; s+=''' ;  ; def test_ten_units_get_fifteen_percent_off_line_total_rounded_down(): ;     # 3330 ce
6. Bash [source]: cd <s>/hrT-s2 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''def line_total_cents(item: LineItem) -> int: ;     """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''BULK_MIN_QUANTITY = 10 ; BULK_DISC
7. Bash [source]: cd <s>/hrT-s2 && python3 - <<'EOF' ; p='src/shop/checkout.py' ; s=open(p).read() ; s=s.replace('''def order_total_cents(items: list[LineItem]) -> int: ;     """Return the amount to charge for a cart.""" ;     return subtotal_cents(items) ; ''','''SHIPPING_CENTS = 599 ; FREE_SHIPPING_MIN_SUBTOTAL_CEN
8. Bash [source]: cd <s>/hrT-s2 && cp src/shop/checkout.py ../checkout.bak && cp src/shop/cart.py ../cart.bak ; sed -i '' 's/subtotal >= FREE/subtotal > FREE/' src/shop/checkout.py && uv run pytest -q 2>&1 | tail -2; cp ../checkout.bak src/shop/checkout.py ; sed -i '' 's/item.quantity >= BULK/item.quantity > BULK/' s

## skill arm 3 (agent aa150d9b)
T1=hit T2=hit T3=hit; ordering conjunct (red before first source write) = True; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Skill [-]: workbench:tdd
2. Bash [none]: cd <s>/hrT-s3 && git status --short | head; find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50; cat docs/plan.md
3. Bash [none]: cd <s>/hrT-s3 && cat pyproject.toml src/shop/*.py tests/*.py; uv run pytest 2>&1 | tail -5
4. Bash [tests]: cd <s>/hrT-s3 && cat >> tests/test_cart.py <<'EOF' ;  ;  ; def test_ten_units_get_fifteen_percent_off_with_discount_rounded_down(): ;     # 3330 cents, discount floor(499.5) = 499 ;     assert line_total_cents(LineItem("A1", 333, 10)) == 2831 ;  ;  ; def test_nine_units_are_not_discounted(): ;     a
5. Bash [source]: cd <s>/hrT-s3 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''    """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''    """Return what one line costs, with 15% off for 10 or more units. ;  ;     Th
6. Bash [tests]: cd <s>/hrT-s3 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_subtotal_just_under_threshold_pays_shipping(): ;     assert order_total_cents([LineItem("A1", 7499, 1)]) == 7499 + 599 ;  ;  ; def test_subtotal_at_threshold_ships_free(): ;     assert order_total_cents([LineItem("A1", 7500, 1)]
7. Bash [source]: cd <s>/hrT-s3 && python3 - <<'EOF' ; p='src/shop/checkout.py' ; s=open(p).read() ; s=s.replace('''def order_total_cents(items: list[LineItem]) -> int: ;     """Return the amount to charge for a cart.""" ;     return subtotal_cents(items) ; ''','''SHIPPING_CENTS = 599 ; FREE_SHIPPING_MIN_SUBTOTAL_CEN

## skill arm 4 (agent a0364116)
T1=hit T2=hit T3=hit; ordering conjunct (red before first source write) = True; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Skill [-]: workbench:tdd
2. Bash [none]: cd <s>/hrT-s4 && git status --short && find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50 && cat docs/plan.md
3. Bash [none]: cd <s>/hrT-s4 && find . -path ./.venv -prune -o -type f -print | grep -v __pycache__ | head -50; echo ---; cat docs/plan.md
4. Bash [none]: cd <s>/hrT-s4 && for f in pyproject.toml src/shop/*.py tests/*.py; do echo "=== $f"; cat $f; done; uv run pytest -q 2>&1 | tail -15
5. Bash [tests]: cd <s>/hrT-s4 && cat >> tests/test_cart.py <<'EOF' ;  ;  ; def test_ten_or_more_units_get_fifteen_percent_off_the_line_with_discount_rounded_down(): ;     # 3330 total, 15% = 499.5 -> discount floors to 499 ;     assert line_total_cents(LineItem("A1", 333, 10)) == 2831 ;  ;  ; def test_nine_units_ar
6. Bash [source]: cd <s>/hrT-s4 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''def line_total_cents(item: LineItem) -> int: ;     """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''BULK_QUANTITY = 10 ; BULK_DISCOUNT
7. Bash [tests]: cd <s>/hrT-s4 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_subtotal_just_under_threshold_pays_flat_shipping(): ;     assert order_total_cents([LineItem("A1", 7499, 1)]) == 7499 + 599 ;  ;  ; def test_subtotal_at_threshold_ships_free(): ;     assert order_total_cents([LineItem("A1", 7500
8. Bash [source]: cd <s>/hrT-s4 && python3 - <<'EOF' ; p='src/shop/checkout.py' ; s=open(p).read() ; s=s.replace('''def order_total_cents(items: list[LineItem]) -> int: ;     """Return the amount to charge for a cart.""" ;     return subtotal_cents(items) ; ''','''SHIPPING_CENTS = 599 ; FREE_SHIPPING_THRESHOLD_CENTS 
9. Bash [tests]: cd <s>/hrT-s4 && sed -i 's/assert subtotal_cents(items) == subtotal_cents(items)/assert subtotal_cents(items) == 1500/' tests/test_cart.py && uv run pytest -q 2>&1 | tail -3
10. Edit [-]: <s>/hrT-s4/tests/test_cart.py
11. Bash [none]: cd <s>/hrT-s4 && uv run pytest -q 2>&1 | tail -3

## skill arm 5 (agent ad3fc184)
T1=hit T2=hit T3=hit; ordering conjunct (red before first source write) = True; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Skill [-]: workbench:tdd
2. Bash [none]: cd <s>/hrT-s5 && git status --short && find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50 && cat docs/plan.md
3. Bash [none]: cd <s>/hrT-s5 && find . -path ./.venv -prune -o -type f -print | grep -v __pycache__ | head -50; echo ---; cat docs/plan.md
4. Bash [none]: cd <s>/hrT-s5 && cat pyproject.toml src/shop/*.py tests/*.py; uv run pytest -q 2>&1 | tail -15
5. Bash [tests]: cd <s>/hrT-s5 && cat >> tests/test_cart.py <<'EOF' ;  ;  ; def test_bulk_line_of_ten_gets_fifteen_percent_off_rounded_down(): ;     # 3330 total, discount floor(3330 * 0.15) = 499 ;     assert line_total_cents(LineItem("A1", 333, 10)) == 2831 ;  ;  ; def test_line_below_ten_units_is_not_discounted()
6. Bash [source]: cd <s>/hrT-s5 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''    """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''    """Return what one line costs: unit price times quantity, less bulk discount.
7. Bash [source]: cd <s>/hrT-s5 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_subtotal_just_under_threshold_pays_shipping(): ;     assert order_total_cents([LineItem("A1", 7499, 1)]) == 7499 + 599 ;  ;  ; def test_subtotal_at_threshold_ships_free(): ;     assert order_total_cents([LineItem("A1", 7500, 1)]
8. Bash [tests]: cd <s>/hrT-s5 && sed -i 's/assert subtotal_cents(items) == subtotal_cents(items)/assert subtotal_cents(items) == 1500/' tests/test_cart.py && uv run pytest -q 2>&1 | tail -3
9. Edit [-]: <s>/hrT-s5/tests/test_cart.py
10. Bash [none]: cd <s>/hrT-s5 && uv run pytest -q 2>&1 | tail -3

## skill arm 6 (agent a52a54ec)
T1=hit T2=hit T3=miss; ordering conjunct (red before first source write) = True; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Skill [-]: workbench:tdd
2. Bash [none]: cd <s>/hrT-s6 && git status --short | head; find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print | head -50; cat docs/plan.md
3. Bash [none]: cd <s>/hrT-s6 && cat pyproject.toml src/shop/*.py tests/*.py; uv run pytest -q 2>&1 | tail -5
4. Bash [tests]: cd <s>/hrT-s6 && cat >> tests/test_cart.py <<'EOF' ;  ;  ; def test_bulk_line_gets_fifteen_percent_off_with_discount_rounded_down(): ;     # 3330 total, discount floor(499.5) = 499 ;     assert line_total_cents(LineItem("A1", 333, 10)) == 2831 ;  ;  ; def test_line_just_below_bulk_threshold_is_uncha
5. Bash [source]: cd <s>/hrT-s6 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''    """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''    """Return what one line costs, with 15% off for 10 or more units. ;  ;     Th
6. Bash [tests]: cd <s>/hrT-s6 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_subtotal_just_under_free_shipping_threshold_pays_shipping(): ;     assert order_total_cents([LineItem("A1", 7499, 1)]) == 7499 + 599 ;  ;  ; def test_subtotal_at_free_shipping_threshold_ships_free(): ;     assert order_total_cen
7. Bash [source]: cd <s>/hrT-s6 && cat > src/shop/checkout.py <<'EOF' ; """What the customer is charged at checkout. All money is whole cents.""" ;  ; from __future__ import annotations ;  ; from shop.cart import LineItem, subtotal_cents ;  ; SHIPPING_CENTS = 599 ; FREE_SHIPPING_MIN_SUBTOTAL_CENTS = 7500 ;  ;  ; def 
8. Bash [source]: cd <s>/hrT-s6 && cat >> tests/test_checkout.py <<'EOF' ;  ;  ; def test_nonempty_cart_with_zero_subtotal_still_pays_shipping(): ;     assert order_total_cents([LineItem("FREEBIE", 0, 1)]) == 599 ; EOF ; uv run pytest -q 2>&1 | tail -3 ; python3 - <<'EOF' ; p='src/shop/checkout.py' ; s=open(p).read()

## no-skill arm 1 (agent a7cdbdb0)
T1=miss T2=miss T3=hit; ordering conjunct (red before first source write) = False; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Bash [none]: cd <s>/hrT-n1 && git status --short && find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print && cat docs/plan.md && cat src/*/*.py 2>/dev/null | head -200
2. Bash [none]: cd <s>/hrT-n1 && find . -path ./.venv -prune -o -type f -print | head -50 && cat docs/plan.md
3. Bash [none]: cd <s>/hrT-n1 && cat src/shop/*.py tests/*.py pyproject.toml
4. Bash [source]: cd <s>/hrT-n1 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''def line_total_cents(item: LineItem) -> int: ;     """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''BULK_MIN_QUANTITY = 10 ; BULK_DISC

## no-skill arm 2 (agent a73326d3)
T1=miss T2=miss T3=hit; ordering conjunct (red before first source write) = False; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Bash [none]: cd <s>/hrT-n2 && git status --short && find . -path ./.git -prune -o -path ./.venv -prune -o -type f -print && cat docs/plan.md && cat src/*/*.py 2>/dev/null | head -200
2. Bash [none]: cd <s>/hrT-n2 && find . -path ./.venv -prune -o -type f -print | head -50; cat docs/plan.md
3. Bash [none]: cd <s>/hrT-n2 && cat pyproject.toml src/shop/*.py tests/*.py
4. Bash [source]: cd <s>/hrT-n2 && python3 - <<'EOF' ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''def line_total_cents(item: LineItem) -> int: ;     """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''BULK_MIN_QUANTITY = 10 ; BULK_DISC

## no-skill arm 3 (agent a583329e)
T1=miss T2=miss T3=hit; ordering conjunct (red before first source write) = False; final suite 'exit=0', src-reverted suite 'exit=1', paths changed under src/: ['src/shop/cart.py', 'src/shop/checkout.py']

1. Bash [none]: cd <s>/hrT-n3 && git ls-files && cat docs/plan.md && cat $(git ls-files | grep -E '\.py$')
2. Bash [none]: cd <s>/hrT-n3 && find . -path ./.venv -prune -o -type f -not -path './.git/*' -print | head -50; cat docs/plan.md
3. Bash [none]: cd <s>/hrT-n3 && cat pyproject.toml src/shop/*.py tests/*.py; uv run pytest 2>&1 | tail -15
4. Bash [source]: cd <s>/hrT-n3 && python3 - <<'EOF' ; import re ; p='src/shop/cart.py' ; s=open(p).read() ; s=s.replace('''def line_total_cents(item: LineItem) -> int: ;     """Return what one line costs: unit price times quantity.""" ;     return item.unit_price_cents * item.quantity ; ''','''BULK_MIN_QUANTITY = 10
