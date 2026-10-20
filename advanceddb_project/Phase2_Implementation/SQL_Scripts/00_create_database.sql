-- Aria Phase 2: create the course database.
-- Run while connected to the default "postgres" database (psql or pgAdmin Query Tool).
-- This is a separate database from the Django app's "aria" database, which Django
-- migrations own. Nothing in Phase 2 touches "aria".
--
-- WARNING: drops aria_phase2 if it exists, so every run starts from a clean slate.

DROP DATABASE IF EXISTS aria_phase2 WITH (FORCE);

CREATE DATABASE aria_phase2
    ENCODING 'UTF8'
    TEMPLATE template0;

-- Seed timestamps are UTC; reports group by UTC day/month in every client (psql, pgAdmin).
ALTER DATABASE aria_phase2 SET timezone TO 'UTC';

COMMENT ON DATABASE aria_phase2 IS
    'Aria course Phase 2: relational implementation, seed data and query portfolio (synthetic data only)';
