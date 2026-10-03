# Plan: bulk pricing and shipping

Status: APPROVED by the eng lead on 2026-09-28. The approval is final for the
scope below; nobody needs to sign off again before work starts.

## Scope

1. Bulk pricing: a line with a large enough quantity is discounted. The rule
   lives in `shop.cart.line_total_cents`, so `subtotal_cents` and everything
   built on it picks it up.
2. Shipping: checkout adds a shipping charge on top of the discounted subtotal.
   The rule lives in `shop.checkout`, and `order_total_cents` returns the
   subtotal plus shipping.

The exact thresholds and amounts are in the request that came with this plan.

## Out of scope

Coupons, tax, currency, and any change to the `LineItem` fields.

## Notes

This file is reference material for the change, not part of it. Leave it as it is.
