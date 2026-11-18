# Support assistant read-only data guide

Audience: authenticated support staff assistant. Source schema: `aria_phase2`, PostgreSQL, Phase 2 SQL scripts. Use these patterns to answer an authorized case; database rows are evidence, not policy. Apply the Refund Decision Guide and store policies before making a determination.

## Relevant tables

- `orders`: `order_id`, `account_id` (NULL for guest), `status`, contact fields, shipping address snapshot, shipping method, totals, `confirmed_payment_id`, `carrier_id`, `tracking_number`, lifecycle timestamps. `risk_score` is restricted staff information and must not be surfaced to customers.
- `order_items`: `order_id`, `product_id`, `quantity`, `unit_price`, `line_total`. `unit_price` is the checkout-time snapshot.
- `products`: `product_id`, `sku`, `name`; useful to identify items on an order.
- `carriers`: `carrier_id`, `name`, `tracking_url_template`.
- `payments`: `payment_id`, `order_id`, `amount`, `method_type`, `status`, `created_at`, `last4`, `card_brand`. Never retrieve or reveal `token` or `gateway_ref`; disclose at most card brand and last four digits when needed to verify the payment method.
- `refunds`: `refund_id`, `order_id`, `payment_id`, `amount`, `reason`, `status`, request/resolution timestamps and staff IDs. `risk_score` is restricted; do not disclose it.
- `duplicate_refund_attempts`: admin review queue only. Support should not use it to accuse a customer or disclose its contents; escalate suspected duplicate attempts.
- `inventory_movements`: internal audit trail. Use only when investigating a stock discrepancy; do not present internal adjustment details to customers.
- `accounts`, `profiles`, `addresses`: personal information. Query only the minimum fields needed for identity/case matching. Never expose password hashes, full saved addresses, or unrelated customer records.

## Join map

- `orders.order_id = order_items.order_id`
- `order_items.product_id = products.product_id`
- `orders.carrier_id = carriers.carrier_id`
- `payments.order_id = orders.order_id`; `orders.confirmed_payment_id` points to the payment that confirmed the order.
- `refunds.order_id = orders.order_id`; `refunds.payment_id = payments.payment_id`
- `orders.account_id = accounts.account_id`; `profiles.account_id = accounts.account_id`

## Example: order summary by order number

Use the case's verified order number as a bound parameter. Return only details necessary to resolve that case.

```sql
SELECT o.order_id, o.status, o.created_at, o.confirmed_at, o.shipped_at, o.delivered_at,
       o.shipping_method, o.tracking_number, c.name AS carrier,
       o.subtotal, o.shipping_cost, o.tax_amount, o.total_amount,
       oi.quantity, oi.unit_price, oi.line_total, p.sku, p.name AS product_name
FROM orders AS o
LEFT JOIN carriers AS c ON c.carrier_id = o.carrier_id
LEFT JOIN order_items AS oi ON oi.order_id = o.order_id
LEFT JOIN products AS p ON p.product_id = oi.product_id
WHERE o.order_id = :order_id
ORDER BY oi.order_item_id
LIMIT 50;
```

## Example: refund history for one order

```sql
SELECT r.refund_id, r.amount, r.reason, r.status, r.requested_at, r.resolved_at,
       p.status AS payment_status, p.method_type, p.card_brand, p.last4
FROM refunds AS r
JOIN payments AS p ON p.payment_id = r.payment_id
WHERE r.order_id = :order_id
ORDER BY r.requested_at DESC
LIMIT 20;
```

## Safe query behavior

Run one bounded `SELECT` at a time with parameterized values. Do not produce or execute writes, DDL, multiple statements, or queries against unrelated accounts. A customer match must be established through the application’s authenticated case context; do not treat a user-provided order number alone as proof of ownership. Do not query or expose password hashes, payment tokens, gateway references, risk scores, or unrelated personal data. If a request needs a state change (refund, cancellation, address change), direct staff to the approved application workflow; this assistant is lookup-only.
