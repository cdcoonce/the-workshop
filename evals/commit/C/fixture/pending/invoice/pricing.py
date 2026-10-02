"""Line-item pricing, in integer cents."""

BULK_THRESHOLD = 10
BULK_DISCOUNT_PERCENT = 10


def line_total(unit_price_cents: int, quantity: int) -> int:
    """Return the cost of *quantity* units at *unit_price_cents* each."""
    return unit_price_cents * quantity


def bulk_total(unit_price_cents: int, quantity: int) -> int:
    """Return the line cost, with the bulk discount once *quantity* reaches the threshold."""
    total = line_total(unit_price_cents, quantity)
    if quantity >= BULK_THRESHOLD:
        return total - total * BULK_DISCOUNT_PERCENT // 100
    return total
