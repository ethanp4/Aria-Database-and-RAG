-- Aria Phase 3 / 03: rules, JSONB validation, the polymorphic interface and encapsulation.
-- Run after 02_product_seed.sql has filled product_kind, specs and the subclass tables.
--
--   Inheritance     shared columns live once in products; subclass columns only in their table.
--   Polymorphism    v_product_catalogue + fn_describe_product / fn_care_interval_months /
--                   fn_care_due_date work on ANY product and answer differently per subclass.
--   Encapsulation   the class is used through the view and SQL functions (its operations);
--                   role aria_catalogue_app may use those and nothing else.
--   Business rules  enforced inside PostgreSQL, not in application code:
--                   R1 disjoint subclasses      composite FK + fixed product_kind (01_hierarchy_tables.sql)
--                   R2 complete hierarchy       every product has its subclass row at COMMIT (trigger)
--                   R3 valid specs JSON         CHECK constraint products_specs_valid
--                   R4 neoprene has thickness   CHECK on wearable_gear (01)
--                   R5 verified purchases       trigger on product_reviews (04_reviews.sql)

-- ---------------------------------------------------------------------------
-- Discriminator and specs are now mandatory; specs must have the expected shape (R3)
-- ---------------------------------------------------------------------------
ALTER TABLE products
    ALTER COLUMN product_kind SET NOT NULL,
    ALTER COLUMN specs SET NOT NULL,
    ADD CONSTRAINT products_specs_valid CHECK (
        jsonb_typeof(specs) = 'object'
        -- required key with a numeric, positive value
        AND CASE WHEN jsonb_typeof(specs -> 'weight_g') = 'number'
                 THEN (specs ->> 'weight_g')::numeric > 0 ELSE FALSE END
        -- optional keys must have the right JSON type when present
        AND jsonb_typeof(COALESCE(specs -> 'colours',         '[]')) = 'array'
        AND jsonb_typeof(COALESCE(specs -> 'certifications',  '[]')) = 'array'
        AND jsonb_typeof(COALESCE(specs -> 'sizes',           '[]')) = 'array'
        AND jsonb_typeof(COALESCE(specs -> 'compatible_with', '[]')) = 'array'
        AND jsonb_typeof(COALESCE(specs -> 'features',        '{}')) = 'object'
        -- every element of the nested arrays carries its required keys
        AND NOT jsonb_path_exists(specs, '$.sizes[*] ? (!(exists(@.size)) || !(exists(@.available)))')
        AND NOT jsonb_path_exists(specs, '$.compatible_with[*] ? (!(exists(@.sku)))')
    );

-- GIN index for @>, @? and @@ on specs. jsonb_path_ops is smaller and faster than the default
-- jsonb_ops for containment / jsonpath, but does not support the key-exists operators (? ?| ?&).
CREATE INDEX products_specs_gin ON products USING gin (specs jsonb_path_ops);
CREATE INDEX products_kind_idx  ON products (product_kind);

-- ---------------------------------------------------------------------------
-- R2: completeness. Product is abstract: every products row must have exactly one subclass row.
-- A DEFERRED constraint trigger checks at COMMIT, so a product and its subclass row can be
-- inserted in either order inside one transaction (that is what fn_add_product does).
-- ---------------------------------------------------------------------------
CREATE FUNCTION fn_check_product_subclass() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    pid  BIGINT := CASE WHEN TG_OP = 'DELETE' THEN OLD.product_id ELSE NEW.product_id END;
    kind VARCHAR(20);
    ok   BOOLEAN;
BEGIN
    SELECT product_kind INTO kind FROM products WHERE product_id = pid;
    IF NOT FOUND THEN
        RETURN NULL;                     -- the product itself was deleted: nothing left to check
    END IF;
    ok := CASE kind
        WHEN 'WEARABLE'     THEN EXISTS (SELECT 1 FROM wearable_gear          WHERE product_id = pid)
        WHEN 'LIFE_SUPPORT' THEN EXISTS (SELECT 1 FROM life_support_equipment WHERE product_id = pid)
        WHEN 'ELECTRONICS'  THEN EXISTS (SELECT 1 FROM dive_electronics       WHERE product_id = pid)
        WHEN 'ACCESSORY'    THEN EXISTS (SELECT 1 FROM safety_accessory       WHERE product_id = pid)
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Product % is a % but has no row in its subclass table', pid, kind
            USING ERRCODE = 'check_violation',
                  HINT = 'Create products through fn_add_product(), which writes both rows.';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER trg_products_have_subclass
    AFTER INSERT OR UPDATE OF product_kind ON products
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_check_product_subclass();
CREATE CONSTRAINT TRIGGER trg_wearable_keeps_parent_complete
    AFTER DELETE ON wearable_gear
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_check_product_subclass();
CREATE CONSTRAINT TRIGGER trg_life_support_keeps_parent_complete
    AFTER DELETE ON life_support_equipment
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_check_product_subclass();
CREATE CONSTRAINT TRIGGER trg_electronics_keeps_parent_complete
    AFTER DELETE ON dive_electronics
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_check_product_subclass();
CREATE CONSTRAINT TRIGGER trg_accessory_keeps_parent_complete
    AFTER DELETE ON safety_accessory
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_check_product_subclass();

-- ---------------------------------------------------------------------------
-- Polymorphic interface: one view over the whole hierarchy.
-- Shared columns come from products; each subclass contributes its own columns (NULL for the
-- others) and its own implementation of describe() and careIntervalMonths().
-- ---------------------------------------------------------------------------
CREATE VIEW v_product_catalogue AS
SELECT p.product_id, p.sku, p.name, c.name AS category, p.product_kind,
       p.unit_price, p.stock_quantity, p.is_active, p.specs,
       -- describe(): text built differently for each subclass
       CASE p.product_kind
           WHEN 'WEARABLE' THEN
               initcap(replace(w.fit_type, '_', ' ')) || ', ' || w.material
               || COALESCE(', ' || w.thickness_mm || ' mm', '')
           WHEN 'LIFE_SUPPORT' THEN
               format('service every %s months, rated to %s m%s', ls.service_interval_months,
                      ls.max_depth_m, CASE WHEN ls.cold_water_rated THEN ', cold-water rated' ELSE '' END)
           WHEN 'ELECTRONICS' THEN
               format('%s battery, %s h, %s-month warranty',
                      lower(replace(de.battery_type, '_', ' ')), de.battery_life_h, de.warranty_months)
           WHEN 'ACCESSORY' THEN
               format('visibility %s/5%s', sa.visibility_rating,
                      CASE WHEN sa.corrosion_resistant THEN ', corrosion resistant' ELSE '' END)
       END AS kind_detail,
       -- careIntervalMonths(): each subclass has its own maintenance rule
       CASE p.product_kind
           WHEN 'LIFE_SUPPORT' THEN ls.service_interval_months          -- technician overhaul
           WHEN 'ELECTRONICS'  THEN de.warranty_months                  -- battery/warranty check
           WHEN 'WEARABLE'     THEN CASE WHEN w.material = 'neoprene' THEN 24 ELSE 36 END
           WHEN 'ACCESSORY'    THEN 12                                  -- annual inspection
       END AS care_interval_months,
       CASE p.product_kind
           WHEN 'LIFE_SUPPORT' THEN 'regulator/BCD service by a technician'
           WHEN 'ELECTRONICS'  THEN 'battery check before the warranty ends'
           WHEN 'WEARABLE'     THEN CASE WHEN w.material = 'neoprene' THEN 'replace compressed neoprene'
                                         ELSE 'replace straps and seals' END
           WHEN 'ACCESSORY'    THEN 'annual safety inspection'
       END AS care_rule,
       -- subclass-only attributes (NULL when they do not apply)
       w.material, w.thickness_mm, w.fit_type,
       ls.service_interval_months, ls.max_depth_m, ls.cold_water_rated,
       de.battery_type, de.battery_life_h, de.warranty_months,
       sa.visibility_rating, sa.corrosion_resistant
FROM products p
LEFT JOIN categories             c  ON c.category_id = p.category_id
LEFT JOIN wearable_gear          w  ON w.product_id  = p.product_id
LEFT JOIN life_support_equipment ls ON ls.product_id = p.product_id
LEFT JOIN dive_electronics       de ON de.product_id = p.product_id
LEFT JOIN safety_accessory       sa ON sa.product_id = p.product_id;

COMMENT ON VIEW v_product_catalogue IS
    'Polymorphic read interface over Product and its four subclasses (Phase 3 Part A)';

-- Operations of the Product class, as SQL functions --------------------------------------
CREATE FUNCTION fn_describe_product(p_product_id BIGINT) RETURNS TEXT
LANGUAGE sql STABLE AS $$
    SELECT name || ' [' || product_kind || ']: ' || kind_detail
    FROM v_product_catalogue WHERE product_id = p_product_id
$$;

CREATE FUNCTION fn_care_interval_months(p_product_id BIGINT) RETURNS INTEGER
LANGUAGE sql STABLE AS $$
    SELECT care_interval_months FROM v_product_catalogue WHERE product_id = p_product_id
$$;

-- careDueDate(purchasedOn): when the owner should next service / check this product
CREATE FUNCTION fn_care_due_date(p_product_id BIGINT, p_purchased_on DATE) RETURNS DATE
LANGUAGE sql STABLE AS $$
    SELECT (p_purchased_on + make_interval(months => care_interval_months))::date
    FROM v_product_catalogue WHERE product_id = p_product_id
$$;

-- Product.create(...): the only supported way to add a product. Writes the superclass row and the
-- right subclass row in one transaction, so callers never touch the tables directly.
CREATE FUNCTION fn_add_product(p_kind VARCHAR, p_sku VARCHAR, p_name VARCHAR, p_category_id BIGINT,
                               p_unit_price NUMERIC, p_specs JSONB, p_attrs JSONB)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO products (sku, name, category_id, unit_price, product_kind, specs)
    VALUES (p_sku, p_name, p_category_id, p_unit_price, p_kind, p_specs)
    RETURNING product_id INTO v_id;

    CASE p_kind
        WHEN 'WEARABLE' THEN
            INSERT INTO wearable_gear (product_id, material, thickness_mm, fit_type)
            VALUES (v_id, p_attrs ->> 'material', (p_attrs ->> 'thickness_mm')::numeric, p_attrs ->> 'fit_type');
        WHEN 'LIFE_SUPPORT' THEN
            INSERT INTO life_support_equipment (product_id, service_interval_months, max_depth_m, cold_water_rated)
            VALUES (v_id, (p_attrs ->> 'service_interval_months')::smallint,
                    (p_attrs ->> 'max_depth_m')::smallint, (p_attrs ->> 'cold_water_rated')::boolean);
        WHEN 'ELECTRONICS' THEN
            INSERT INTO dive_electronics (product_id, battery_type, battery_life_h, warranty_months)
            VALUES (v_id, p_attrs ->> 'battery_type', (p_attrs ->> 'battery_life_h')::smallint,
                    (p_attrs ->> 'warranty_months')::smallint);
        WHEN 'ACCESSORY' THEN
            INSERT INTO safety_accessory (product_id, visibility_rating, corrosion_resistant)
            VALUES (v_id, (p_attrs ->> 'visibility_rating')::smallint, (p_attrs ->> 'corrosion_resistant')::boolean);
    END CASE;                          -- an unknown kind already failed products_kind_valid
    RETURN v_id;
END $$;

-- ---------------------------------------------------------------------------
-- Encapsulation for real: a catalogue-app role that can use the interface but not the tables.
-- (Roles are cluster-wide, so create it only once.)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aria_catalogue_app') THEN
        CREATE ROLE aria_catalogue_app NOLOGIN;
    END IF;
END $$;
REVOKE ALL ON products, wearable_gear, life_support_equipment, dive_electronics, safety_accessory
    FROM aria_catalogue_app;
GRANT SELECT ON v_product_catalogue TO aria_catalogue_app;
REVOKE EXECUTE ON FUNCTION fn_add_product(VARCHAR, VARCHAR, VARCHAR, BIGINT, NUMERIC, JSONB, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_add_product(VARCHAR, VARCHAR, VARCHAR, BIGINT, NUMERIC, JSONB, JSONB),
                          fn_describe_product(BIGINT), fn_care_interval_months(BIGINT),
                          fn_care_due_date(BIGINT, DATE)
    TO aria_catalogue_app;

-- fresh planner statistics for the new columns (keeps the EXPLAIN plans in B1 reproducible)
VACUUM ANALYZE products;
