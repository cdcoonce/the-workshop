"""Line-item pricing, in integer cents."""


def line_total(unit_price_cents: int, quantity: int) -> int:
    """Return the cost of *quantity* units at *unit_price_cents* each."""
    return unit_price_cents * quantity
