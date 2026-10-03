from shop.cart import LineItem
from shop.checkout import order_total_cents


def test_order_total_of_empty_cart_is_zero():
    assert order_total_cents([]) == 0


def test_order_total_for_a_large_cart():
    items = [LineItem("A1", 4000, 2), LineItem("B2", 2000, 2)]
    assert order_total_cents(items) == 12000
