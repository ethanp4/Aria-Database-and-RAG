# Demo video script (target 5:00, allowed 4-6 min)

**Before you record**
- Rebuild the database so the numbers match the report: run `SQL_Scripts/run_all.ps1`, then `OO_JSONB_Mapping/01_order_document.sql`.
- Open pgAdmin 4 connected to `aria_phase2`, with one Query Tool tab per file you will run.
- Open a terminal in `NoSQL_Prototype/` with `GOOGLE_APPLICATION_CREDENTIALS` set and the reviews already seeded (`python seed_reviews.py --reset`).
- Open the Firebase console on Firestore > Data > `reviews`.
- Set the screen to 1080p and increase the pgAdmin font size so text stays readable.

Each segment below is one speaker.

| Time | Section (required item) | Speaker |
|---|---|---|
| 0:00-0:20 | Intro | [name] |
| 0:20-1:10 | Schema and sample data tour | [name] |
| 1:10-2:30 | Key queries (KPIs, nested query, view) | [name] |
| 2:30-3:05 | Trigger + stored procedure in action (optional item) | [name] |
| 3:05-4:10 | Firestore: CRUD + query | [name] |
| 4:10-5:00 | Object model + JSONB query | [name] |
| 5:00-5:10 | Wrap-up | [name] |

---

## 0:00-0:20 Intro
**Show:** the README in the repo, top section.

**Say:** "This is Aria, an online store for diving gear. In Phase 2 we implemented our model in PostgreSQL, added Cloud Firestore for product reviews, and mapped the Order entity to Python classes and a JSONB document. All of the data is synthetic."

## 0:20-1:10 Schema and sample data tour
**Show:** in pgAdmin, expand aria_phase2 > Schemas > public > Tables. Open `orders` > Constraints.

**Say:** "There are 16 tables. Every relationship is a foreign key, and the business rules are constraints. This one, `orders_confirmed_requires_payment`, means the database itself refuses to mark an order Confirmed without a payment. Accounts payable has an exclusive-arc check, so every bill belongs to exactly one supplier or one carrier. That fixes the suppliers gap from Phase 1."

**Run:** the first query in `SQL_Scripts/04_verify_seed.sql` (row counts), then the integrity checks.

**Say:** "Our seed generator simulates a year of trading with a fixed random seed: 200 customers, 480 orders, about a thousand order lines, 1,300 stock movements and 137 refunds. These ten cross-table checks all return zero. For example, stock always equals the sum of its movement history."

## 1:10-2:30 Key queries
**Run Q01** (monthly revenue).

**Say:** "Monthly revenue net of refunds, with month-over-month growth using the LAG window function. July is our peak, right before summer dive trips."

**Run Q06** (carrier performance).

**Say:** "Carrier performance joins orders to the bills carriers send us. UPS delivers on time about 97% of the time. Canada Post is cheapest per parcel but only 54% on time. That's a real decision for the business."

**Run Q03** (lapsed customers), scroll briefly.

**Say:** "This one uses nested queries, IN and NOT EXISTS, to find customers who bought in our first quarter but haven't ordered in 120 days. It's a win-back list."

**Run Q08**, the second SELECT (staff refund queue).

**Say:** "Views give each audience only the columns it's allowed to see. The customer view has no payment token or risk score; this staff queue view adds the risk score."

## 2:30-3:05 Trigger + procedure in action
**Run Q09** from `BEGIN;` to the end.

**Say:** "Confirming an order fires a trigger that locks the products and takes the stock. MASK-001 goes from 14 to 12, with a logged movement. Ordering 500 whistles is rejected by the trigger, and stock is untouched."

**Run Q10's** demo block and point at the NOTICE messages.

**Say:** "The refund procedure is idempotent. The second click returns the same refund, a second request is rejected, and over-refunding is blocked. Every blocked attempt is flagged for admin review."

## 3:05-4:10 Firestore
**Show:** the Firebase console. Open one review document, expand `ratings` (map), `tags` and `photos` (arrays), then click into its `replies` subcollection.

**Say:** "Reviews are document-shaped. A wetsuit review rates fit and a dive computer doesn't, and replies are a subcollection. PostgreSQL stays authoritative for products and orders; Firestore owns the review text. Reviewers and SKUs come from our PostgreSQL seed."

**Run:** `python crud_demo.py`

**Say:** "Create, read, update and delete. The update changes one nested field, appends to an array and increments a counter atomically. Firestore doesn't cascade, so we delete the replies before the review."

**Run:** `python queries.py`

**Say:** "F1 filters by product and rating and orders by date, using a composite index. F3 is a server-side count and average, and F4 is a collection-group query across every replies subcollection."

## 4:10-5:00 Object model + JSONB
**Show:** `OO_JSONB_Mapping/order_uml.png`.

**Say:** "The Order class composes items, addresses, a payment and a shipment, and uses inheritance for card versus wallet payments and shipping versus billing addresses."

**Run** in pgAdmin: `SELECT jsonb_pretty(doc) FROM order_document WHERE order_id = 321;`

**Say:** "The same Order stored as one JSONB document, built from the relational tables."

**Run** J1 from `02_jsonb_queries.sql`.

**Say:** "One containment query matches three nesting levels at once: delivered, to BC, by Canada Post. It's backed by a GIN index. The JSON is a read model, so the tables stay the source of truth."

**Run (optional):** `python order_model.py` and show "Round trip OK".

## 5:00-5:10 Wrap-up
**Say:** "Everything rebuilds with one command, and the README explains how to supply credentials without committing them. Thanks for watching."

**After recording:** upload the video as a private YouTube video and paste the link into `Demo_Video_Link.txt`.
