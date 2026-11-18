-- A1  Part A: inheritance, polymorphism, encapsulation and in-database business rules
-- Business question: The catalogue has four very different kinds of gear. Can staff and the
--   chatbot treat every product the same way (one list, one "describe", one "when is it due for
--   care") while each kind keeps its own attributes and rules?
-- This file makes NO lasting changes: every write is rolled back or rejected.
-- It contains 5 deliberate errors, each marked EXPECTED ERROR.

-- ---------------------------------------------------------------------------
-- 1. INHERITANCE: shared attributes are defined once (products); each subclass table holds only
--    its own attributes plus the key it inherits.
-- ---------------------------------------------------------------------------
SELECT table_name,
       count(*) AS columns,
       string_agg(column_name, ', ' ORDER BY ordinal_position) AS column_list
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('products', 'wearable_gear', 'life_support_equipment', 'dive_electronics', 'safety_accessory')
GROUP BY table_name
ORDER BY table_name = 'products' DESC, table_name;

-- the IS-A link: every subclass row joins to exactly one product (and inherits its columns)
SELECT p.product_id, p.sku, p.name, p.unit_price, w.material, w.thickness_mm, w.fit_type
FROM products p JOIN wearable_gear w USING (product_id)
WHERE p.sku IN ('SUIT-002', 'MASK-001', 'GEN-BOOT-04');

-- ---------------------------------------------------------------------------
-- 2. POLYMORPHISM: one query over the whole hierarchy. kind_detail (describe()) and
--    care_interval_months / fn_care_due_date (careDueDate()) are computed differently per subclass.
-- ---------------------------------------------------------------------------
WITH sample AS (
    SELECT *, row_number() OVER (PARTITION BY product_kind ORDER BY product_id) AS n
    FROM v_product_catalogue
)
SELECT product_kind, sku, name, kind_detail, care_rule,
       care_interval_months AS months,
       fn_care_due_date(product_id, DATE '2026-06-01') AS care_due_if_bought_2026_06_01
FROM sample
WHERE n <= 2
ORDER BY product_kind, sku;

-- the same polymorphic operation used for a real business question: for every delivered order
-- line, when does that item next need attention? (customers due for a care reminder this year)
SELECT v.product_kind,
       count(*) AS items_sold,
       count(*) FILTER (WHERE fn_care_due_date(v.product_id, o.delivered_at::date) <= DATE '2026-12-31')
           AS care_due_by_end_of_2026
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id AND o.delivered_at IS NOT NULL
JOIN v_product_catalogue v ON v.product_id = oi.product_id
GROUP BY v.product_kind
ORDER BY v.product_kind;

-- ---------------------------------------------------------------------------
-- 3. ENCAPSULATION: the catalogue app role can only use the class's interface
--    (view + functions), never the underlying tables.
-- ---------------------------------------------------------------------------
BEGIN;
SET LOCAL ROLE aria_catalogue_app;

SELECT count(*) AS products_visible_through_view FROM v_product_catalogue;

SAVEPOINT direct_table_access;
-- EXPECTED ERROR: permission denied for table products (no direct table access)
SELECT sku, unit_price FROM products LIMIT 1;
ROLLBACK TO SAVEPOINT direct_table_access;

-- creating a product through the class operation writes BOTH rows atomically
SELECT fn_add_product(
    'ELECTRONICS', 'GEN-COMP-99', 'Demo wrist dive computer', 5, 429.00,
    '{"weight_g": 118, "colours": ["black"], "features": {"nitrox": true, "max_o2_pct": 40, "gas_mixes": 2}}',
    '{"battery_type": "RECHARGEABLE_LI_ION", "battery_life_h": 45, "warranty_months": 24}') AS new_product_id
\gset
SELECT fn_describe_product(:new_product_id) AS describe,
       fn_care_due_date(:new_product_id, DATE '2026-11-18') AS care_due;
RESET ROLE;
ROLLBACK;                          -- demo only: the new product is not kept

-- ---------------------------------------------------------------------------
-- 4. BUSINESS RULES ENFORCED BY THE DATABASE (not by application code)
-- ---------------------------------------------------------------------------
-- R1 disjoint: product 1 is a mask (WEARABLE); it cannot also become an electronics row.
-- EXPECTED ERROR: violates foreign key constraint "electronics_is_a_product"
INSERT INTO dive_electronics (product_id, battery_type, battery_life_h, warranty_months)
VALUES (1, 'RECHARGEABLE_LI_ION', 40, 24);

-- R1 again: a product cannot silently switch subclass while its subclass row exists.
-- EXPECTED ERROR: update on "products" violates foreign key constraint "wearable_is_a_product"
UPDATE products SET product_kind = 'ACCESSORY' WHERE product_id = 1;

-- R2 complete: Product is abstract. A bare products row with no subclass row is rejected when the
-- transaction commits (deferred constraint trigger).
BEGIN;
INSERT INTO products (sku, name, category_id, unit_price, product_kind, specs)
VALUES ('GEN-ORPHAN-01', 'Product with no subclass row', 5, 10.00, 'ELECTRONICS', '{"weight_g": 50}');
-- EXPECTED ERROR at COMMIT: Product ... is a ELECTRONICS but has no row in its subclass table
COMMIT;

-- R5 verified purchase: account 1 cannot claim a verified review on an order that is not theirs.
-- EXPECTED ERROR: Review cannot be verified
INSERT INTO product_reviews (product_id, account_id, order_id, rating, title, body)
SELECT oi.product_id, (SELECT min(account_id) FROM accounts WHERE account_type = 'user' AND account_id <> o.account_id),
       o.order_id, 5, 'Fake verified review', 'Trying to attach someone else''s order.'
FROM orders o JOIN order_items oi USING (order_id)
WHERE o.delivered_at IS NOT NULL AND o.account_id IS NOT NULL
ORDER BY o.order_id LIMIT 1;

-- nothing above changed the data
SELECT count(*) AS products, (SELECT count(*) FROM product_reviews) AS reviews FROM products;
