-- Q08  Views: a customer-safe order summary and a staff-only refund queue
-- Business question: How do we give each audience exactly the columns it is allowed to see,
--   without copying the join logic into every screen and report?
--   * v_order_summary: one row per order with items, masked payment, carrier tracking link and
--     refunded amount. It has NO payment token and NO risk score, so it is safe for customer
--     pages and for the chatbot's order context.
--   * v_staff_refund_queue: open refund requests, oldest first, WITH the risk score and the
--     duplicate-attempt count. Staff/admin only.
-- Techniques: CREATE VIEW over 6 tables, LEFT JOIN LATERAL for the latest payment and per-order
--   aggregates, string masking, COMMENT ON VIEW to document the access rule.

CREATE OR REPLACE VIEW v_order_summary AS
SELECT o.order_id,
       o.created_at,
       o.status,
       COALESCE(a.username, 'guest')                         AS customer,
       o.account_id,
       o.contact_name,
       items.item_lines,
       items.units,
       o.total_amount,
       CASE WHEN pay.last4 IS NOT NULL THEN pay.card_brand || ' **** ' || pay.last4
            ELSE initcap(replace(pay.method_type, '_', ' ')) END AS payment,
       pay.status                                            AS payment_status,
       c.name                                                AS carrier,
       replace(c.tracking_url_template, '{tracking_number}', o.tracking_number) AS tracking_url,
       round(extract(epoch FROM o.delivered_at - o.shipped_at)::numeric / 86400, 1) AS transit_days,
       COALESCE(ref.refunded, 0)                             AS refunded_amount
FROM orders o
LEFT JOIN accounts a ON a.account_id = o.account_id
LEFT JOIN carriers c ON c.carrier_id = o.carrier_id
LEFT JOIN LATERAL (                                    -- most recent payment attempt
    SELECT p.method_type, p.card_brand, p.last4, p.status
    FROM payments p
    WHERE p.order_id = o.order_id
    ORDER BY p.created_at DESC
    LIMIT 1
) pay ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS item_lines, sum(oi.quantity) AS units
    FROM order_items oi
    WHERE oi.order_id = o.order_id
) items ON TRUE
LEFT JOIN LATERAL (
    SELECT sum(r.amount) AS refunded
    FROM refunds r
    WHERE r.order_id = o.order_id AND r.status = 'COMPLETED'
) ref ON TRUE;

COMMENT ON VIEW v_order_summary IS
    'Customer-safe order summary: masked payment only, no token, no risk_score. Filter by account_id for a customer.';

CREATE OR REPLACE VIEW v_staff_refund_queue AS
SELECT r.refund_id,
       r.requested_at,
       now() - r.requested_at                      AS waiting,
       r.order_id,
       COALESCE(a.username, 'guest')               AS customer,
       r.amount,
       o.total_amount                              AS order_total,
       round(100 * r.amount / o.total_amount, 1)   AS pct_of_order,
       r.reason,
       r.status,
       r.risk_score,
       (SELECT count(*) FROM duplicate_refund_attempts d
         WHERE d.order_id = r.order_id)            AS duplicate_attempts,
       (SELECT count(*) FROM refunds r2 JOIN orders o2 ON o2.order_id = r2.order_id
         WHERE o.account_id IS NOT NULL AND o2.account_id = o.account_id
           AND r2.refund_id <> r.refund_id)        AS customer_prior_refunds
FROM refunds r
JOIN orders o ON o.order_id = r.order_id
LEFT JOIN accounts a ON a.account_id = o.account_id
WHERE r.status IN ('REQUESTED', 'APPROVED');

COMMENT ON VIEW v_staff_refund_queue IS
    'STAFF/ADMIN ONLY: includes risk_score. Never expose to customers or customer-facing chatbot answers.';

-- Use 1: a customer's order history page (only their own rows: filter by account_id).
-- Picks the customer with the most orders so the example has several rows.
SELECT order_id, created_at::date AS ordered, status, item_lines, units, total_amount,
       payment, carrier, transit_days, refunded_amount
FROM v_order_summary
WHERE account_id = (SELECT account_id FROM orders WHERE account_id IS NOT NULL
                    GROUP BY account_id ORDER BY count(*) DESC, account_id LIMIT 1)
ORDER BY created_at DESC;

-- Use 2: the staff refund queue, riskiest first.
SELECT refund_id, requested_at::date AS requested, order_id, customer, amount, pct_of_order,
       reason, risk_score, duplicate_attempts, customer_prior_refunds
FROM v_staff_refund_queue
ORDER BY risk_score DESC, requested_at;
