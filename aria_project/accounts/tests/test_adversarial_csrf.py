"""CSRF and HTTP-method checks on every state-changing view.

The default test client skips CSRF checks, so the rest of the suite can't notice a view
that was made csrf_exempt. These tests use enforce_csrf_checks=True: a forged cross-site
POST (no token) must be rejected with 403 and change nothing.
State-changing endpoints the plans define as POST only must refuse GET with 405.
"""
import uuid
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account, Address, Profile
from orders.models import Carrier, Order
from payments.models import Payment
from products.models import Category, InventoryMovement, Product


def make_account(username, role=ROLE_CUSTOMER):
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


def confirmed_order():
    order = make_order()
    pay = Payment.objects.create(order=order, amount=Decimal('23.00'), method_type='CREDIT_CARD',
                                 token='tok_ok', last4='4242', status='CAPTURED')
    Order.objects.filter(pk=order.pk).update(status='CONFIRMED', confirmed_payment=pay)
    order.refresh_from_db()
    return order


def csrf_client(account=None):
    client = Client(enforce_csrf_checks=True, raise_request_exception=False)
    if account is not None:
        session = client.session
        session['account_id'] = account.account_id
        session.save()
    return client


ADDRESS = {'address_type': 'SHIPPING', 'line1': '9 Forged St', 'line2': '', 'city': 'Victoria',
           'region': 'BC', 'postal_code': 'V8W 1A1', 'country': 'CA'}


class CsrfEnforcementTests(TestCase):
    def setUp(self):
        self.customer = make_account('cust')
        self.staff = make_account('stf', ROLE_STAFF)
        self.admin = make_account('adm', ROLE_ADMIN)
        self.product = Product.objects.create(sku='M-1', name='Mask', unit_price=Decimal('10.00'),
                                              stock_quantity=5)
        self.category = Category.objects.create(name='Masks')
        self.address = Address.objects.create(account=self.customer, **{**ADDRESS, 'line1': '1 Mine St'})
        self.order = confirmed_order()
        self.carrier = Carrier.objects.create(name='UPS')

    def assert_forbidden(self, response, label):
        self.assertEqual(response.status_code, 403, label)

    def test_customer_and_guest_forms_reject_post_without_csrf_token(self):
        cases = [
            (None, reverse('cart:add', args=[self.product.pk]), {'quantity': 1}),
            (None, reverse('cart:update', args=[self.product.pk]), {'quantity': 3}),
            (None, reverse('cart:checkout'), {'checkout_token': str(uuid.uuid4())}),
            (None, reverse('orders:lookup'), {'order_number': self.order.pk,
                                              'email': 'guest@example.com'}),
            (None, reverse('accounts:register'), {'username': 'forged', 'password': 'pw-123456-x',
                                                  'confirm_password': 'pw-123456-x'}),
            (None, reverse('accounts:login'), {'username': 'cust', 'password': 'x'}),
            (self.customer, reverse('accounts:address_create'), ADDRESS),
            (self.customer, reverse('accounts:address_edit', args=[self.address.pk]),
             {**ADDRESS, 'line1': 'Hijacked'}),
            (self.customer, reverse('accounts:address_delete', args=[self.address.pk]), {}),
            (self.customer, reverse('accounts:update_profile'),
             {'first_name': 'Forged', 'last_name': 'X', 'email': 'forged@example.com'}),
            (self.customer, reverse('accounts:logout'), {}),
        ]
        for account, url, data in cases:
            with self.subTest(url=url):
                self.assert_forbidden(csrf_client(account).post(url, data), url)
        self.assertFalse(Account.objects.filter(username='forged').exists())
        self.address.refresh_from_db()
        self.assertEqual(self.address.line1, '1 Mine St')
        self.assertEqual(Address.objects.filter(account=self.customer).count(), 1)
        self.assertFalse(Profile.objects.exists())

    def test_staff_mark_shipped_rejects_post_without_csrf_token(self):
        r = csrf_client(self.staff).post(
            reverse('orders:staff_mark_shipped', args=[self.order.pk]),
            {'carrier': self.carrier.pk, 'tracking_number': 'FORGED1'})
        self.assert_forbidden(r, 'mark shipped')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CONFIRMED')
        self.assertIsNone(self.order.tracking_number)

    def test_admin_product_forms_reject_post_without_csrf_token(self):
        product_data = {'sku': 'FORGED-1', 'name': 'Forged', 'description': '', 'category': '',
                        'unit_price': '0.01', 'currency': 'CAD', 'stock_quantity': '999',
                        'reorder_level': '1', 'is_active': 'on', 'original_stock': '5',
                        'inventory_reason': 'ADJUSTMENT'}
        cases = [
            (reverse('products:product_create'), product_data),
            (reverse('products:product_edit', args=[self.product.pk]), product_data),
            (reverse('products:category_create'), {'name': 'Forged'}),
            (reverse('products:category_edit', args=[self.category.pk]), {'name': 'Forged'}),
        ]
        for url, data in cases:
            with self.subTest(url=url):
                self.assert_forbidden(csrf_client(self.admin).post(url, data), url)
        self.product.refresh_from_db()
        self.category.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)
        self.assertEqual(self.product.name, 'Mask')
        self.assertEqual(self.category.name, 'Masks')
        self.assertFalse(Product.objects.filter(sku='FORGED-1').exists())
        self.assertFalse(InventoryMovement.objects.exists())


class PostOnlyTests(TestCase):
    """State-changing endpoints must not act on GET (a link or <img> could trigger them)."""

    def setUp(self):
        self.customer = make_account('cust')
        self.staff = make_account('stf', ROLE_STAFF)
        self.product = Product.objects.create(sku='M-1', name='Mask', unit_price=Decimal('10.00'),
                                              stock_quantity=5)
        self.address = Address.objects.create(account=self.customer, **ADDRESS)
        self.order = confirmed_order()
        Carrier.objects.create(name='UPS')

    def login(self, account):
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

    def test_get_on_state_changing_endpoints_is_405_and_changes_nothing(self):
        self.login(self.customer)
        cases = [
            reverse('cart:add', args=[self.product.pk]) + '?quantity=3',
            reverse('cart:update', args=[self.product.pk]) + '?quantity=3',
            reverse('accounts:address_delete', args=[self.address.pk]),
            reverse('accounts:logout'),
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertFalse(self.client.session.get('cart'))
        self.assertIn('account_id', self.client.session)
        self.assertTrue(Address.objects.filter(pk=self.address.pk).exists())

        self.client.logout()
        self.login(self.staff)
        url = reverse('orders:staff_mark_shipped', args=[self.order.pk]) + '?carrier=1&tracking_number=X'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CONFIRMED')

    def test_checkout_get_never_places_an_order(self):
        self.client.post(reverse('cart:add', args=[self.product.pk]), {'quantity': 1})
        params = {'contact_name': 'Gina', 'contact_email': 'gina@example.com',
                  'ship-line1': '1 Reef Rd', 'ship-city': 'Toronto', 'ship-region': 'ON',
                  'ship-postal_code': 'M5V 1A1', 'ship-country': 'CA', 'billing_same': 'on',
                  'shipping_method': 'STANDARD', 'test_card': 'visa_ok',
                  'checkout_token': str(uuid.uuid4()), 'expected_total': '23.56'}
        r = self.client.get(reverse('cart:checkout'), params)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.filter(account__isnull=True,
                                              contact_email='gina@example.com').exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_admin_product_edit_get_changes_nothing(self):
        admin = make_account('adm', ROLE_ADMIN)
        self.login(admin)
        url = reverse('products:product_edit', args=[self.product.pk])
        r = self.client.get(url, {'stock_quantity': '0', 'name': 'Renamed', 'original_stock': '5',
                                  'inventory_reason': 'ADJUSTMENT', 'sku': 'M-1',
                                  'unit_price': '1.00', 'currency': 'CAD', 'reorder_level': '1'})
        self.assertEqual(r.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)
        self.assertEqual(self.product.name, 'Mask')
        self.assertFalse(InventoryMovement.objects.exists())
