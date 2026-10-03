from shop.cart import LineItem, line_total_cents, subtotal_cents


def test_line_total_multiplies_price_by_quantity():
    assert line_total_cents(LineItem("A1", 250, 3)) == 750


def test_subtotal_of_empty_cart_is_zero():
    assert subtotal_cents([]) == 0


def test_subtotal_adds_up_line_items():
    items = [LineItem("A1", 250, 2), LineItem("B2", 1000, 1)]
    assert subtotal_cents(items) == subtotal_cents(items)
