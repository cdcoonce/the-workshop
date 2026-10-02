"""What the customer is charged at checkout. All money is whole cents."""

from __future__ import annotations

from shop.cart import LineItem, subtotal_cents


def order_total_cents(items: list[LineItem]) -> int:
    """Return the amount to charge for a cart."""
    return subtotal_cents(items)
