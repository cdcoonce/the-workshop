"""Line items and cart subtotals. All money is whole cents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    """One product line in a cart."""

    sku: str
    unit_price_cents: int
    quantity: int


def line_total_cents(item: LineItem) -> int:
    """Return what one line costs: unit price times quantity."""
    return item.unit_price_cents * item.quantity


def subtotal_cents(items: list[LineItem]) -> int:
    """Return the sum of every line's total."""
    return sum(line_total_cents(item) for item in items)
