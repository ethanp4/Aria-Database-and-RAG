"""Table-driven authorization check over every URL the app routes.

Spec (CLAUDE.md "Auth" and "Roles and permissions"):
- account pages: not logged in -> redirect to accounts:login
- staff pages (orders, refunds): staff and admin only; customer -> 403
- admin pages (dashboard, product/category create+edit): admin only; customer/staff -> 403
- public storefront (product detail, cart, checkout) is @customer_or_guest:
  guests and customers pass, staff/admin -> 403
- guest order link and lookup are public

Every named URL outside /admin/ must be listed in POLICY. A new view that is not
classified here fails test_every_url_is_classified, so it can't ship without a guard decision.
"""
import uuid
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account, Address
from orders.links import guest_order_key
from orders.models import Carrier, Order
from payments.models import Payment
from products.models import Category, Product

PUBLIC = 'public'          # anyone, including staff/admin
STOREFRONT = 'storefront'  # @customer_or_guest
LOGIN = 'login'            # any logged-in account
STAFF = 'staff'            # staff + admin
ADMIN = 'admin'            # admin only
ANY_POST = 'any_post'      # logout: not role gated
API_LOGIN = 'api_login'    # JSON API for any logged-in account: anonymous -> 401, no redirect

POLICY = {
    'core:home': PUBLIC,
    'accounts:login': PUBLIC,
    'accounts:register': PUBLIC,
    'accounts:logout': ANY_POST,
    'accounts:update_profile': LOGIN,
    'accounts:address_list': LOGIN,
    'accounts:address_create': LOGIN,
    'accounts:address_edit': LOGIN,
    'accounts:address_delete': LOGIN,
    'products:browse': PUBLIC,
    # CLAUDE.md: "Public storefront views (product detail, cart, checkout) use @customer_or_guest"
    'products:detail': STOREFRONT,
    'products:dashboard': ADMIN,
    'products:product_create': ADMIN,
    'products:product_edit': ADMIN,
    'products:category_create': ADMIN,
    'products:category_edit': ADMIN,
    'cart:detail': STOREFRONT,
    'cart:add': STOREFRONT,
    'cart:update': STOREFRONT,
    'cart:checkout': STOREFRONT,
    'orders:history': LOGIN,
    'orders:detail': LOGIN,
    'orders:lookup': PUBLIC,
    'orders:guest_detail': PUBLIC,
    'orders:staff_list': STAFF,
    'orders:staff_detail': STAFF,
    'orders:staff_mark_shipped': STAFF,
    # UI prototype stubs (GET only, no writes). Customer refund request is customer-only:
    # staff/admin get 403, another customer's order 404.
    'refunds:request': LOGIN,
    'refunds:staff_queue': STAFF,
    'refunds:staff_review': STAFF,
    'analytics:dashboard': ADMIN,
    'analytics:data': ADMIN,
    # chatbot: guests, customers and staff may ask questions (CLAUDE.md roles)
    'chat:ask': PUBLIC,
    # RAG chatbot stream: any signed-in role; sources are role-scoped inside the view
    'chatbot:stream': API_LOGIN,
}

# views the spec says are POST only; they are probed with POST
POST_ONLY = {'accounts:logout', 'accounts:address_delete', 'cart:add', 'cart:update',
             'orders:staff_mark_shipped', 'chatbot:stream'}

LOGIN_URL = reverse('accounts:login')


def all_url_names():
    names = []

    def walk(patterns, namespace):
        for p in patterns:
            if isinstance(p, URLResolver):
                if p.app_name == 'admin' or p.namespace == 'admin':
                    continue
                ns = p.namespace or namespace
                walk(p.url_patterns, ns)
            elif isinstance(p, URLPattern) and p.name:
                names.append(f'{namespace}:{p.name}' if namespace else p.name)

    walk(get_resolver().url_patterns, None)
    return names


def make_account(username, role):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def make_order(account=None, **kw):
    fields = dict(
        account=account, contact_name='Guest Buyer', contact_email='guest@example.com',
        ship_line1='1 Test St', ship_city='Vancouver', ship_region='BC',
        ship_postal_code='V6B 1A1', ship_country='CA',
        bill_line1='1 Test St', bill_city='Vancouver', bill_region='BC',
        bill_postal_code='V6B 1A1', bill_country='CA', shipping_method='STANDARD',
        subtotal=Decimal('10.00'), shipping_cost=Decimal('12.00'),
        tax_amount=Decimal('1.00'), total_amount=Decimal('23.00'), checkout_token=uuid.uuid4(),
    )
    fields.update(kw)
    return Order.objects.create(**fields)


class UrlGuardTests(TestCase):
    def setUp(self):
        self.customer = make_account('cust', ROLE_CUSTOMER)
        self.staff = make_account('stf', ROLE_STAFF)
        self.admin = make_account('adm', ROLE_ADMIN)
        self.category = Category.objects.create(name='Masks')
        self.product = Product.objects.create(sku='M-1', name='Mask', unit_price=Decimal('10.00'),
                                              stock_quantity=5, category=self.category)
        self.address = Address.objects.create(
            account=self.customer, address_type='SHIPPING', line1='1 Reef Rd', city='Toronto',
            region='ON', postal_code='M5V 1A1', country='CA')
        self.customer_order = make_order(account=self.customer)
        self.guest_order = make_order()
        self.confirmed = make_order()
        pay = Payment.objects.create(order=self.confirmed, amount=Decimal('23.00'),
                                     method_type='CREDIT_CARD', token='tok_ok', last4='4242',
                                     status='CAPTURED')
        Order.objects.filter(pk=self.confirmed.pk).update(status='CONFIRMED', confirmed_payment=pay)
        Carrier.objects.create(name='UPS')

    def url_for(self, name):
        args = {
            'accounts:address_edit': [self.address.pk],
            'accounts:address_delete': [self.address.pk],
            'products:detail': [self.product.pk],
            'products:product_edit': [self.product.pk],
            'products:category_edit': [self.category.pk],
            'cart:add': [self.product.pk],
            'cart:update': [self.product.pk],
            'orders:detail': [self.customer_order.pk],
            'orders:guest_detail': [self.guest_order.pk, guest_order_key(self.guest_order)],
            'orders:staff_detail': [self.confirmed.pk],
            'orders:staff_mark_shipped': [self.confirmed.pk],
            'refunds:request': [self.customer_order.pk],
        }.get(name, [])
        return reverse(name, args=args)

    def client_for(self, account):
        client = Client(raise_request_exception=False)
        if account is not None:
            session = client.session
            session['account_id'] = account.account_id
            session.save()
        return client

    def hit(self, name, account):
        client = self.client_for(account)
        url = self.url_for(name)
        if name in POST_ONLY:
            return client.post(url, {})
        return client.get(url)

    def assert_login_redirect(self, r, label):
        self.assertEqual(r.status_code, 302, label)
        self.assertEqual(r['Location'], LOGIN_URL, label)

    def assert_allowed(self, r, label):
        self.assertNotEqual(r.status_code, 403, label)
        self.assertNotEqual(r.status_code, 500, label)
        if r.status_code == 302:
            self.assertNotEqual(r['Location'], LOGIN_URL, label)

    def test_every_url_is_classified(self):
        unclassified = sorted(set(all_url_names()) - set(POLICY))
        self.assertEqual(unclassified, [], 'new URL(s) without an access decision in POLICY')
        stale = sorted(set(POLICY) - set(all_url_names()))
        self.assertEqual(stale, [], 'POLICY lists URL(s) that no longer exist')

    def test_role_matrix(self):
        roles = {'anonymous': None, 'customer': self.customer, 'staff': self.staff,
                 'admin': self.admin}
        expect = {
            # role -> 'login' | 'unauthorized' | 'forbid' | 'allow'
            PUBLIC: {'anonymous': 'allow', 'customer': 'allow'},
            STOREFRONT: {'anonymous': 'allow', 'customer': 'allow', 'staff': 'forbid',
                         'admin': 'forbid'},
            LOGIN: {'anonymous': 'login', 'customer': 'allow'},
            STAFF: {'anonymous': 'login', 'customer': 'forbid', 'staff': 'allow', 'admin': 'allow'},
            ADMIN: {'anonymous': 'login', 'customer': 'forbid', 'staff': 'forbid', 'admin': 'allow'},
            ANY_POST: {},
            API_LOGIN: {'anonymous': 'unauthorized', 'customer': 'allow', 'staff': 'allow',
                        'admin': 'allow'},
        }
        for name in all_url_names():
            for role, outcome in expect[POLICY.get(name, PUBLIC)].items():
                with self.subTest(url=name, role=role):
                    r = self.hit(name, roles[role])
                    label = f'{name} as {role} -> {r.status_code}'
                    if outcome == 'login':
                        self.assert_login_redirect(r, label)
                    elif outcome == 'unauthorized':
                        self.assertEqual(r.status_code, 401, label)
                    elif outcome == 'forbid':
                        self.assertEqual(r.status_code, 403, label)
                    else:
                        self.assert_allowed(r, label)

    def test_guarded_post_by_anonymous_redirects_to_login_for_every_non_public_url(self):
        # a POST must hit the same guard as a GET (no method-specific bypass)
        for name, policy in POLICY.items():
            if policy not in (LOGIN, STAFF, ADMIN):
                continue
            with self.subTest(url=name):
                r = self.client_for(None).post(self.url_for(name), {})
                self.assert_login_redirect(r, f'{name} POST anonymous -> {r.status_code}')

    def test_wrong_role_post_is_forbidden_for_staff_and_admin_urls(self):
        for name, policy in POLICY.items():
            if policy == STAFF:
                wrong = [self.customer]
            elif policy == ADMIN:
                wrong = [self.customer, self.staff]
            elif policy == STOREFRONT:
                wrong = [self.staff, self.admin]
            else:
                continue
            for account in wrong:
                with self.subTest(url=name, role=account.account_type):
                    r = self.client_for(account).post(self.url_for(name), {})
                    self.assertEqual(r.status_code, 403, f'{name} POST as {account.account_type}')
        # nothing changed by any of the forbidden POSTs
        self.confirmed.refresh_from_db()
        self.assertEqual(self.confirmed.status, 'CONFIRMED')
        self.assertTrue(Address.objects.filter(pk=self.address.pk).exists())
        self.assertEqual(Product.objects.count(), 1)
