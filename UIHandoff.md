# UI Handoff: Figma prototype → Django templates

Branch: `UI-and-CD-CI`
Figma: "ARIA (Copy)", page **06 Prototype** (file key `bOglhOtSK3Rmv9rFTJmg8n`, node `22:9005`)

This document explains what was built from the Figma prototype, where it lives, what is
real versus preview-only, and what is still open. ALL DATA IS SYNTHETIC.

---

## 1. Summary

- Every screen on the Prototype page now has a responsive Django template that covers
  both the 1440px desktop frame (D-…) and the 390px mobile frame (M-…).
- The look comes from one design system stylesheet built from the Figma variables.
  Bootstrap 5 is still loaded for the grid and utilities, and its components are re-skinned.
- Screens with a backend (storefront, cart, checkout, orders, staff orders, admin products)
  were restyled **template-only**. View, order, payment and stock logic is unchanged.
- Screens without a backend yet (refunds, Ask Aria chatbot) are **read-only previews**.
  They are GET-only, write nothing, and show a "Preview" notice on every page.
- Admin analytics uses **real** read-only aggregates from the database. Refund figures
  show "Unavailable" until refunds exist.
- Tests: 276 passing, `ruff check .` clean.

---

## 2. Design system

| Piece | Location |
|---|---|
| Tokens + shared components | `aria_project/static/css/aria.css` |
| Site shell (skip link, top nav, messages, footer, Ask Aria button) | `aria_project/templates/base.html` |
| Nav context (admin flag, storefront categories, current view) | `aria_project/core/context_processors.py` (`site_nav`) |
| Page CSS | `static/css/storefront.css`, `checkout.css`, `backoffice.css` (loaded per page via `{% block extra_css %}`) |
| Icons / photos (downloaded from Figma) | `aria_project/static/img/icons/`, `aria_project/static/img/photos/` |

**Tokens** (CSS custom properties on `:root`, mirroring the Figma variables):
- Brand `--color-brand-primary #0e6e66`
- Text: primary `#0a1f24`, secondary `#4a5f5e`
- Background: page `#f4efe6`, surface `#fff`, subtle `#e9e2d6`, inverse `#04161a`
- Border: default `#d9d0c1`, strong `#7a8b88`
- Status colours: success, warning, error and info, each with a `-bg` variant
- Accent button `#ff5a36` (`.btn-accent`) uses a dark label, because a white label fails AA contrast.
- Type: Bricolage Grotesque (headings) and Instrument Sans (body), from Google Fonts.

**Components** (classes in `aria.css`):
- Layout: `.aria-page`, `.page-heading`, `.aria-columns`
- Panels: `.aria-card`, `.feature-panel`
- Fields: `.aria-field` (Figma text field with the label inside the box), `.field-error`
- Buttons: `.btn-primary`, `.btn-secondary`, `.btn-link`, `.btn-accent`, `.text-action`
- Status and filters: `.status-badge--success|warning|error|info|neutral`, `.chip`
- Products: `.product-grid`, `.product-card`
- Data display: `.table-wrap`, `.summary-row`, `.aria-steps`
- Other: `.prototype-notice`, `.aria-spinner`

**Shell behaviour** (`base.html`):
- The top nav depends on the role:
  - **Guests and customers** see storefront categories, search, the account menu and the cart with its count.
  - **Staff** see Orders and Refunds.
  - **Admin** also see Products and Analytics.
- Flash messages render once, centrally, in `{% block messages %}`. Templates should not loop over `messages` themselves.
- The Ask Aria button appears on every page except Ask Aria itself.
- The status-annotation pill above each Figma frame (EMPTY/ERROR/…) and the designer's footer text are not part of the UI.

**Accessibility** (Figma page 07):
- Skip link and visible focus rings.
- Targets are at least 44px.
- Every input has a label.
- Status text is never shown by colour alone.
- Charts have a table alternative (`analytics:data`).

---

## 3. Screen map

Desktop / mobile node IDs refer to the 06 Prototype page.

### Storefront, sign-in, chat
| Figma screen | Nodes (D / M) | URL name | Template |
|---|---|---|---|
| Sign in (EMPTY, TYPING, ERROR) | 22:372, 22:623, 22:775 / 22:291, 22:551, 22:680 | `accounts:login` | `accounts/auth.html` |
| Create account | 22:912 / 22:844 | `accounts:register` | `accounts/auth.html` |
| Browse | 22:1141 / 22:971 | `products:browse` | `products/browse.html` (+ `_hero.html`) |
| Home | (reuses the Browse hero) | `core:home` | `core/home.html` |
| Product detail / Added to cart | 22:1368, 22:1563 / 22:1255, 22:1454 | `products:detail` | `products/product_details.html` |
| Cart / Empty cart | 22:1742, 22:1853 / 22:1653, 22:1809 | `cart:detail` | `cart/detail.html` |
| Address book | (Figma field styles) | `accounts:address_*` | `accounts/address_list.html`, `address_form.html` |
| Ask Aria (answer, no source, action boundary) **preview** | 22:6612, 22:6750, 22:6871 / 22:6534, 22:6698, 22:6817 | `chat:ask` (`?state=`) | `chat/ask.html` |

### Checkout and customer orders
| Figma screen | Nodes (D / M) | URL name | Template |
|---|---|---|---|
| Checkout / validation error | 22:2044, 22:2301 / 22:1883, 22:2171 | `cart:checkout` | `cart/checkout.html` (+ `_checkout_field.html`) |
| Review order | 22:2485 / 22:2414 | `cart:checkout` | the summary panel on the checkout page (no separate step, see §5) |
| Processing payment | 22:2630 / 22:2543 | `cart:checkout` | button spinner on submit, plus a pending panel on order detail |
| Order confirmed | 22:2787 / 22:2694 | `orders:detail` | `orders/detail.html`, `_order_body.html` |
| Payment failed | 22:9072 / 22:9013 | `cart:checkout`, `orders:detail` | error alert, plus a failed panel on order detail |
| Out of stock at commit | 22:9195 / 22:9149 | `cart:detail` | the existing redirect with its message |
| Order history | 22:3045 / 22:2865 | `orders:history` | `orders/history.html` |
| Guest order lookup | (Figma field styles) | `orders:lookup` | `orders/lookup.html` |
| Refund reason / items / confirm / requested **preview** | 22:3293, 22:3438, 22:3567, 22:3697 / 22:3202, 22:3359, 22:3500, 22:3623 | `refunds:request` (`?step=`) | `refunds/request.html` (+ `_request_items.html`) |

### Staff and admin
| Figma screen | Nodes (D / M) | URL name | Template |
|---|---|---|---|
| Staff orders | 22:3940 / 22:3756 | `orders:staff_list`, `orders:staff_detail` | `orders/staff_list.html`, `staff_detail.html` |
| Refund review, processing, approved, decline reason, declined **preview** | 22:4302, 22:4499, 22:4656, 22:4822, 22:4993 / 22:4169, 22:4412, 22:4575, 22:4726, 22:4902 | `refunds:staff_queue`, `refunds:staff_review` (`?state=`) | `refunds/staff_queue.html`, `staff_review.html` |
| Admin analytics | 22:5285 / 22:5073 | `analytics:dashboard` | `analytics/dashboard.html` (+ `_kpis`, `_low_stock`, `_refunds`) |
| Accessible analytics data | 22:5690 / 22:5512 | `analytics:data` | `analytics/data.html` |
| Edit product / validation / saved | 22:6078, 22:6292, 22:6469 / 22:5961, 22:6180, 22:6393 | `products:product_edit`, `product_create` | `products/product_form.html` |
| Product dashboard, category form | (Figma table and field styles) | `products:dashboard`, `category_*` | `products/dashboard*.html`, `category_form.html` |

**Status badge:** `orders/_status_badge.html` is driven only by `order.status`. "Confirmed" styling appears only when the order really is confirmed (CLAUDE.md invariant 1).

---

## 4. Preview-only screens (no backend yet)

New apps: `refunds/`, `chat/`, `analytics/`. Every route is registered in the role-guard
POLICY table in `accounts/tests/test_url_guards.py`.

| Route | Who | Behaviour |
|---|---|---|
| `refunds:request` | customer only (staff/admin 403, another customer's order 404) | Uses the customer's real order lines. Steps move by GET links. Nothing submits. The last step says **"No refund request was created."** |
| `refunds:staff_queue`, `refunds:staff_review` | staff and admin | Clearly synthetic sample data defined in the view. Risk labels are marked as samples. The buttons only switch between the designed states. |
| `chat:ask` | everyone | Sample answers. The "no source" state refuses and offers a person; the "action boundary" state explains it can't act. There is no form and no POST handler. It has no access to orders or refunds (CLAUDE.md invariants 5 and 6). |
| `analytics:dashboard`, `analytics:data` | admin only | Real aggregates from 5 bounded queries (revenue and orders by month and day, orders by status, top products, low stock). Refund metrics show "Unavailable". No payment data is read. |

All preview views are GET-only, and their tests assert that POST returns 405 and nothing is written.
When refunds and the chatbot are built, replace these views. Don't extend them.

---

## 5. Known gaps and deviations

**Not built, because they would change checkout or order code** (CLAUDE.md requires a plan first):
1. A separate "Review order" step page. The checkout page's summary panel serves as the review.
2. Saved-details summary with "Edit" links at checkout. Customers get an address select plus a "Manage addresses" link.
3. A dedicated "item unavailable" checkout page. The existing redirect to the cart with a message is kept.
4. "Session expired during checkout" (22:9301). This state doesn't exist in the app.
5. Item, card and delivery details on order history cards. This needs `select_related`/`prefetch_related` in `orders/views.py`.
6. Estimated delivery date on the confirmation page. There is no data for it.
7. Staff orders search and payment-status filter, and a masked-payment column. The first two need backend support; the column needs `select_related` in `staff_list_view` to avoid N+1 queries.

**Deviations for data or model reasons:**
- **Product photos:** products have no image field, so neutral placeholder tiles stand in for photos. Adding photos needs a schema change.
- **Sign-in fields:** sign-in and create account use the existing username/password fields; the design shows email and full name.
- **Checkout and cart headers:** they keep the normal site header, not the design's separate "Back / Secure checkout" header.
- **Mobile summary:** the mobile "Order summary · Show" collapse isn't built. The summary always shows.
- **Product form:** strap/colour variants and image upload aren't shown (no data for them).
- **Order references:** staff order references show as `#id`, not `AR-…`.

**Verification:**
- Desktop (1440) was checked in Chrome against the Figma frames: browse, product, sign-in, Ask Aria, analytics, staff orders and refund review.
- **The 390px phone layout has not been checked in a browser.** Chrome wouldn't go below 500px; at 500px columns stack and nothing overflows horizontally.
- The sample seed has no orders, so order and analytics pages were only seen in their empty states.

---

## 6. Issues found during this work

- **Fixed:**
  - `products:detail` was missing `@customer_or_guest`.
  - `cart:update` accepted unknown or inactive products.
- **Open, decision needed:**
  - **Guest order lookup can be guessed:** no rate limit, and order numbers are sequential (the most important item).
  - **Raw error page:** a gateway or database error mid-checkout shows a 500. Data stays consistent.
  - **No message for a dropped cart item:** when the only cart item is deactivated just before submit, the customer only sees "Your cart is empty."
  - **No server-side minimum on product fields:** `ProductForm` has no minimum on price or stock. A negative price is accepted, and negative stock likely causes a 500 from a database constraint.
  - **Compose vs CLAUDE.md:** `docker-compose.yml` defines a Postgres service, which contradicts CLAUDE.md.

---

## 7. How to run and check

```bash
# tests + lint (repo root, Git Bash): see docs/ci-cd.md for the full CI recipe
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/aria_project:/app" -e DB_HOST=host.docker.internal django python manage.py test
ruff check .

# local app with sample data
cd aria_project
python manage.py migrate
python manage.py create_sample_data --password <pw>
python manage.py runserver
```

Preview states to look at:
- `/ask-aria/?state=answer|no-source|action-boundary`
- `/orders/<id>/refund/?step=reason|items|confirm|requested` (as the customer who owns the order)
- `/staff/refunds/review/?state=review|processing|approved|decline-reason|declined` (as staff)
- `/analytics/` and `/analytics/data/` (as admin)

**Adding a new screen:**
1. Extend `base.html` and wrap the content in `.aria-page`.
2. Use the `aria.css` components; put page-only CSS in a page stylesheet.
3. Don't render `messages` in the template.
4. Add the new URL to POLICY in `accounts/tests/test_url_guards.py` (the test fails until you do).
