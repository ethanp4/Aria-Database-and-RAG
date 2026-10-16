# Follow-ups (after Phase 1)

## Payments (TODO: add payment API and test it)
Payments are TEMPORARY: `FakeGateway` with test cards. No Stripe or other provider API is wired yet.
- Replace `FakeGateway` with a Stripe gateway (PaymentIntents with manual capture, so authorize/capture/void map 1:1); keep the `PaymentGateway` protocol.
- Card entry via Stripe Elements so card data never touches our server; remove the test-card picker (`payments/test_cards.py`) from checkout.
- Pass the checkout token as the Stripe idempotency key; add webhook handling and reconciliation for capture timeouts (a timeout can mean "captured but we didn't hear back").
- Sweep for orders stuck in `PENDING_PAYMENT` (process crash between steps).
- Test plan: Stripe test mode + test cards for success, decline, 3-D Secure, timeout; rerun the Phase 1 concurrency tests against the new gateway.
- Refuse to start with `FakeGateway` when `DEBUG=False`.
- An authorize timeout can leave an authorization at the gateway with no ref to void; a DB commit failure right after a successful capture marks the order PAYMENT_FAILED although money may have been captured (`capture_entered` is logged). Both need reconciliation via Stripe webhooks/idempotency.
- A price change in the milliseconds between the checkout view's total check and `place_order`'s re-pricing is charged at the new price; pass an expected total into `place_order` when wiring Stripe.
- Payment rows are marked VOIDED even if the void call failed; record the real void outcome.

## Tax
- Replace the `orders/pricing.py` tax tables with Stripe Tax (local US rates, product taxability, shipping taxability per state); keep `quote()` as the seam.

## Guest checkout / email
- Real email provider (console backend today).
- Rate-limit `orders:lookup`; consider `Cache-Control: no-store` on the guest order page.
- Decide retention for guest contact/address data (Phase 5).
- Back + resubmit of a stale checkout page after a decline lands on the failed order instead of a fresh checkout.

## Scale
- Staff order list runs COUNT(*) on every page load; switch to keyset/next-prev paging near the 1M orders/month target.
- Payments/order_items have explicit indexes duplicating Django's FK indexes; drop one in the Phase 5 index review.
