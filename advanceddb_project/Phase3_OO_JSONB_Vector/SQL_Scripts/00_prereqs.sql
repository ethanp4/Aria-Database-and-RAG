-- Aria Phase 3 / 00: prerequisites.
-- Run while connected to aria_phase2, AFTER the Phase 2 build
-- (Phase2_Implementation/SQL_Scripts/run_all.*). Phase 3 extends that database in place.
--
-- pgvector must be installed on the server first:
--   * Windows (EDB installer): pgvector ships with PostgreSQL 18 (share/extension/vector.control),
--     or use Stack Builder; on Linux: apt install postgresql-18-pgvector
--   * Docker: image pgvector/pgvector:pg18
--   * Neon / Supabase: already available, just run CREATE EXTENSION.

-- stop early with a clear message if the Phase 2 schema is missing
DO $$
BEGIN
    IF to_regclass('public.products') IS NULL OR to_regclass('public.order_items') IS NULL THEN
        RAISE EXCEPTION 'aria_phase2 is not built: run Phase2_Implementation/SQL_Scripts/run_all first';
    END IF;
END $$;

-- Phase 3 must be re-runnable: remove the Phase 3 objects if a previous run left them behind.
DROP VIEW IF EXISTS v_product_catalogue CASCADE;
DROP TABLE IF EXISTS eval_queries, review_embeddings, product_reviews,
                     wearable_gear, life_support_equipment, dive_electronics, safety_accessory CASCADE;
DROP FUNCTION IF EXISTS fn_add_product, fn_care_interval_months, fn_care_due_date, fn_describe_product,
                        fn_check_product_subclass, fn_check_verified_purchase, fn_search_reviews CASCADE;
ALTER TABLE products DROP COLUMN IF EXISTS product_kind CASCADE,
                     DROP COLUMN IF EXISTS specs CASCADE;

CREATE EXTENSION IF NOT EXISTS vector;

SELECT current_database() AS database,
       split_part(version(), ' on ', 1) AS server,
       (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector;
