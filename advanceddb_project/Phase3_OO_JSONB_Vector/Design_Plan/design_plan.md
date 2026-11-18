# Aria Phase 3 Design Plan: Product hierarchy, JSONB specs and semantic review search

**Domain extended:** the product catalogue of Aria (diving and watersports gear) and its customer reviews. Phase 2 left product attributes as a flat `products` table and kept reviews in a 60-document Firestore prototype. Phase 3 moves both into PostgreSQL 18 (`aria_phase2` database) and gives each kind of data the structure that fits it. All data is synthetic.

## 1. Workflow and tools

| Stage | Tool | Output |
|---|---|---|
| Generate | `generate_dataset.py` (Python stdlib, seed 202603, reuses the Phase 2 simulation) | product specs SQL, 2,440 raw reviews, hidden topic labels |
| Clean / audit | `clean_reviews.py` + the model tokenizer | 2,390 clean reviews, `data_quality_report.md` |
| Embed | `embed_reviews.py`: sentence-transformers on the local CPU | `review_embeddings.csv` (384-d vectors) |
| Load and index | `psql \copy`, PostgreSQL 18.6 + pgvector 0.8.7 | tables, GIN and HNSW indexes |
| Query and evaluate | SQL files A1-D1, `evaluate.py` (psycopg) | captured outputs, precision@5 |
| Orchestrate | `run_pipeline.py --all` (bonus) | the whole chain in one command, reproducible byte-for-byte |

## 2. Class hierarchy and mapping strategy

`Product` is abstract and has four disjoint, complete subclasses:
- `WearableGear` (masks, suits, gloves, fins, boots)
- `LifeSupportEquipment` (regulators, BCDs, gauges, hoses)
- `DiveElectronics` (computers, lights)
- `SafetyAccessory` (SMBs, reels, cutters, whistles, compasses)

`Category` aggregates products. `Product` composes `ProductReview`, which composes its `ReviewEmbedding`. `Account` writes reviews, and an `Order` optionally verifies one.

**Chosen: class table inheritance.** Shared attributes stay once in the existing `products` table, and each subclass table holds only its own columns. The subclass table's primary key is a foreign key to `products`. A discriminator, `products.product_kind`, plus a composite FK `(product_id, product_kind)` makes the subclasses disjoint at the database level. A deferred constraint trigger makes the hierarchy complete: no product exists without its subclass row.

- **Single table rejected.** It would add about 11 subclass columns to `products`, NULL for three quarters of the rows. Rules like "electronics must have a warranty" could then only be written as CHECKs that depend on `product_kind`, which grow with every subclass.
- **Concrete table rejected.** Four separate product tables would break every existing foreign key from `order_items`, `inventory_movements` and `refunds` to `products`, and SKU uniqueness would have to be enforced across tables. Phase 2's order history must not change.
- **Native `INHERITS` rejected.** PostgreSQL table inheritance does not carry primary keys, unique constraints or foreign keys to child tables, which is the same problem as concrete tables.

Polymorphism and encapsulation are provided through `v_product_catalogue` and the functions `fn_describe_product`, `fn_care_interval_months`, `fn_care_due_date` and `fn_add_product`. Each subclass computes its own care interval and description. A role, `aria_catalogue_app`, may use only these, not the tables.

## 3. Relational vs JSONB vs embedded

| Data | Stored as | Why |
|---|---|---|
| sku, price, stock, kind, category; subclass fields such as `warranty_months` and `service_interval_months` | **relational columns** | Every row has them; they are filtered, joined, aggregated and constrained (CHECK, FK, NOT NULL). |
| `products.specs`: `weight_g`, `colours[]`, `sizes[]` (array of objects), `features{}` (keys differ per product type: `nitrox`, `lumens`, `lift_kg`), `certifications[]`, `compatible_with[]` | **JSONB** | The keys vary per product. As columns they would be dozens of mostly-NULL fields, and a new product type would need a migration. |
| `product_reviews.details`: sub-ratings (`fit` only for wearables), optional `dive_context{site, water_temp_c, depth_m}`, `photos[]` | **JSONB** | Optional and nested; 61% of reviews have a dive context. |
| review `title + body` | **embedded** (and `tsvector` for keywords) | People search reviews by meaning ("mask steams up" = fogging). |

`products_specs_valid` checks the JSON: it must be an object, `weight_g` must be a positive number, the arrays must be arrays, and every size must have `size` and `available`. GIN (`jsonb_path_ops`) indexes `specs` and `details`.

## 4. Embeddings, distance and index

- **Model:** `sentence-transformers/all-MiniLM-L6-v2`, Hugging Face revision `1110a24` (pinned), **384 dimensions**, maximum input of 256 word pieces. It is free and open (Apache-2.0), small enough to embed 2,390 reviews on a laptop CPU in under 30 s, and trained for semantic similarity of sentences, which matches short reviews.
- **Long text:** 39 reviews exceed 254 tokens. Instead of cutting them off, they are embedded in overlapping windows and the window vectors are averaged.
- **Distance: cosine (`<=>`).** The model is trained with a cosine objective and its vectors are normalised.
- **Index: HNSW with `vector_cosine_ops`** (m = 16, ef_construction = 64). HNSW gives better recall per millisecond than IVFFlat, needs no training step, and stays correct as rows are added.

## 5. Where the authoritative copy lives

| Data | Authoritative | Derived copies (rebuildable) |
|---|---|---|
| products, subclass attributes, specs | PostgreSQL `products` + subclass tables | `v_product_catalogue` (view) |
| review text, rating, details | PostgreSQL `product_reviews` | `body_tsv` (generated column); `review_embeddings` (rebuilt by `embed_reviews.py`, tagged with the model version) |
| orders, accounts | PostgreSQL (Phase 2 tables) | none |
| relevance labels for evaluation | `Embeddings/eval/ground_truth.csv` (never in the database) | none |

The Phase 2 Firestore review prototype is superseded: reviews now live next to the products and orders they reference, so foreign keys and the verified-purchase trigger can protect them.
