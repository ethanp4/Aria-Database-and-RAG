-- Q14  Payables aging and spend by payee
-- Business question: How much do we owe each supplier and carrier, how much of it is overdue
--   (and by how long), and how much have we paid each payee over the last 12 months?
-- Techniques: exclusive-arc join (each bill points at a supplier OR a carrier; the
--   ap_one_payee CHECK guarantees exactly one), COALESCE across the two subtypes, aging
--   buckets with FILTER, ROLLUP for a grand total.
-- The dataset is fixed as of 2026-10-01; in production replace the literal with current_date.

SELECT * FROM (
SELECT COALESCE(CASE WHEN ap.supplier_id IS NOT NULL THEN 'Supplier' ELSE 'Carrier' END, 'TOTAL') AS payee_type,
       COALESCE(s.name, c.name, '')                                              AS payee,
       count(*) FILTER (WHERE ap.status <> 'PAID')                               AS unpaid_bills,
       COALESCE(sum(ap.amount_due) FILTER (WHERE ap.status <> 'PAID'
                    AND ap.due_date >= DATE '2026-10-01'), 0)                    AS not_yet_due,
       COALESCE(sum(ap.amount_due) FILTER (WHERE ap.status <> 'PAID'
                    AND ap.due_date <  DATE '2026-10-01'
                    AND ap.due_date >= DATE '2026-10-01' - 30), 0)               AS overdue_1_30,
       COALESCE(sum(ap.amount_due) FILTER (WHERE ap.status <> 'PAID'
                    AND ap.due_date <  DATE '2026-10-01' - 30), 0)               AS overdue_31_plus,
       COALESCE(sum(ap.amount_due) FILTER (WHERE ap.status = 'PAID'
                    AND ap.paid_at >= TIMESTAMPTZ '2025-10-01 00:00+00'), 0)     AS paid_last_12_months
FROM accounts_payable ap
LEFT JOIN suppliers s ON s.supplier_id = ap.supplier_id
LEFT JOIN carriers  c ON c.carrier_id  = ap.carrier_id
GROUP BY ROLLUP ((CASE WHEN ap.supplier_id IS NOT NULL THEN 'Supplier' ELSE 'Carrier' END,
                  COALESCE(s.name, c.name, '')))
) aging
ORDER BY payee_type = 'TOTAL', paid_last_12_months DESC;
