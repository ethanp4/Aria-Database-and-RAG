# Product catalogue lookup guide (customer chatbot)

Audience: customer-facing assistant. Source schema: `aria_phase2`, PostgreSQL, `products` and `categories` from the Phase 2 SQL scripts.

## Approved information

Use the catalogue to answer questions about product names, descriptions, SKU, category, listed price/currency, and whether an item is active and currently in stock. `products.stock_quantity` is an inventory snapshot, not a reservation or guarantee; availability can change before checkout. Do not promise fit, certification, safety, or compatibility unless the product description explicitly states it. Do not expose internal product IDs, reorder levels, or timestamps.

## Tables and fields

- `products(product_id, sku, name, description, category_id, unit_price, currency, stock_quantity, reorder_level, is_active, created_at, updated_at)`
- `categories(category_id, name, description)`
- Join with `products.category_id = categories.category_id`. A product may have no category.
- Only show `is_active = TRUE`. Treat `stock_quantity > 0` as currently listed in stock; zero means currently unavailable.

## Query patterns

Search by product name or description; bind user text as a parameter (shown as `:term` below). Keep results bounded and return only customer-safe columns.

```sql
SELECT p.sku, p.name, p.description, c.name AS category,
       p.unit_price, p.currency,
       CASE WHEN p.stock_quantity > 0 THEN 'in stock' ELSE 'currently unavailable' END AS availability
FROM products AS p
LEFT JOIN categories AS c ON c.category_id = p.category_id
WHERE p.is_active = TRUE
  AND (p.name ILIKE '%' || :term || '%' OR p.description ILIKE '%' || :term || '%')
ORDER BY p.name
LIMIT 10;
```

For a SKU lookup, filter `p.sku = :sku` and retain `p.is_active = TRUE`. For category browsing, filter `c.name ILIKE '%' || :category || '%'`. Never interpolate raw user text into SQL.

## Answering rules

Use the current database result for price and stock, and the policy documents for store rules. State currency with every price. If no suitable product is found, ask a clarifying question or say no match was found; do not invent product specifications. Do not query or disclose customer, account, order, payment, supplier, refund, fraud-risk, or financial tables.

## Read-only query constraints

Generate one `SELECT` statement only. No writes, DDL, multiple statements, system catalog access, or unbounded result sets. The database role must independently enforce read-only access and grant access only to the product fields needed by this customer assistant.
