# Aria: Phase 2 implementation

Aria is an online store for diving and watersports gear. This phase turns the Phase 1 model into a working data layer:

| Store | Folder | What lives there |
|---|---|---|
| **PostgreSQL 18** (`aria_phase2`) | `SQL_Scripts/`, `Query_Portfolio/` | Everything transactional and authoritative: accounts, products, stock, orders, payments, refunds, payables/receivables, policy metadata (16 tables) |
| **PostgreSQL JSONB** (`order_document`) | `OO_JSONB_Mapping/` | A read model: each Order as one JSON document, mapped to Python dataclasses |
| **Cloud Firestore** (`reviews`) | `NoSQL_Prototype/` | Customer product reviews with nested ratings, tags, photos and a replies subcollection |

**All data is synthetic.**
- Names come from fixed lists.
- Emails use the reserved `example.test` domain and phones use the fictional `555-01xx` range.
- Payment tokens are `tok_fake_…`, and only the last 4 digits are stored.
- Seed accounts have unusable password hashes, so nobody can log in as them.

```
Phase2_Implementation/
  SQL_Scripts/          schema, indexes, deterministic seed, integrity checks, one-command rebuild
  Query_Portfolio/      14 commented queries (+ expected_output/ with captured results)
  NoSQL_Prototype/      Firestore seed, CRUD demo, queries, indexes, security rules
  OO_JSONB_Mapping/     Order dataclasses, UML diagram, order_document JSONB table + queries
  Implementation_Report/  report and demo script
  Demo_Video_Link.txt
```

---

## 1. Prerequisites

| Tool | Version used | Needed for |
|---|---|---|
| PostgreSQL server + `psql` | 18.6 (Windows installer) | everything in SQL_Scripts, Query_Portfolio, OO_JSONB_Mapping |
| pgAdmin 4 | ships with the PostgreSQL installer | browsing tables and running queries for screenshots (optional) |
| Python | 3.10+ (3.11+ recommended for Firestore) | `generate_seed.py`, `order_model.py`, the Firestore scripts |
| Node.js + Java | Node 18+, Java 21 (or 11, see 3b) | the local Firestore emulator only |
| A Firebase project | Spark (free) plan is enough | running against real Cloud Firestore |

There are **no Python dependencies** for the PostgreSQL parts; they use the standard library only. The Firestore part needs one package, `firebase-admin` (see `NoSQL_Prototype/requirements.txt`). It is the official Admin SDK and brings in `google-cloud-firestore`.

## 2. PostgreSQL: build and seed the database

**Supplying the database password**
- Never put the password in a file inside this repo.
- Option 1: set it for the current terminal only, as an environment variable.
- Option 2: use a pgpass file. On Windows it lives at `%APPDATA%\postgresql\pgpass.conf`, on macOS/Linux at `~/.pgpass`, with one line:
  `127.0.0.1:5432:*:postgres:<password>`

**PowerShell**
```powershell
$env:PGHOST = '127.0.0.1'; $env:PGPORT = '5432'; $env:PGUSER = 'postgres'
$env:PGPASSWORD = Read-Host 'Postgres password'      # typed in, not saved anywhere
cd advanceddb_project\Phase2_Implementation\SQL_Scripts
.\run_all.ps1
```

**Git Bash / macOS / Linux**
```bash
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres
read -s -p "Postgres password: " PGPASSWORD; export PGPASSWORD
# Windows only, if psql is not on PATH:
export PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"
cd advanceddb_project/Phase2_Implementation/SQL_Scripts
./run_all.sh
```

`run_all` takes about 5 seconds and runs these steps in order:

| Step | File | What it does |
|---|---|---|
| 1 | `00_create_database.sql` | Drops and recreates `aria_phase2` and sets its time zone to UTC. **It never touches the app's `aria` database.** |
| 2 | `01_tables.sql` | Creates the 16 tables with primary/foreign keys and CHECK/UNIQUE constraints. |
| 3 | `02_indexes.sql` | Adds foreign-key, query and business-rule indexes, each commented with the query it serves. |
| 4 | `03_seed.sql` | Loads the synthetic data in one transaction. |
| 5 | `04_verify_seed.sql` | Prints row counts and runs 10 cross-table integrity checks. It stops with an error if any check fails. |
| 6 | `Query_Portfolio/run_portfolio.*` | Runs Q01-Q14, installs the views, triggers and procedure, and saves each result to `Query_Portfolio/expected_output/`. |

**Using pgAdmin instead:**
1. Open a Query Tool on the `postgres` database and run `00_create_database.sql`.
2. Open a Query Tool on `aria_phase2` and run `01`, `02`, `03` and `04` in order.
3. Run the `Query_Portfolio` files in numeric order.

Then build the JSONB read model:
```bash
cd ../OO_JSONB_Mapping
psql -d aria_phase2 -f 01_order_document.sql
psql -d aria_phase2 -f 02_jsonb_queries.sql
python order_model.py          # JSONB -> Order objects -> JSON round trip
```

**Regenerating the seed (optional):**
- `python SQL_Scripts/generate_seed.py` rewrites `03_seed.sql`.
- `--check` confirms the committed file is up to date.
- The generator is deterministic (seed `2026`, clock fixed at 2026-10-01), so the output is identical byte for byte every time.

## 3. Firestore: seed the `reviews` collection

```bash
cd advanceddb_project/Phase2_Implementation/NoSQL_Prototype
python -m venv .venv && . .venv/Scripts/activate      # macOS/Linux: . .venv/bin/activate
pip install -r requirements.txt
```

### 3a. Against your Firebase project

**One-time setup (do it once per team)**
1. Go to <https://console.firebase.google.com> and choose **Add project**, e.g. `aria-phase2`. Google Analytics isn't needed.
2. Go to **Build > Firestore Database > Create database**, choose **Production mode**, and pick a region. We use `northamerica-northeast1` (Montréal).
3. Go to **Project settings > Service accounts > Generate new private key**.
   - Save the JSON file **outside the repository**, e.g. `C:\Users\<you>\keys\aria-firebase.json`.
   - If it must sit in the folder, name it `serviceAccountKey.json`. `.gitignore` already blocks `serviceAccount*.json` and `*firebase-adminsdk*.json`.
   - Each teammate generates their own key. **Never commit, email or paste the key.**
4. Deploy the composite indexes and the security rules. Query F1 needs the indexes; until they are deployed, Firestore returns an error that includes a link to create them.
   ```bash
   npx firebase-tools login
   npx firebase-tools deploy --only firestore:indexes,firestore:rules --project <your-project-id>
   ```

**Every session**
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\Users\<you>\keys\aria-firebase.json'   # PowerShell
```
```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/keys/aria-firebase.json                  # bash
python seed_reviews.py --reset   # 60 reviews + their replies
python crud_demo.py              # create / read / update / delete one review
python queries.py                # F1-F4
```

### 3b. Against the local emulator (no cloud account, no key)
```bash
# Java 21 + current CLI:
npx firebase-tools emulators:start --only firestore --project demo-aria
# in a second terminal:
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080          # PowerShell: $env:FIRESTORE_EMULATOR_HOST = '127.0.0.1:8080'
python seed_reviews.py --reset && python crud_demo.py && python queries.py
```
- Browse the data in the Emulator UI at <http://127.0.0.1:4000/firestore>.
- **Only have Java 11?** Use `firebase-tools@13.29.1`, installed with `npm install` in a scratch folder.
  - Its dependency `universal-analytics` now pulls in an ESM-only `uuid`, so first add `"overrides": {"universal-analytics": {"uuid": "8.3.2"}}` to that folder's `package.json`.
- The emulator doesn't enforce composite indexes, so queries also run there without step 4.
- The captured output in `NoSQL_Prototype/expected_output/` came from this emulator setup.

## 4. Datasets

### PostgreSQL: `aria_phase2`
**How the data is generated:** `SQL_Scripts/generate_seed.py`, standard library only, `random.Random(2026)`.
- It simulates one year of trading (2025-10-01 → 2026-09-30) in time order, so the rows are consistent with each other, not just random.
- Stock never goes negative, and every stock change has a movement row.
- Totals add up, and confirmed orders always have a captured payment.
- Refunds never exceed what was paid.
- Order volume follows a seasonal curve that peaks in summer.

| Table | Rows | Contents |
|---|---:|---|
| accounts | 210 | 200 customers, 8 staff, 2 admins |
| profiles | 210 | name, `@example.test` email, `555-01xx` phone |
| addresses | 350 | CA/US shipping and billing addresses (coastal and dive towns weighted higher) |
| categories | 6 | product categories |
| products | 200 | same catalogue as the app's `sample_data` command (30 named + 17 families × 10 variants) |
| carriers | 4 | Canada Post, Purolator, UPS, FedEx |
| suppliers | 25 | synthetic vendors (`*.example.test`) |
| orders | 480 | 10% guest checkout, with every outcome: delivered, shipped, refunded, payment failed, cancelled, out of stock |
| order_items | 979 | 1-4 lines per order |
| payments | 480 | credit, debit, PayPal, gift card; fake token + last 4 only |
| inventory_movements | 1,337 | opening stock, restocks, sales, returns, month-end adjustments |
| refunds | 137 | completed, denied and open requests, each with a rule-based risk score |
| duplicate_refund_attempts | 17 | blocked duplicate refunds awaiting admin review |
| accounts_receivable | 434 | card processor settlements (one per captured payment) |
| accounts_payable | 125 | supplier and carrier bills (exactly one payee each) |
| policy_documents | 22 | metadata for the 20 chatbot policy docs, plus 2 superseded versions |

`order_document` (JSONB) holds 480 documents, one per order, built from the tables above by `fn_order_document()`.

**Reference and lookup tables** (categories, carriers, suppliers, policy documents) are small on purpose. They describe the business, so padding them to 100+ rows would make the data less realistic. Every transactional entity has 100+ rows.

### Firestore: `reviews`
**How the data is generated:** `NoSQL_Prototype/reviews_data.py` reuses the PostgreSQL simulation.
- Each reviewer is a real seed customer, and every SKU exists in `products`.
- `verified_purchase` and `order_id` point at a delivered order in `aria_phase2`.

| Collection | Documents | Shape |
|---|---:|---|
| `reviews` | 60 | `product` (map), `author` (map), `rating`, `ratings` (map; `fit` only for wearable gear, `durability` only sometimes), `tags` (array), `photos` (array of maps), `dive_context` (map, on 26 of 60 reviews), `helpful_votes`, `status`, `created_at` |
| `reviews/{id}/replies` | 60 | `author_role` (staff/customer), `author`, `body`, `created_at` |

54 of the 60 reviews are verified purchases, and 19 of the replies are from staff. `NoSQL_Prototype/sample_documents.json` shows two complete documents.

## 5. Which store holds what, and which copy is authoritative

| Data | Authoritative store | Copies |
|---|---|---|
| customers, products, stock, orders, payments, refunds, payables/receivables | **PostgreSQL tables** | `order_document` JSONB (read model, rebuilt from the tables); review documents keep `product.name`/`sku` and `author.username` as display copies |
| review text, ratings, tags, photos, replies, helpful votes | **Firestore** | none |
| `verified_purchase` on a review | computed from **PostgreSQL** orders when the review is written | stored in Firestore |

If a copy disagrees with its source, the source wins. `02_jsonb_queries.sql` J5 checks the JSONB copy against the relational tables and must return 0 rows.

## 6. Credentials: what is and isn't in the repo

| Secret | How you provide it | Never |
|---|---|---|
| PostgreSQL password | `PGPASSWORD` in the current terminal, or a pgpass file in your home folder | in any `.sql`, script or committed `.env` |
| Firebase service-account key | `GOOGLE_APPLICATION_CREDENTIALS` = path to the JSON key, saved outside the repo | committed, emailed or pasted; `.gitignore` blocks `serviceAccount*.json` and `*firebase-adminsdk*.json` |
| Firebase project id | read from the key file (or `FIREBASE_PROJECT_ID` for the emulator) | — |

The Django app's own settings file `aria_project/aria/.env` is gitignored too. `firestore.rules` denies all direct client access: only the server, using the Admin SDK and a service account, can read or write.

## 7. Notes
- **App database is untouched.** Django migrations own the app's `aria` database, and nothing in this folder changes it. `SQL_Scripts/schema_reconciliation.md` lists how `aria_phase2` differs from the app and from Phase 1 `schema.sql`, including the suppliers fix.
- **Demo files don't change the data.** Q09-Q11 and J6 demonstrate writes inside transactions that end in `ROLLBACK`, so rerunning them never changes the seed data. The production version of each would `COMMIT`.
- **Expected errors.** Errors marked `EXPECTED ERROR` in Q09 and Q11 are deliberate: an oversell blocked by the trigger, a double-submitted checkout, and an order confirmed without a payment.
- **Timings vary by machine.** Timings in `Q13` depend on the machine; the plan shapes (Seq Scan + Sort → Index Scan) are the point.
