-- OO / JSONB mapping, part 1: store each Order as one JSONB document.
-- Run while connected to aria_phase2 (after SQL_Scripts/run_all).
--
-- The document mirrors the Order class in order_model.py:
--   embedded objects: customer, contact, shipping_address, billing_address, payment,
--                     shipment, totals
--   embedded arrays:  items[], refunds[]
-- The relational tables stay the source of truth (authoritative copy). order_document is a
-- read model rebuilt from them by fn_order_document(), e.g. for an API response, an export,
-- or the chatbot's order context. It never contains the payment token or the risk score.

CREATE OR REPLACE FUNCTION fn_order_document(p_order_id bigint)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
SELECT jsonb_build_object(
    'schema_version', 1,
    'order_id',       o.order_id,
    'status',         o.status,
    'created_at',     o.created_at,
    'confirmed_at',   o.confirmed_at,
    'customer',       CASE WHEN a.account_id IS NULL THEN NULL
                           ELSE jsonb_build_object('account_id', a.account_id, 'username', a.username) END,
    'contact',        jsonb_build_object('name', o.contact_name, 'email', o.contact_email),
    'shipping_address', jsonb_build_object(
                          'kind', 'shipping', 'line1', o.ship_line1, 'line2', o.ship_line2,
                          'city', o.ship_city, 'region', o.ship_region,
                          'postal_code', o.ship_postal_code, 'country', o.ship_country),
    'billing_address',  jsonb_build_object(
                          'kind', 'billing', 'line1', o.bill_line1, 'line2', o.bill_line2,
                          'city', o.bill_city, 'region', o.bill_region,
                          'postal_code', o.bill_postal_code, 'country', o.bill_country),
    'items', (SELECT jsonb_agg(jsonb_build_object(
                         'sku', p.sku, 'name', p.name, 'category', c.name,
                         'quantity', oi.quantity, 'unit_price', oi.unit_price,
                         'line_total', oi.line_total)
                     ORDER BY oi.order_item_id)
              FROM order_items oi
              JOIN products p ON p.product_id = oi.product_id
              LEFT JOIN categories c ON c.category_id = p.category_id
              WHERE oi.order_id = o.order_id),
    'payment', (SELECT CASE WHEN pay.last4 IS NOT NULL
                            THEN jsonb_build_object('type', 'card', 'method', pay.method_type,
                                                    'brand', pay.card_brand, 'last4', pay.last4,
                                                    'status', pay.status)
                            ELSE jsonb_build_object('type', 'wallet', 'method', pay.method_type,
                                                    'status', pay.status) END
                FROM payments pay
                WHERE pay.order_id = o.order_id
                ORDER BY pay.created_at DESC
                LIMIT 1),
    'shipment', jsonb_build_object(
                    'method', o.shipping_method, 'carrier', cr.name,
                    'tracking_number', o.tracking_number,
                    'tracking_url', replace(cr.tracking_url_template, '{tracking_number}', o.tracking_number),
                    'shipped_at', o.shipped_at, 'delivered_at', o.delivered_at),
    'totals', jsonb_build_object('subtotal', o.subtotal, 'shipping', o.shipping_cost,
                                 'tax', o.tax_amount, 'total', o.total_amount, 'currency', 'CAD'),
    'refunds', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                    'refund_id', r.refund_id, 'amount', r.amount, 'status', r.status,
                                    'reason', r.reason, 'requested_at', r.requested_at)
                                ORDER BY r.requested_at)
                         FROM refunds r WHERE r.order_id = o.order_id), '[]'::jsonb)
)
FROM orders o
LEFT JOIN accounts a  ON a.account_id = o.account_id
LEFT JOIN carriers cr ON cr.carrier_id = o.carrier_id
WHERE o.order_id = p_order_id
$$;

DROP TABLE IF EXISTS order_document;
CREATE TABLE order_document (
    order_id    BIGINT PRIMARY KEY,
    doc         JSONB       NOT NULL,
    built_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT order_document_order_fk FOREIGN KEY (order_id)
        REFERENCES orders (order_id) ON DELETE CASCADE,
    -- light structural checks; the full shape is validated by Order.from_dict() in Python
    CONSTRAINT order_document_id_matches CHECK ((doc ->> 'order_id')::bigint = order_id),
    CONSTRAINT order_document_has_items CHECK (jsonb_typeof(doc -> 'items') = 'array'
                                               AND jsonb_array_length(doc -> 'items') > 0),
    CONSTRAINT order_document_version CHECK (doc ? 'schema_version'),
    -- the read model must never carry secrets
    CONSTRAINT order_document_no_secrets CHECK (NOT doc @? '$.**.token' AND NOT doc @? '$.**.risk_score')
);

COMMENT ON TABLE order_document IS
    'Read model: one JSONB document per order, rebuilt from the relational tables (which stay authoritative).';

-- jsonb_path_ops GIN index: small and fast for containment (@>) and jsonpath (@?, @@) queries
CREATE INDEX idx_order_document_doc ON order_document USING GIN (doc jsonb_path_ops);

INSERT INTO order_document (order_id, doc)
SELECT o.order_id, fn_order_document(o.order_id)
FROM orders o
ORDER BY o.order_id;

ANALYZE order_document;

SELECT count(*) AS documents,
       pg_size_pretty(pg_total_relation_size('order_document')) AS table_plus_index_size
FROM order_document;

-- one complete document, pretty-printed: a registered customer's delivered, card-paid order
-- with a completed partial refund (the same document is saved as sample_order_document.json)
SELECT jsonb_pretty(doc) AS sample_document
FROM order_document
ORDER BY doc @> '{"status": "DELIVERED", "payment": {"type": "card"}}' DESC,
         doc @? '$.refunds[*] ? (@.status == "COMPLETED")' DESC,
         jsonb_typeof(doc -> 'customer') = 'object' DESC,
         jsonb_array_length(doc -> 'items') DESC,
         order_id
LIMIT 1;
