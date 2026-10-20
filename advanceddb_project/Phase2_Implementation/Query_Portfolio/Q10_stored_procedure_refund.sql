-- Q10  Stored procedure: idempotent refund requests
-- Business question: When a customer clicks "Request refund" twice, their browser retries, or
--   they try to refund more than they paid, how do we make sure money only goes back once and
--   that admins can see every blocked duplicate?
-- Techniques: a SQL function (risk score), a PL/pgSQL PROCEDURE with INOUT parameters,
--   SELECT ... FOR UPDATE to serialize requests for the same order, an inner BEGIN/EXCEPTION
--   block as a backstop for the unique indexes, and an audit insert that survives the rejection.
--
-- Business invariant 3: refunds are idempotent. The database backs this up two ways:
--   refunds.idempotency_key is UNIQUE, and refunds_one_open_per_order allows one open refund.
-- Blocked attempts return normally (they don't raise), so the duplicate_refund_attempts row
-- commits with the caller's transaction instead of being rolled back.

-- Deterministic refund risk score, 0-100 (rules, not ML). Staff/admin only.
CREATE OR REPLACE FUNCTION fn_refund_risk_score(p_order_id bigint, p_amount numeric)
RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT LEAST(100, round(
               5
             + 30 * p_amount / o.total_amount                       -- share of the order refunded
             + 12 * (SELECT count(*)                                -- this customer's past refunds
                       FROM refunds r JOIN orders o2 ON o2.order_id = r.order_id
                      WHERE o.account_id IS NOT NULL AND o2.account_id = o.account_id)
             + CASE WHEN o.account_id IS NULL THEN 10 ELSE 0 END    -- guest order
             + CASE WHEN o.total_amount > 800 THEN 10 ELSE 0 END,   -- high-value order
           2))
    FROM orders o
    WHERE o.order_id = p_order_id
$$;

CREATE OR REPLACE PROCEDURE request_refund(
    p_order_id        bigint,
    p_amount          numeric,
    p_reason          text,
    p_idempotency_key uuid,
    p_requested_by    bigint,                -- customer account, or NULL for a guest using the order link
    INOUT o_refund_id bigint DEFAULT NULL,
    INOUT o_outcome   text   DEFAULT NULL)
LANGUAGE plpgsql AS $$
DECLARE
    v_order     orders%ROWTYPE;
    v_existing  refunds%ROWTYPE;
    v_committed numeric;
BEGIN
    -- lock the order so two requests for it run one after the other
    SELECT * INTO v_order FROM orders WHERE order_id = p_order_id FOR UPDATE;
    -- another customer's order looks exactly like a missing one (no existence leak)
    IF NOT FOUND OR v_order.account_id IS DISTINCT FROM p_requested_by THEN
        RAISE EXCEPTION 'Order % not found', p_order_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_order.status NOT IN ('CONFIRMED', 'SHIPPED', 'DELIVERED') THEN
        RAISE EXCEPTION 'Order % is % and cannot be refunded', p_order_id, v_order.status;
    END IF;

    -- 1. same idempotency key = a retry of a request we already have: return it, flag it
    SELECT * INTO v_existing FROM refunds WHERE idempotency_key = p_idempotency_key;
    IF FOUND THEN
        INSERT INTO duplicate_refund_attempts (order_id, idempotency_key, existing_refund_id, attempt_reason)
        VALUES (p_order_id, p_idempotency_key, v_existing.refund_id, 'SAME_KEY');
        o_refund_id := v_existing.refund_id;
        o_outcome   := 'DUPLICATE: returned existing refund';
        RETURN;
    END IF;

    -- 2. a different request while one is still open
    SELECT * INTO v_existing FROM refunds
     WHERE order_id = p_order_id AND status IN ('REQUESTED', 'APPROVED');
    IF FOUND THEN
        INSERT INTO duplicate_refund_attempts (order_id, idempotency_key, existing_refund_id, attempt_reason)
        VALUES (p_order_id, p_idempotency_key, v_existing.refund_id, 'OPEN_REFUND_EXISTS');
        o_refund_id := v_existing.refund_id;
        o_outcome   := 'REJECTED: an open refund already exists';
        RETURN;
    END IF;

    -- 3. never refund more than the customer paid
    SELECT COALESCE(sum(amount), 0) INTO v_committed
      FROM refunds WHERE order_id = p_order_id AND status IN ('APPROVED', 'COMPLETED');
    IF v_committed + p_amount > v_order.total_amount THEN
        INSERT INTO duplicate_refund_attempts (order_id, idempotency_key, existing_refund_id, attempt_reason)
        VALUES (p_order_id, p_idempotency_key, NULL, 'EXCEEDS_ORDER_TOTAL');
        o_refund_id := NULL;
        o_outcome   := format('REJECTED: %s already refunded of %s', v_committed, v_order.total_amount);
        RETURN;
    END IF;

    BEGIN
        INSERT INTO refunds (order_id, payment_id, amount, reason, idempotency_key, requested_by, risk_score)
        VALUES (p_order_id, v_order.confirmed_payment_id, p_amount, p_reason, p_idempotency_key,
                p_requested_by, fn_refund_risk_score(p_order_id, p_amount))
        RETURNING refund_id INTO o_refund_id;
        o_outcome := 'CREATED';
    EXCEPTION WHEN unique_violation THEN
        -- backstop: the unique indexes caught a duplicate the checks above missed
        INSERT INTO duplicate_refund_attempts (order_id, idempotency_key, existing_refund_id, attempt_reason)
        VALUES (p_order_id, p_idempotency_key, NULL, 'SAME_KEY');
        o_refund_id := NULL;
        o_outcome   := 'REJECTED: duplicate caught by unique index';
    END;
END $$;

-- ---------------------------------------------------------------------------
-- Demo (rolled back at the end so the seed data stays unchanged).
-- Target: the most recent delivered order of a registered customer that has no refunds yet.
-- ---------------------------------------------------------------------------
BEGIN;

CREATE TEMP TABLE demo_target ON COMMIT DROP AS
SELECT o.order_id, o.account_id, o.total_amount
FROM orders o
WHERE o.status = 'DELIVERED' AND o.account_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM refunds r WHERE r.order_id = o.order_id)
ORDER BY o.order_id DESC
LIMIT 1;
SELECT * FROM demo_target;

-- CALL arguments can't contain subqueries, so the demo calls the procedure from a DO block
-- and prints each outcome as a NOTICE. From an application: CALL request_refund(123, 20.00, ...);
DO $$
DECLARE
    t          demo_target%ROWTYPE;
    refund_id  bigint;
    outcome    text;
BEGIN
    SELECT * INTO t FROM demo_target;

    -- 1st click: creates the refund
    CALL request_refund(t.order_id, 20.00, 'Wrong size',
                        'aaaaaaaa-0000-4000-8000-000000000001', t.account_id, refund_id, outcome);
    RAISE NOTICE '1st click            -> refund %, %', refund_id, outcome;

    -- browser retry with the SAME key: returns the same refund, flags SAME_KEY
    CALL request_refund(t.order_id, 20.00, 'Wrong size',
                        'aaaaaaaa-0000-4000-8000-000000000001', t.account_id, refund_id, outcome);
    RAISE NOTICE 'retry, same key      -> refund %, %', refund_id, outcome;

    -- a second, different request while the first is open: rejected, flags OPEN_REFUND_EXISTS
    CALL request_refund(t.order_id, 35.00, 'Changed my mind',
                        'aaaaaaaa-0000-4000-8000-000000000002', t.account_id, refund_id, outcome);
    RAISE NOTICE 'new request, 1 open  -> refund %, %', refund_id, outcome;
END $$;

-- one refund row exists for the order...
SELECT refund_id, order_id, amount, status, risk_score
FROM refunds WHERE order_id = (SELECT order_id FROM demo_target);
-- ...and both blocked attempts are waiting for admin review
SELECT attempt_id, order_id, existing_refund_id, attempt_reason, reviewed_at
FROM duplicate_refund_attempts WHERE order_id = (SELECT order_id FROM demo_target)
ORDER BY attempt_id;

-- staff completes the first refund, then the customer asks for more than is left
UPDATE refunds SET status = 'COMPLETED', resolved_at = now(),
       resolved_by = (SELECT min(account_id) FROM accounts WHERE account_type = 'staff')
 WHERE order_id = (SELECT order_id FROM demo_target);
DO $$
DECLARE
    t          demo_target%ROWTYPE;
    refund_id  bigint;
    outcome    text;
BEGIN
    SELECT * INTO t FROM demo_target;
    CALL request_refund(t.order_id, t.total_amount, 'Not as described',
                        'aaaaaaaa-0000-4000-8000-000000000003', t.account_id, refund_id, outcome);
    RAISE NOTICE 'refund the full total -> refund %, %', refund_id, outcome;
END $$;

-- all three blocked attempts are now in the admin review queue
SELECT attempt_id, existing_refund_id, attempt_reason
FROM duplicate_refund_attempts WHERE order_id = (SELECT order_id FROM demo_target)
ORDER BY attempt_id;

ROLLBACK;
