# Phase 1: Cart, Checkout, Orders, Temporary Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone can browse, fill a cart and check out, as a guest or as a logged-in customer,
with a shipping speed and a *test card*. They get exactly one confirmed order, and only when the
(fake) payment captured, with stock decremented in the same transaction. Guests reach their
order through a private link or a lookup form. Staff can list orders and mark them shipped.

**Architecture:** New `orders` and `payments` apps plus the existing empty `cart` app. Business
rules live in `orders/services.py` (`place_order`, `mark_shipped`) and `orders/pricing.py`
(shipping + tax); views only check permissions, build inputs and render. Orders keep their own
copy of contact details and addresses, so guest orders and address-book edits/deletes never
conflict. Payments go through a `PaymentGateway` protocol whose only implementation for now is
`FakeGateway` (no external API). Invariant 1 is a DB CheckConstraint; invariants 2 and 4 are
enforced in `place_order`.

**Tech Stack:** Django 6.1, PostgreSQL, Bootstrap 5 templates. No new dependencies.

**Spec:** `CLAUDE.md`; master plan `docs/superpowers/plans/2026-10-14-aria-build-structure.md`
(Phase 1). Decisions taken with the user on 2026-10-15 (they override the master plan where they differ):
- **Guest checkout.** The storefront, product pages, cart and checkout are public. A visitor pays as
  a guest (email + full name required, phone not collected) or logs in / registers. The session cart
  survives login (`cycle_key()` keeps session data) and is cleared on logout (`flush()`).
  Logged-in staff and admin get 403 on cart and checkout (they can log out and buy as a guest).
- **Order addresses are copied onto the order** (`ship_*`, `bill_*` columns). Logged-in customers pick
  from their address book (defaults preselected, link to add one); guests type addresses on the checkout
  page. "Billing same as shipping" checkbox for both, checked by default.
- **Guest order access:** a private link `orders/guest/<order_id>/<key>/` where `key` is an HMAC of
  `(order_id, checkout_token)`, shown after checkout and in the email; plus a "Find my order" form
  (order number + email). Phase 2 will let guests request refunds from that link.
- **Confirmation email** sent through Django's mail API (console backend in dev).
- **Temporary payments.** No Stripe/provider API yet. Checkout shows a *test-card picker*; the
  server maps the picked key to a fake token + last4. No card number is ever entered or sent.
  Write a follow-up note to add the real payment API and test it (Task 10).
- **Shipping:** Standard $12.00 (free when subtotal ≥ $150.00), Express $20.00, Priority $35.00.
- **Tax:** destination-based on the shipping address. Canada: combined GST/HST/PST per province
  and territory. US: statewide base sales-tax rate per state + DC (no county/city rates).
  Shipping is taxed in Canada, not in the US. Unknown region → checkout blocked with a clear message.
  Temporary: to be replaced by Stripe Tax (follow-up note, Task 10).

## Global Constraints

- Roles: `'user'` = Customer, `'staff'` = Staff, `'admin'` = Admin. Not logged in on an account page → login
  redirect; wrong role → 403; another customer's object → 404 (filter by `account=current_account(request)`).
  A guest link with a wrong key, or pointing at an account's order → 404.
- Payment storage: `token` + `last4` (+ brand label, method type) only. Never a full card number,
  anywhere: models, forms, logs, emails, fixtures, templates.
- `risk_score` is never rendered on customer or guest pages or in emails.
- An order shows "Confirmed" only when `status == CONFIRMED`, which the DB only allows with a `confirmed_payment`.
- Stock check + decrement + `InventoryMovement(SALE)` + order confirmation in one `transaction.atomic()`
  with `select_for_update()` on products ordered by `pk`.
- One checkout token → at most one order and at most one authorization.
- Every list view paginated; every filter/sort column indexed. Money is `Decimal`, rounded
  `ROUND_HALF_UP` to cents.
- All data synthetic; tests use `example.com` emails. Schema changes via `makemigrations` only.
  Out of scope: multicurrency (ignore `Product.currency`), logistics, international tax beyond CA/US.

**Test command** (repo root, Git Bash; Django 6.1 needs Python ≥ 3.12):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/aria_project:/app" -e DB_HOST=host.docker.internal django python manage.py test
```

Abbreviated below as `TEST [label]`. `makemigrations` runs the same way with `python manage.py makemigrations`.

## Review Focus

1. **Price changed between loading the checkout page and submitting** → no charge; checkout re-renders
   with the new total and a message. Test: `test_price_change_since_checkout_page_blocks_order` (Task 8).
2. **A checkout token is replayed by a different owner** (other customer, or guest ↔ account) → treated as
   not found, no order returned, no gateway call. Test: `test_checkout_token_of_other_owner_is_rejected` (Task 5).
3. **Someone probes guest orders** (right order number with a wrong key, a valid-looking key on an account's order,
   or lookup with a right number but wrong email) → 404 / the same "couldn't find" message as a nonexistent order.
   Tests: `test_guest_link_wrong_key_or_account_order_404`, `test_lookup_wrong_email_same_message_as_missing_order` (Task 7).
4. **Shipping address region not in the tax table** (e.g. old free-text `"Ontaro"`) → checkout blocked
   before any payment call, message says to fix the address. Tests:
   `test_unsupported_tax_region_blocks_checkout_before_payment` (Task 5),
   `test_address_form_rejects_unknown_region_and_normalizes_code` (Task 1).
5. **Product deactivated or deleted after it went into the cart** → cart drops it with a message;
   `place_order` treats an inactive product as out of stock. Tests: `test_cart_drops_inactive_and_deleted_products`
   (Task 4), `test_inactive_product_treated_as_out_of_stock` (Task 5).

---

### Task 1: Regions, shipping and tax pricing

**Files:**
- Create: `aria_project/accounts/regions.py`, `aria_project/orders/__init__.py`, `orders/apps.py`,
  `orders/pricing.py`, `orders/tests/__init__.py`, `orders/tests/test_pricing.py`
- Modify: `aria_project/accounts/forms.py` (`AddressForm.clean`), `aria_project/aria/settings.py`
  (`INSTALLED_APPS += 'orders'`), `aria_project/accounts/tests/test_addresses.py`

**Interfaces (Produces):**
- `accounts.regions.REGIONS: dict[str, dict[str, str]]`: `{'CA': {code: name}, 'US': {code: name}}`;
  13 Canadian provinces/territories, 50 states + `DC`.
- `accounts.regions.normalize_region(country: str, region: str) -> str`: strips/upper-cases; raises
  `django.core.exceptions.ValidationError("Use the 2-letter province or state code, e.g. ON or WA.")` if not in `REGIONS[country]`.
  Used by `AddressForm` and the guest checkout address form (Task 8).
- `orders.pricing.ShippingMethod(code: str, label: str, price: Decimal, free_over: Decimal | None)` (frozen dataclass)
- `orders.pricing.SHIPPING_METHODS: dict[str, ShippingMethod]`, keys `'STANDARD'`, `'EXPRESS'`, `'PRIORITY'`
  (labels `Standard`, `Express`, `Priority`; prices `12.00`, `20.00`, `35.00`; STANDARD `free_over=150.00`).
- `orders.pricing.shipping_cost(method: str, subtotal: Decimal) -> Decimal`: free when `subtotal >= free_over`;
  unknown method → `ValueError`.
- `orders.pricing.TaxRate(label: str, rate: Decimal, taxes_shipping: bool)`;
  `orders.pricing.tax_rate_for(country: str, region: str) -> TaxRate` (region compared upper-cased/stripped);
  raises `orders.pricing.UnsupportedTaxRegion(country, region)`.
- `orders.pricing.Quote(subtotal, shipping_cost, tax_amount, tax_label, total)` (all `Decimal` except label);
  `orders.pricing.quote(subtotal: Decimal, shipping_method: str, country: str, region: str) -> Quote`.

**Rates** (`orders/pricing.py`, module comment: *"TEMPORARY placeholder rates, statewide/provincial
only, as of 2026. Replace with Stripe Tax when the payment API is connected; see docs/follow-ups.md."*):

- Canada (`taxes_shipping=True`): AB 5% GST; BC 12% GST+PST; MB 12% GST+RST; NB 15% HST; NL 15% HST;
  NS 14% HST; NT 5% GST; NU 5% GST; ON 13% HST; PE 15% HST; QC 14.975% GST+QST; SK 11% GST+PST; YT 5% GST.
- US (`taxes_shipping=False`, label `"<ST> sales tax"`): AL 4, AK 0, AZ 5.6, AR 6.5, CA 7.25, CO 2.9,
  CT 6.35, DE 0, DC 6, FL 6, GA 4, HI 4, ID 6, IL 6.25, IN 7, IA 6, KS 6.5, KY 6, LA 5, ME 5.5, MD 6,
  MA 6.25, MI 6, MN 6.875, MS 7, MO 4.225, MT 0, NE 5.5, NV 6.85, NH 0, NJ 6.625, NM 4.875, NY 4,
  NC 4.75, ND 5, OH 5.75, OK 4.5, OR 0, PA 6, RI 7, SC 6, SD 4.2, TN 7, TX 6.25, UT 6.1, VT 6, VA 5.3,
  WA 6.5, WV 6, WI 5, WY 4.

- [ ] **Step 0:** `git checkout -b feature/checkout` from `master`; commit this plan (`docs: phase 1 checkout plan`).
- [ ] **Step 1: Failing tests** in `orders/tests/test_pricing.py` (`SimpleTestCase`):
  - `test_standard_shipping_free_at_or_over_150`: `shipping_cost('STANDARD', Decimal('149.99')) == Decimal('12.00')`, `('150.00') → Decimal('0.00')`
  - `test_express_and_priority_never_free`: at subtotal `500.00` → `20.00`, `35.00`
  - `test_unknown_shipping_method_raises`
  - `test_ontario_taxes_subtotal_and_shipping`: `quote(Decimal('100.00'), 'EXPRESS', 'CA', 'on')` → shipping `20.00`, tax `15.60`, total `135.60`, label `'HST 13%'`
  - `test_quebec_rounds_half_up_to_cents`: `quote(Decimal('10.00'), 'PRIORITY', 'CA', 'QC')` → tax `6.74` ((10.00 + 35.00) × 0.14975 = 6.73875), total `51.74`
  - `test_us_taxes_subtotal_only`: `quote(Decimal('100.00'), 'PRIORITY', 'US', 'WA')` → tax `6.50`, total `141.50`
  - `test_zero_rate_state`: `('US', 'OR')` → tax `0.00`
  - `test_every_region_has_a_tax_rate`: every code in `REGIONS['CA']` and `REGIONS['US']` resolves; tables have exactly 13 and 51 entries
  - `test_unknown_region_raises_unsupported_tax_region`: `('CA', 'Ontaro')`
- [ ] **Step 2: Failing test** in `test_addresses.py`: `test_address_form_rejects_unknown_region_and_normalizes_code`:
  `AddressForm(address_data(region='Ontaro'))` invalid with error on `region`; `address_data(region=' bc ')` valid and `cleaned_data['region'] == 'BC'`;
  `address_data(country='US', region='BC')` invalid.
- [ ] **Step 3:** `TEST orders accounts` → fail.
- [ ] **Step 4:** Implement `accounts/regions.py`, `orders/pricing.py`, `AddressForm.clean` (calls `normalize_region`, attaches the error to `region`). Update the region field help text.
- [ ] **Step 5:** `TEST` → all pass. Commit `feat(orders): shipping methods and temporary CA/US tax rules`.

### Task 2: Order, OrderItem, Carrier, Payment models

**Files:**
- Create: `aria_project/orders/models.py`, `aria_project/payments/{__init__,apps,models}.py`,
  migrations via `makemigrations orders payments products`, `orders/tests/test_models.py`
- Modify: `aria_project/products/models.py` (`InventoryMovement.reference_order`), `aria/settings.py` (`INSTALLED_APPS += 'payments'`)

**Interfaces (Produces):**
- `orders.models.Carrier(carrier_id, name unique, tracking_url_template)` → table `carriers`
- `orders.models.Order` → table `orders`. Master-plan fields with these changes:
  - `account` FK RESTRICT, **`null=True`** (null = guest order). Remove `shipping_address`/`billing_address` FKs.
  - Contact: `contact_name CharField(200, blank=True)`, `contact_email EmailField(254, null=True, blank=True)`.
  - Address copies: `ship_line1, ship_line2, ship_city, ship_region, ship_postal_code, ship_country` and the same six `bill_*`
    (same max lengths as `accounts.Address`; `*_line2` nullable).
  - `shipping_method CharField(10)`.
  - `confirmed_payment OneToOneField('payments.Payment', PROTECT, null=True, related_name='+')`; `checkout_token UUIDField(unique=True)`.
  - `Order.Status` TextChoices: `PENDING_PAYMENT`, `PAYMENT_FAILED`, `OUT_OF_STOCK`, `CONFIRMED`, `SHIPPED`,
    `DELIVERED`, `CANCELLED`, `REFUNDED` (labels: "Processing", "Payment failed", "Out of stock", "Confirmed", ...).
  - Constraints: `order_status_valid`; `order_shipping_method_valid` (over `SHIPPING_METHODS` keys);
    `order_confirmed_requires_payment` (`~Q(status__in=[CONFIRMED,SHIPPED,DELIVERED,REFUNDED]) | Q(confirmed_payment__isnull=False)`);
    `order_has_owner` (`Q(account__isnull=False) | Q(contact_email__isnull=False)`); `ship_country`/`bill_country` in `('CA','US')`; money columns `>= 0`.
  - Indexes: `(account, -created_at)`, `(status, -created_at)`, `created_at`, `tracking_number`.
  - Method `ship_address_lines() -> list[str]` / `bill_address_lines()` for templates and email.
- `orders.models.OrderItem` → table `order_items`, master-plan fields, CheckConstraint `quantity > 0`, index `product`.
- `payments.models.Payment` → table `payments`. Master-plan fields plus `card_brand CharField(20, blank=True)`.
  `Payment.Status`: `AUTHORIZED`, `CAPTURED`, `DECLINED`, `VOIDED`, `FAILED`, `REFUNDED`.
  `Payment.MethodType`: `CREDIT_CARD`, `DEBIT_CARD`, `PAYPAL`, `GIFT_CARD`.
  Constraint `payment_last4_digits`: `Q(last4__isnull=True) | Q(last4__regex=r'^[0-9]{4}$')`. Index `(order)`, `(status, created_at)`.
- `products.models.InventoryMovement.reference_order = ForeignKey('orders.Order', RESTRICT, null=True, blank=True, related_name='inventory_movements')`.
  No `RELEASE` reason: a failed capture rolls the decrement back inside the atomic block, so nothing is ever released.

- [ ] **Step 1: Failing tests** `orders/tests/test_models.py` (`TestCase`, helper `make_order(account=None, **kw)` filling address copies and `contact_email='guestexample.com'`):
  - `test_db_rejects_confirmed_order_without_payment`: `Order.objects.filter(pk=o.pk).update(status='CONFIRMED')` inside `transaction.atomic()` → `IntegrityError`
  - `test_db_accepts_confirmed_order_with_payment`
  - `test_db_rejects_order_without_account_or_email`
  - `test_payment_rejects_non_digit_last4`: `last4='42a2'` → `IntegrityError`; `last4=None` ok
  - `test_order_item_quantity_must_be_positive`
  - `test_checkout_token_unique`
- [ ] **Step 2:** `TEST orders` → fail. **Step 3:** Implement models; run `makemigrations` (Django splits the
  orders↔payments↔products cycle into separate migrations; check the generated files contain only these changes).
- [ ] **Step 4:** `TEST` → all pass. Commit `feat(orders): order, payment and carrier models with confirmed-requires-payment constraint`.

### Task 3: Fake gateway, test cards, masking

**Files:** Create `payments/gateway.py`, `payments/test_cards.py`, `payments/masking.py`, `payments/tests/{__init__,test_gateway,test_masking}.py`.
Modify `aria/settings.py`: `ARIA_PAYMENT_GATEWAY = env('ARIA_PAYMENT_GATEWAY', default='payments.gateway.FakeGateway')`.

**Interfaces (Produces):**
- `payments.gateway.GatewayResult(ok: bool, ref: str, error: str | None)`; `GatewayTimeout(Exception)`;
  `PaymentGateway` (`typing.Protocol`): `authorize(token, amount) -> GatewayResult`, `capture(ref) -> GatewayResult`, `void(ref) -> GatewayResult`.
- `payments.gateway.FakeGateway`: stateless outcomes by token, refs are `f'fake_{token}_{uuid4().hex}'` so
  `capture`/`void` read the token back from the ref. Tokens: `tok_ok` (all succeed), `tok_decline`
  (authorize → `ok=False, error='card_declined'`), `tok_timeout_authorize` (authorize raises `GatewayTimeout`),
  `tok_timeout_capture` (capture raises `GatewayTimeout`); any other token → authorize `ok=False, error='invalid_token'`.
  `self.calls: list[tuple[str, str]]` (`('authorize', token)`, `('capture', ref)`, `('void', ref)`), appended under a `threading.Lock`.
  Module docstring: *"TEMPORARY. No real money moves. Replace with a Stripe gateway; see docs/follow-ups.md."*
- `payments.gateway.get_gateway() -> PaymentGateway`: `import_string(settings.ARIA_PAYMENT_GATEWAY)()`.
- `payments.test_cards.TestCard(key, label, token, last4, brand, method_type)`; `TEST_CARDS: dict[str, TestCard]`:
  `visa_ok` ("Visa •••• 4242 (approves)", `tok_ok`, `4242`), `mc_ok` ("Mastercard •••• 4444 (approves)", `tok_ok`, `4444`),
  `visa_decline` ("Visa •••• 0002 (declined)", `tok_decline`, `0002`), `visa_timeout` ("Visa •••• 0119 (capture times out)",
  `tok_timeout_capture`, `0119`); all `CREDIT_CARD`.
- `payments.masking.mask_payment(payment) -> str`: `"Visa •••• 4242"`; `"•••• ----"` when `last4` is null; brand omitted when blank.

- [ ] **Step 1: Failing tests:** `test_fake_gateway_outcomes_by_token` (one assertion block per token above),
  `test_fake_gateway_records_calls`, `test_get_gateway_uses_setting` (`override_settings`),
  `test_mask_payment_formats_brand_and_last4`, `test_mask_payment_without_last4`, `test_test_cards_never_hold_more_than_four_digits`
  (every `last4` matches `^\d{4}$`, no attribute value is a digit string longer than 4).
- [ ] **Step 2:** `TEST payments` → fail. **Step 3:** Implement. **Step 4:** `TEST` → pass.
- [ ] **Step 5:** Commit `feat(payments): temporary fake gateway, test cards and payment masking`.

### Task 4: Public session cart, product detail, cart pages

**Files:**
- Create: `cart/cart.py`, `cart/forms.py`, `cart/urls.py`, `cart/templates/cart/detail.html`, `cart/tests/{__init__,test_cart}.py`
- Modify: `accounts/permissions.py` (+ `customer_or_guest`), `accounts/tests/test_permissions.py`, `cart/views.py`,
  `aria/urls.py` (`include('cart.urls')`), `products/views.py` + `products/urls.py` (`product_detail_view`,
  `products:detail` at `products/<int:product_id>/`), `products/templates/products/product_details.html` (add-to-cart form),
  `products/templates/products/browse.html` (link names to detail), `templates/base.html` (Cart link with item count, hidden for staff/admin)
- Delete: `cart/tests.py`, `cart/models.py` (no models in `cart`)

**Interfaces (Produces):**
- `accounts.permissions.customer_or_guest(view)`: anonymous and `ROLE_CUSTOMER` pass; staff/admin → 403. Added to `__all__`.
- `cart.cart.CartLine(product: Product, quantity: int, line_total: Decimal)`
- `cart.cart.Cart(request)`: session key `'cart'` = `{str(product_id): qty}`. `.add(product_id, qty)` (adds to existing),
  `.set(product_id, qty)` (`qty <= 0` removes), `.remove(product_id)`, `.lines() -> list[CartLine]` (one query, active products only,
  prunes unknown/inactive ids from the session and returns their names via `.dropped: list[str]`), `.subtotal() -> Decimal`,
  `.count() -> int`, `.clear()`. Quantity per line capped at 99.
- `cart.forms.AddToCartForm(quantity: 1..99)`, `UpdateCartForm(quantity: 0..99)`.
- Views, all `customer_or_guest`: `cart:detail` (GET `cart/`), `cart:add` (POST `cart/add/<product_id>/`, 404 for inactive product),
  `cart:update` (POST `cart/update/<product_id>/`). Lines whose quantity exceeds current stock show "Only N left".
- `products:detail`: public, `get_object_or_404(Product, pk=..., is_active=True)`.

- [ ] **Step 1: Failing tests** (`cart/tests/test_cart.py`, plus permissions tests):
  - `test_customer_or_guest_allows_anonymous_and_customer_forbids_staff_and_admin` (in `test_permissions.py`)
  - `test_add_set_remove_and_subtotal` (two products, Decimal subtotal)
  - `test_cart_drops_inactive_and_deleted_products` (deactivate one, delete another; `lines()` returns the rest; `.dropped` names the inactive one; session pruned)
  - `test_guest_can_add_to_cart_and_view_it`, `test_staff_and_admin_get_403_on_cart`
  - `test_cart_survives_login` (guest adds, posts to `accounts:login`, cart still has the line)
  - `test_add_inactive_product_404`, `test_update_to_zero_removes_line`, `test_cart_add_is_post_only` (GET → 405)
  - `test_product_detail_public_and_hides_inactive`
- [ ] **Step 2:** `TEST cart products accounts` → fail. **Step 3:** Implement. **Step 4:** `TEST` → pass.
- [ ] **Step 5:** Commit `feat(cart): public session cart, product detail page and cart views`.

### Task 5: `place_order` service

**Files:** Create `orders/services.py`, `orders/tests/test_place_order.py` (`TestCase` class `PlaceOrderTests`).

**Interfaces:**
- Consumes: `CartLine`, `quote`, `UnsupportedTaxRegion`, `FakeGateway`/`get_gateway`, `GatewayTimeout`, models from Tasks 1–3.
- Produces (`orders.services`):
  - `AddressData(line1, line2, city, region, postal_code, country)` (frozen dataclass) with `AddressData.from_address(address: Address)`.
  - `Contact(name: str, email: str | None)` (frozen dataclass).
  - `class CheckoutError(Exception)`; `OutOfStock(CheckoutError)` with `.product_ids: list[int]`;
    `PaymentDeclined(CheckoutError)` with `.reason`; `PaymentFailed(CheckoutError)` (timeouts / capture failure);
    `InvalidCheckout(CheckoutError)` (empty cart, guest without email, unknown shipping method, `UnsupportedTaxRegion`; message is user-facing).
  - `place_order(account: Account | None, cart_lines, *, contact: Contact, shipping: AddressData, billing: AddressData, shipping_method, payment_token, last4, method_type, card_brand, checkout_token, gateway=None) -> Order`
    (`account=None` = guest. Address-book ownership is checked by the checkout form in Task 7, which builds `AddressData`.)

**Algorithm** (master plan, with these additions):
0. Validate before anything is written or charged: non-empty lines; guest needs `contact.email`;
   `quote(...)` from **current DB prices** for the line products against `shipping.country/region`
   (`UnsupportedTaxRegion` → `InvalidCheckout("We can't calculate tax for <region>, <country>. Please check your shipping address.")`).
1. In `transaction.atomic()`: `Order.objects.get_or_create(checkout_token=..., defaults={...status PENDING_PAYMENT, contact, address copies, totals...})`
   and, only if created, the `OrderItem`s (unit_price snapshot). If not created: return it if
   `order.account_id == (account.pk if account else None)`, else raise `Order.DoesNotExist`. No gateway call either way.
2. `authorize`. Decline → `Payment(DECLINED)`, order `PAYMENT_FAILED`, raise `PaymentDeclined`. `GatewayTimeout` → `Payment(FAILED)`, order `PAYMENT_FAILED`, raise `PaymentFailed`.
3. Atomic block as in the master plan (lock products `order_by('pk')`; inactive or short → `OutOfStock`; else decrement,
   `InventoryMovement(change_qty=-qty, reason=SALE, reference_order=order)`, `capture`, `Payment(CAPTURED)`, order `CONFIRMED` + `confirmed_at`).
4. Outside: `OutOfStock` → `void`, `Payment(VOIDED)`, order `OUT_OF_STOCK`, re-raise. Capture failure/timeout → `void`, `Payment(FAILED)`, order `PAYMENT_FAILED`, raise `PaymentFailed`.
   A `void` that itself fails or times out is logged (order id + gateway ref only) and does not change the outcome.

- [ ] **Step 1: Failing tests** (pass `gateway=FakeGateway()` and assert on `gateway.calls`):
  - `test_successful_checkout_confirms_order_decrements_stock_and_logs_sale` (status, `confirmed_payment.status == CAPTURED`, stock, one SALE movement with `reference_order`, totals match `quote`, address copied)
  - `test_guest_checkout_creates_order_without_account`
  - `test_guest_without_email_rejected_before_payment`
  - `test_declined_payment_leaves_order_payment_failed_and_stock_untouched`
  - `test_authorize_timeout_leaves_order_payment_failed`
  - `test_capture_timeout_leaves_order_unconfirmed_and_restores_stock` (stock unchanged, no SALE movement, `('void', ref)` recorded, status `PAYMENT_FAILED`)
  - `test_out_of_stock_voids_authorization_and_shows_clear_message` (`OutOfStock.product_ids`, void recorded, no capture)
  - `test_inactive_product_treated_as_out_of_stock`
  - `test_same_checkout_token_twice_returns_same_order_and_charges_once` (one `authorize`, one `capture`)
  - `test_checkout_token_of_other_owner_is_rejected` (customer B replays A's token; guest replays A's token → `Order.DoesNotExist`; no new gateway calls)
  - `test_unsupported_tax_region_blocks_checkout_before_payment` (no Order row, `gateway.calls == []`)
  - `test_editing_address_book_does_not_change_existing_order`
  - `test_payment_row_stores_only_token_last4_and_brand`
- [ ] **Step 2:** `TEST orders.tests.test_place_order` → fail. **Step 3:** Implement. **Step 4:** `TEST` → pass.
- [ ] **Step 5:** Commit `feat(orders): place_order with authorize/lock/capture and idempotent checkout token`.

### Task 6: Concurrency tests

**Files:** Modify `orders/tests/test_place_order.py` (new `PlaceOrderConcurrencyTests(TransactionTestCase)`).

- [ ] **Step 1: Write** the two tests. Each runs `place_order` in two `threading.Thread`s started behind a
  `threading.Barrier(2)`, shares one `FakeGateway`, collects result-or-exception per thread, and calls
  `django.db.connection.close()` in each thread's `finally`.
  - `test_concurrent_last_unit_one_wins_loser_voided`: product stock 1, one customer and one guest, different tokens →
    exactly one `CONFIRMED`, one `OUT_OF_STOCK`; stock 0; one `capture`, one `void` in calls.
  - `test_concurrent_double_submit_same_token_authorizes_once`: same guest + token → both threads get the same
    `order_id`; exactly one `authorize` in calls; stock decremented once.
- [ ] **Step 2:** `TEST orders.tests.test_place_order` → pass (if not, fix `place_order`, not the test). Run it 3 times to check it isn't flaky.
- [ ] **Step 3:** Commit `test(orders): concurrent last-unit and double-submit checkout`.

### Task 7: Order pages (customer, guest link, lookup) and confirmation email

**Files:**
- Create: `orders/links.py`, `orders/emails.py`, `orders/urls.py`, `orders/views.py`, `orders/forms.py`,
  `orders/templates/orders/{history,detail,lookup,_order_body,_status_badge}.html`, `orders/templates/orders/email/confirmation.txt`,
  `orders/tests/test_views.py`
- Modify: `aria/urls.py` (`include('orders.urls')`), `aria/settings.py` (`DEFAULT_FROM_EMAIL = 'ordersaria.example'`), `templates/base.html` ("My orders" for customers, "Find my order" for guests)

**Interfaces (Produces):**
- `orders.links.guest_order_key(order) -> str`: `django.utils.crypto.salted_hmac('aria.guest-order', f'{order.pk}:{order.checkout_token}').hexdigest()`.
  `orders.links.guest_order_url(order) -> str` (path to `orders:guest_detail`). `orders.links.check_guest_order_key(order, key) -> bool` (`constant_time_compare`).
  Comment: rotating `SECRET_KEY` invalidates existing guest links (the lookup form still works).
- `orders.emails.send_order_confirmation(order, order_url: str) -> None`: plain-text email to `order.contact_email` (skip if none) with order number,
  items, totals, shipping method, masked payment, absolute link (`request.build_absolute_uri` is done by the caller). Mail errors are logged
  (order id only) and never fail the checkout.
- `orders.forms.OrderLookupForm(order_number: int, email: EmailField)`.
- Views:
  - `orders:history` (`login_required`, `orders/`, own orders, newest first, 20 per page).
  - `orders:detail` (`login_required`, `orders/<int:order_id>/`, `get_object_or_404(Order, pk=..., account=current_account(request))`).
  - `orders:guest_detail` (public, `orders/guest/<int:order_id>/<str:key>/`): `get_object_or_404(Order, pk=..., account__isnull=True)` and
    404 unless `check_guest_order_key`. Page says "Bookmark this page to check your order later." Response sets `Referrer-Policy: no-referrer`.
  - `orders:lookup` (public, `orders/find/`): POST matches `pk=order_number, account__isnull=True, contact_email__iexact=email` → redirect to the
    guest link; otherwise re-render with "We couldn't find an order with that number and email." (identical for every miss, including account orders).
  - Detail pages share `_order_body.html`: items, totals, shipping method, address copies, status badge, masked payment, carrier + tracking link
    when shipped. Never `risk_score`. Status text "Confirmed" only via `order.get_status_display()` for `CONFIRMED`.

- [ ] **Step 1: Failing tests** (`orders/tests/test_views.py`):
  - `test_customer_cannot_view_other_customers_order` → 404
  - `test_customer_cannot_view_guest_order_via_customer_detail_url` → 404
  - `test_history_lists_only_own_orders_paginated`
  - `test_guest_link_shows_order`
  - `test_guest_link_wrong_key_or_account_order_404` (wrong key → 404; correct-format key for an account's order → 404)
  - `test_lookup_redirects_to_guest_link_on_match_case_insensitive_email`
  - `test_lookup_wrong_email_same_message_as_missing_order` (wrong email, nonexistent number, account order → identical response body message)
  - `test_failed_order_page_never_says_confirmed`
  - `test_customer_and_guest_pages_never_render_risk_score` (set `risk_score=Decimal('87.50')`; assert `'87.5'` and `'risk'` (case-insensitive) absent from history, detail, guest detail and the email)
  - `test_confirmation_email_contains_link_and_masked_card_only`
- [ ] **Step 2:** `TEST orders` → fail. **Step 3:** Implement. **Step 4:** `TEST` → pass.
- [ ] **Step 5:** Commit `feat(orders): customer order history, guest order link and lookup, confirmation email`.

### Task 8: Checkout page (guest and customer)

**Files:**
- Create: `cart/templates/cart/checkout.html`, `cart/tests/test_checkout.py`
- Modify: `cart/views.py`, `cart/forms.py`, `cart/urls.py`

**Interfaces:**
- Consumes: `place_order`, `AddressData`, `Contact`, exceptions (Task 5); `TEST_CARDS` (Task 3); `quote`, `normalize_region` (Task 1);
  `orders.links.guest_order_url`, `orders.emails.send_order_confirmation` and the `orders:detail` URL (Task 7).
- Produces:
  - `cart.forms.CheckoutAddressForm(prefix)`: `line1, line2, city, region, postal_code, country` with `normalize_region` in `clean`; `.to_address_data() -> AddressData`.
  - `cart.forms.CheckoutForm(account: Account | None, data=None, initial=None)`: for a customer, `shipping_address` / `billing_address`
    (`ModelChoiceField` over **that account's** addresses of that type, defaults preselected); for a guest, `contact_name` (required),
    `contact_email` (required) and the address forms (`prefix='ship'` / `'bill'`); for both, `billing_same` (checked by default; billing
    fields/choice only required when unchecked; a customer's billing choice may be any of their addresses), `shipping_method` (radio over
    `SHIPPING_METHODS`), `test_card` (radio over `TEST_CARDS`, labels only, no token in HTML), hidden `checkout_token` (UUID) and `expected_total` (Decimal).
    `.shipping_data()`, `.billing_data() -> AddressData`, `.contact() -> Contact` (customer: profile name/email if a Profile exists, else username + `None`).
  - `cart:checkout` (`customer_or_guest`, `cart/checkout/`). GET: empty cart → redirect `cart:detail`; render a fresh `uuid4` token, the quote
    for the current selections, a banner "Test payments: no real card is charged.", and for guests a line "Have an account? Log in" (link to
    `accounts:login`) / "Register". Customer with no shipping address → link to `accounts:address_create`. Submit button disabled by inline JS
    on submit (UI layer only). A GET "Update totals" button re-quotes for the chosen address/shipping method (no JS framework).
  - POST: re-quote; if `quote.total != expected_total` → re-render with new totals and "Prices or totals changed. Please review and submit again.", no `place_order` call.
    Otherwise call `place_order` with the test card's token/last4/brand/method_type, then:
    `CONFIRMED` (or an existing order returned by a double submit) → `cart.clear()`, send the confirmation email (only when this request
    confirmed it), success message "Order #N confirmed.", redirect to `orders:detail` (customer) or `guest_order_url(order)` (guest);
    `PaymentDeclined`/`PaymentFailed` → re-render with fresh token and "Your payment didn't go through. You have not been charged.";
    `OutOfStock` → redirect `cart:detail` with "Sorry, <names> sold out before your order completed. You have not been charged.";
    `InvalidCheckout` → re-render with its message.

- [ ] **Step 1: Failing tests** (`cart/tests/test_checkout.py`):
  - `test_checkout_get_renders_token_test_cards_and_quote` (no `tok_` string in HTML)
  - `test_guest_checkout_success_redirects_to_private_link_clears_cart_and_emails` (`len(mail.outbox) == 1`, link in body, no `tok_` and no `last4` digits beyond `•••• 4242`)
  - `test_customer_checkout_success_redirects_to_order_detail`
  - `test_guest_checkout_requires_name_email_and_valid_address`
  - `test_checkout_declined_rerenders_with_message_and_keeps_cart`
  - `test_checkout_out_of_stock_redirects_to_cart_with_message`
  - `test_price_change_since_checkout_page_blocks_order` (change `unit_price` between GET and POST → no Order row, new total shown)
  - `test_checkout_rejects_other_customers_or_wrong_type_address`
  - `test_checkout_double_post_same_token_creates_one_order_and_one_email`
  - `test_staff_and_admin_get_403_on_checkout`
- [ ] **Step 2:** `TEST cart` → fail. **Step 3:** Implement. **Step 4:** `TEST` → pass.
- [ ] **Step 5:** Commit `feat(checkout): guest and customer checkout with test cards`.

### Task 9: Staff order pages, `mark_shipped`, carriers in sample data

**Files:**
- Create: `orders/staff_views.py`, `orders/templates/orders/staff_list.html`, `orders/templates/orders/staff_detail.html`, `orders/tests/test_staff_views.py`
- Modify: `orders/services.py`, `orders/forms.py`, `orders/urls.py`, `templates/base.html` ("Orders" for staff/admin), `products/management/commands/sample_data.py` (carriers), `products/tests.py` (sample data test)

**Interfaces (Produces):**
- `orders.services.InvalidTransition(CheckoutError)`; `mark_shipped(staff: Account, order_id: int, carrier_id: int, tracking_number: str) -> Order`:
  `select_for_update`, only `CONFIRMED → SHIPPED`, sets carrier + tracking (stripped, non-empty), else `InvalidTransition`.
- `orders.forms.MarkShippedForm(carrier: ModelChoiceField, tracking_number: CharField(max 100))`; `StaffOrderFilterForm(status, date_from, date_to)`.
- `orders:staff_list` (`staff/orders/`, 50 per page, filters on indexed `status`/`created_at`, `select_related('account')`; guest orders shown as "Guest" + contact name),
  `orders:staff_detail` (`staff/orders/<id>/`, shows `mask_payment`, contact details, `risk_score` if set, mark-shipped form when `CONFIRMED`),
  `orders:staff_mark_shipped` (POST only). All `role_required(ROLE_STAFF, ROLE_ADMIN)`.
- `sample_data` creates (idempotently) carriers `Canada Post`, `Purolator`, `UPS`, `FedEx` with placeholder
  `tracking_url_template` values of the form `https://example.com/track/{tracking_number}`.

- [ ] **Step 1: Failing tests:**
  - `test_staff_list_shows_customer_and_guest_orders_and_filters_by_status`
  - `test_customer_gets_403_on_staff_order_pages`, `test_anonymous_redirected_to_login`
  - `test_staff_order_detail_shows_masked_payment_only` (response contains `•••• 4242`, not the token `tok_ok`)
  - `test_mark_shipped_sets_carrier_and_tracking`, `test_mark_shipped_rejects_unconfirmed_order` (`PAYMENT_FAILED` → message, unchanged)
  - `test_staff_list_query_count_constant` (`assertNumQueries` same for 3 and 30 orders)
  - `test_sample_data_creates_carriers_idempotently` (in `products/tests.py`)
- [ ] **Step 2:** `TEST orders products` → fail. **Step 3:** Implement. **Step 4:** `TEST` → pass.
- [ ] **Step 5:** Commit `feat(orders): staff order list/detail and mark shipped`.

### Task 10: Follow-up notes, docs, verification, PR

**Files:** Create `docs/follow-ups.md`. Modify `CLAUDE.md` (layout: `orders/`, `payments/`, `cart/`; implemented tables; guest checkout
in Roles; a line "Payments and tax are TEMPORARY (FakeGateway, placeholder tax table); see docs/follow-ups.md"),
`docs/superpowers/plans/2026-10-14-aria-build-structure.md` (Phase 2: `request_refund` must also accept a guest authorized by the
private order link; Phase 5: retention must cover order contact/address copies and guest orders).

`docs/follow-ups.md` must contain, under **Payments (TODO: add payment API and test it)**:
- Replace `FakeGateway` with a Stripe gateway (PaymentIntents with manual capture → authorize/capture/void map 1:1); keep the `PaymentGateway` protocol.
- Card entry via Stripe Elements so card data never touches our server; remove the test-card picker (`payments/test_cards.py`) from checkout.
- Pass the checkout token as the Stripe idempotency key; add webhook handling and reconciliation for capture timeouts (a timeout can mean "captured but we didn't hear back").
- Sweep for orders stuck in `PENDING_PAYMENT` (process crash between steps).
- Test plan: Stripe test mode + test cards for success, decline, 3-D Secure, timeout; rerun the Phase 1 concurrency tests against the new gateway.
- Refuse to start with `FakeGateway` when `DEBUG=False`.

Under **Tax**: replace `orders/pricing.py` tax tables with Stripe Tax (local US rates, product taxability, shipping taxability per state); keep `quote()` as the seam.

Under **Guest checkout / email**: real email provider (console backend today); rate-limit `orders:lookup`; decide retention for guest
contact/address data (Phase 5).

- [ ] **Step 1:** Write `docs/follow-ups.md`, the CLAUDE.md updates and the master-plan notes.
- [ ] **Step 2:** `TEST` → full suite passes; record the count.
- [ ] **Step 3:** Manual smoke run (`docker compose up --build`, `sample_data`): a guest checks out with each test card and reopens the order
  via the link and via lookup; a customer checks out from the address book; staff marks one shipped.
- [ ] **Step 4:** Commit `docs: phase 1 follow-ups (payment API, tax) and CLAUDE.md layout`; push `feature/checkout`; open PR into `master`.
