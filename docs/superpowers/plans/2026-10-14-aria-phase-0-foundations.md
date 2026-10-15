# Phase 0: Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce role permissions server-side with one shared module, add the Staff role and customer addresses, and fix the broken seed test and profile-creation bug, so Phase 1 (checkout) can build on them.

**Architecture:** `accounts/permissions.py` is the single place that resolves the logged-in `Account` from the session and gates views by role. All existing admin views switch to it. `Address` lives in `accounts` and is only ever queried through `account=current_account(request)`.

**Tech Stack:** Django 6.1, PostgreSQL. No new dependencies.

**Spec:** `CLAUDE.md`; master plan `docs/superpowers/plans/2026-10-14-aria-build-structure.md` (Phase 0).

## Global Constraints

- Roles: `'user'` = Customer, `'staff'` = Staff, `'admin'` = Admin (`Account.account_type`).
- No account → redirect to `accounts:login`. Wrong role → HTTP 403. Another customer's object → HTTP 404.
- Schema changes via `makemigrations` only.
- Address country limited to `CA`, `US` (existing Phase 1 design; no international tax).

**Test command** (Django 6.1 needs Python ≥ 3.12, so tests run in the project's Docker image against host Postgres), from repo root:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/aria_project:/app" -e DB_HOST=host.docker.internal django python manage.py test
```

Abbreviated below as `TEST [label]`.

## Review Focus

1. **Session points at a deleted account** → treated as logged out, not a 500. Test: `test_current_account_none_when_session_account_deleted` (Task 2).
2. **Customer edits another customer's address by changing the URL ID** → 404, row unchanged. Test: `test_customer_cannot_edit_other_customers_address` (Task 5).
3. **Two users register and both leave the profile page before submitting** → both succeed (no unique-email collision on `''`). Test: `test_two_users_can_register_before_filling_profile` (Task 4).
4. **Second default address of the same type** → the previous default is cleared, not an IntegrityError. Test: `test_setting_new_default_clears_previous_default` (Task 5).
5. **Staff hits admin product pages** → 403 (staff must not edit products). Test: `test_staff_gets_403_on_product_and_category_pages` (Task 3).

---

### Task 1: Green baseline (seed test name)

**Files:** Modify `aria_project/products/tests.py` (`SampleDataCommandTests`)

- [ ] **Step 1:** Change both `call_command('seed_sample_data', ...)` to `call_command('sample_data', ...)`.
- [ ] **Step 2:** `TEST products` → all pass (15 tests).
- [ ] **Step 3:** Commit `test: call sample_data command by its real name`.

### Task 2: Permissions module + Staff role

**Files:**
- Modify: `aria_project/accounts/models.py`
- Create: `aria_project/accounts/permissions.py`, migration `0004` (via makemigrations), `aria_project/accounts/tests/__init__.py`, `aria_project/accounts/tests/test_permissions.py`
- Delete: `aria_project/accounts/tests.py` (empty stub; replaced by package)

**Interfaces (Produces):**
- `accounts.models`: `ROLE_CUSTOMER = 'user'`, `ROLE_STAFF = 'staff'`, `ROLE_ADMIN = 'admin'`, `ROLES = (ROLE_CUSTOMER, ROLE_STAFF, ROLE_ADMIN)`; `valid_account_type` constraint uses `ROLES`.
- `accounts.permissions.current_account(request) -> Account | None`: cached on `request._aria_account`.
- `accounts.permissions.login_required(view)`, `accounts.permissions.role_required(*roles)` (re-exports the `ROLE_*` constants).

- [ ] **Step 1: Failing tests** in `test_permissions.py` using a `RequestFactory` request with a `SessionStore` session, plus tiny inline views decorated in the test:
  - `test_current_account_returns_account_from_session`
  - `test_current_account_none_when_not_logged_in`
  - `test_current_account_none_when_session_account_deleted`
  - `test_login_required_redirects_anonymous_to_login` (302, `Location` == `reverse('accounts:login')`)
  - `test_role_required_redirects_anonymous_to_login`
  - `test_role_required_forbids_wrong_role` (customer on `role_required(ROLE_ADMIN)` → 403)
  - `test_role_required_allows_listed_roles` (staff and admin on `role_required(ROLE_STAFF, ROLE_ADMIN)` → 200)
  - `test_db_accepts_staff_and_rejects_unknown_account_type` (`IntegrityError` for `'superuser'`)
- [ ] **Step 2:** `TEST accounts` → fail (ImportError).
- [ ] **Step 3:** Implement constants + permissions module; decorators use `functools.wraps`. `login_required` adds `messages.error(request, 'You must be logged in to view that page.')` before redirecting (matches existing view copy style). Run `makemigrations accounts` in the container.
- [ ] **Step 4:** `TEST` → all pass.
- [ ] **Step 5:** Commit `feat(accounts): add staff role and shared permission decorators`.

### Task 3: Lock admin pages server-side

**Files:** Modify `aria_project/products/views.py`, `aria_project/products/tests.py`

- [ ] **Step 1: Failing tests** (new `ProductPermissionTests` in `products/tests.py`), parametrized over the 5 admin URLs `dashboard`, `product_create`, `product_edit`, `category_create`, `category_edit`:
  - `test_anonymous_redirected_to_login_and_nothing_saved` (GET and POST; no Product/Category created or changed)
  - `test_customer_gets_403_on_product_and_category_pages`
  - `test_staff_gets_403_on_product_and_category_pages`
  - `test_browse_stays_public`
- [ ] **Step 2:** `TEST products` → fail.
- [ ] **Step 3:** Decorate the five views with `@role_required(ROLE_ADMIN)`; remove the hand-rolled session/role check in `dashboard_view`. Give `CategoryManagementTests` an admin session in `setUp` (same pattern as `ProductManagementTests`).
- [ ] **Step 4:** `TEST` → all pass.
- [ ] **Step 5:** Commit `fix(products): require admin role for dashboard and product/category editing`.

### Task 4: Profile creation without empty-email collisions

**Files:** Modify `aria_project/accounts/views.py` (`update_profile`); Test `aria_project/accounts/tests/test_profile.py`

- [ ] **Step 1: Failing tests:**
  - `test_two_users_can_register_before_filling_profile`: register `a` and `b` via POST to `accounts:register`, GET `accounts:update_profile` for each → both 200; `Profile.objects.count() == 0`.
  - `test_profile_created_on_first_valid_submit` (POST → one Profile linked to the session account).
  - `test_update_profile_requires_login` (anonymous → redirect to login).
- [ ] **Step 2:** `TEST accounts` → first test fails with `IntegrityError`.
- [ ] **Step 3:** `update_profile(request)` (drop the unused `account_id` parameter, which would allow editing others if ever routed), wrapped in `@login_required`. Load `Profile.objects.filter(account=account).first()`; bind `ProfileEditForm(instance=profile)`; on valid POST with no profile, `form.save(commit=False)`, set `account`, save. No Profile row is created on GET.
- [ ] **Step 4:** `TEST` → all pass.
- [ ] **Step 5:** Commit `fix(accounts): create profile on submit, not on page load`.

### Task 5: Customer addresses

**Files:**
- Modify: `aria_project/accounts/models.py`, `aria_project/accounts/forms.py`, `aria_project/accounts/views.py`, `aria_project/accounts/urls.py`, `aria_project/templates/base.html` (nav link "Addresses" when logged in)
- Create: migration `0005` (makemigrations), `aria_project/accounts/templates/accounts/address_list.html`, `aria_project/accounts/templates/accounts/address_form.html`, `aria_project/accounts/tests/test_addresses.py`

**Interfaces (Produces, consumed by Phase 1 checkout):**
- `Address` (`db_table='addresses'`): `address_id` BigAutoField PK, `account` FK(Account, CASCADE, related_name='addresses'), `address_type` in `('SHIPPING','BILLING')`, `line1`, `line2` (blank/null), `city`, `region`, `postal_code`, `country` in `('CA','US')`, `is_default` bool, `created_at`.
  - Constraints: `address_type_valid`, `address_country_valid` (CheckConstraint); `one_default_address_per_type` (UniqueConstraint on `account, address_type`, `condition=Q(is_default=True)`).
  - Index `idx_addresses_account_type` on `(account, address_type)`.
- `accounts.forms.AddressForm` (ModelForm; all fields except `account`, `created_at`; Bootstrap classes like existing forms).
- `accounts.views.save_address(account, form) -> Address`: inside `transaction.atomic()`, if `is_default`, clear other defaults of the same type for that account first.
- URLs: `accounts:address_list` `addresses/`, `accounts:address_create` `addresses/new/`, `accounts:address_edit` `addresses/<int:address_id>/edit/`, `accounts:address_delete` `addresses/<int:address_id>/delete/` (POST only). All `@login_required`; object lookups `get_object_or_404(Address, address_id=..., account=current_account(request))`.

- [ ] **Step 1: Failing tests:**
  - `test_address_list_shows_only_own_addresses`
  - `test_create_address_links_to_logged_in_account` (POSTed `account` field ignored)
  - `test_customer_cannot_edit_other_customers_address` (GET and POST → 404; row unchanged)
  - `test_customer_cannot_delete_other_customers_address` (404; row still exists)
  - `test_delete_requires_post` (GET → 405)
  - `test_setting_new_default_clears_previous_default`
  - `test_db_rejects_two_defaults_of_same_type` (`IntegrityError`)
  - `test_rejects_country_outside_ca_us` (form invalid)
  - `test_address_pages_require_login`
- [ ] **Step 2:** `TEST accounts` → fail.
- [ ] **Step 3:** Implement model, `makemigrations accounts`, form, views, urls, templates (extend `base.html`, follow `auth.html` layout), nav link.
- [ ] **Step 4:** `TEST` → all pass.
- [ ] **Step 5:** Commit `feat(accounts): customer address book scoped to the logged-in account`.

### Task 6: Docs and PR

- [ ] Update `CLAUDE.md`: Staff role now exists; remove the "Known gap" line about unprotected product views; add the Docker test command.
- [ ] `TEST` full suite → all pass. Commit `docs: update CLAUDE.md for phase 0`.
- [ ] Push `feature/foundations`, open PR into `master` (ask before pushing).
