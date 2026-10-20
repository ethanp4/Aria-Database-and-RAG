import re
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account, Address, Profile
from orders.links import guest_order_url
from orders.models import Order
from products.models import Product

CHECKOUT = reverse('cart:checkout')
TOKEN_RE = re.compile(r'name="checkout_token" value="([0-9a-f-]{36})"')
DECLINED = 'Your payment didn&#x27;t go through. You have not been charged.'
PAYMENT_FAILED = ('We couldn&#x27;t confirm your payment. If you see a charge, it will be '
                  'reversed — contact us if it isn&#x27;t.')
PROCESSING = 'Your order is being processed. Refresh this page in a moment.'

# one 50.00 item, Standard 12.00, ON HST 13% on goods + shipping: 62.00 + 8.06
TOTAL = '70.06'


def make_account(username, role=ROLE_CUSTOMER):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def make_address(account, address_type=Address.AddressType.SHIPPING, region='ON', default=True, **kw):
    fields = dict(account=account, address_type=address_type, line1='1 Reef Rd', city='Toronto',
                  region=region, postal_code='M5V 1A1', country='CA', is_default=default)
    fields.update(kw)
    return Address.objects.create(**fields)


def login(client, account):
    session = client.session
    session['account_id'] = account.account_id
    session.save()


def guest_data(token, total=TOTAL, **over):
    data = {
        'contact_name': 'Gina Guest', 'contact_email': 'gina@example.com',
        'ship-line1': '1 Reef Rd', 'ship-line2': '', 'ship-city': 'Toronto', 'ship-region': 'ON',
        'ship-postal_code': 'M5V 1A1', 'ship-country': 'CA',
        'billing_same': 'on', 'shipping_method': 'STANDARD', 'test_card': 'visa_ok',
        'checkout_token': token, 'expected_total': total,
    }
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def customer_data(token, shipping_address, total=TOTAL, **over):
    data = {
        'shipping_address': shipping_address.pk, 'billing_same': 'on',
        'shipping_method': 'STANDARD', 'test_card': 'visa_ok',
        'checkout_token': token, 'expected_total': total,
    }
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


class CheckoutTests(TestCase):
    def setUp(self):
        self.mask = Product.objects.create(sku='MASK-1', name='Mask', unit_price=Decimal('50.00'),
                                           stock_quantity=5)
        self.alice = make_account('alice')
        Profile.objects.create(account=self.alice, first_name='Alice', last_name='Diver',
                               email='alice@example.com')
        self.alice_ship = make_address(self.alice)

    def add_to_cart(self, qty=1):
        self.client.post(reverse('cart:add', args=[self.mask.pk]), {'quantity': qty})

    def token_from(self, response):
        return TOKEN_RE.search(response.content.decode()).group(1)

    def test_checkout_get_renders_token_test_cards_and_quote(self):
        login(self.client, self.alice)
        self.add_to_cart()
        r = self.client.get(CHECKOUT)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        uuid.UUID(self.token_from(r))
        self.assertContains(r, 'Test payments: no real card is charged.')
        self.assertContains(r, 'Visa •••• 4242 (approves)')
        self.assertContains(r, 'Visa •••• 0002 (declined)')
        self.assertContains(r, TOTAL)
        self.assertContains(r, '8.06')
        self.assertNotIn('tok_', html)
        # a fresh token per page view
        self.assertNotEqual(self.token_from(self.client.get(CHECKOUT)), self.token_from(r))

    def test_guest_get_shows_login_link(self):
        self.add_to_cart()
        r = self.client.get(CHECKOUT)
        self.assertContains(r, 'Have an account?')
        self.assertContains(r, reverse('accounts:login'))
        self.assertContains(r, reverse('accounts:register'))

    def test_get_with_query_params_does_not_echo_guest_fields(self):
        self.add_to_cart()
        r = self.client.get(CHECKOUT, {'contact_name': 'Gina Guest', 'contact_email': 'gina@example.com',
                                       'ship-line1': '77 Leak St', 'ship-country': 'CA',
                                       'ship-region': 'ON', 'update': '1', 'action': 'update'})
        self.assertEqual(r.status_code, 200)
        for value in ('Gina Guest', 'gina@example.com', '77 Leak St', TOTAL):
            self.assertNotContains(r, value)

    def test_update_totals_button_posts_and_never_uses_a_get_form(self):
        self.add_to_cart()
        html = self.client.get(CHECKOUT).content.decode()
        self.assertNotIn('formmethod="get"', html)
        self.assertRegex(html, r'<button[^>]*name="action" value="update"[^>]*formnovalidate')

    def test_update_totals_post_requotes_without_placing_order(self):
        self.add_to_cart()
        token = str(uuid.uuid4())
        # incomplete guest form: no name or email yet
        data = guest_data(token, total='', contact_name='', contact_email='',
                          shipping_method='EXPRESS', **{'ship-region': 'bc'})
        data['action'] = 'update'
        with patch('cart.views.place_order') as placed, \
                patch('payments.gateway.FakeGateway.authorize') as authorize:
            r = self.client.post(CHECKOUT, data)
        placed.assert_not_called()
        authorize.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())
        # BC 12% on 50.00 + 20.00 express = 78.40
        self.assertContains(r, 'name="expected_total" value="78.40"')
        self.assertEqual(self.token_from(r), token)
        self.assertNotContains(r, 'This field is required')
        # the normal submit with the re-quoted total places the order
        data = guest_data(token, total='78.40', shipping_method='EXPRESS', **{'ship-region': 'bc'})
        r = self.client.post(CHECKOUT, data)
        order = Order.objects.get()
        self.assertEqual(order.total_amount, Decimal('78.40'))
        self.assertEqual(r.url, guest_order_url(order))

    def test_empty_cart_redirects_to_cart(self):
        self.assertRedirects(self.client.get(CHECKOUT), reverse('cart:detail'))

    def test_guest_checkout_success_redirects_to_private_link_clears_cart_and_emails(self):
        self.add_to_cart()
        token = str(uuid.uuid4())
        r = self.client.post(CHECKOUT, guest_data(token))
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertIsNone(order.account)
        self.assertEqual(order.contact_email, 'gina@example.com')
        self.assertRedirects(r, guest_order_url(order), fetch_redirect_response=False)
        self.assertFalse(self.client.session.get('cart'))
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('http://testserver' + guest_order_url(order), body)
        self.assertNotIn('tok_', body)
        self.assertIn('•••• 4242', body)
        self.assertNotRegex(body.replace('•••• 4242', ''), r'4242')
        page = self.client.get(r.url)
        self.assertContains(page, f'Order #{order.pk} confirmed.')

    def test_customer_checkout_success_redirects_to_order_detail(self):
        login(self.client, self.alice)
        self.add_to_cart()
        r = self.client.post(CHECKOUT, customer_data(str(uuid.uuid4()), self.alice_ship))
        order = Order.objects.get()
        self.assertEqual(order.account, self.alice)
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(order.contact_name, 'Alice Diver')
        self.assertEqual(order.bill_line1, '1 Reef Rd')
        self.assertRedirects(r, reverse('orders:detail', args=[order.pk]), fetch_redirect_response=False)
        self.assertFalse(self.client.session.get('cart'))
        self.assertEqual([m.to for m in mail.outbox], [['alice@example.com']])
        self.assertContains(self.client.get(r.url), f'Order #{order.pk} confirmed.')

    def test_customer_without_profile_checks_out_with_username(self):
        bob = make_account('bob')
        login(self.client, bob)
        ship = make_address(bob)
        self.add_to_cart()
        self.client.post(CHECKOUT, customer_data(str(uuid.uuid4()), ship))
        order = Order.objects.get()
        self.assertEqual(order.contact_name, 'bob')
        self.assertIsNone(order.contact_email)
        self.assertEqual(len(mail.outbox), 0)

    def test_guest_checkout_requires_name_email_and_valid_address(self):
        self.add_to_cart()
        cases = {
            'name': {'contact_name': '   '},
            'email': {'contact_email': '   '},
            'region': {'ship-region': 'ZZ'},
            'city': {'ship-city': ''},
            'billing': {'billing_same': None, 'bill-line1': ''},
        }
        for label, over in cases.items():
            with self.subTest(label):
                r = self.client.post(CHECKOUT, guest_data(str(uuid.uuid4()), **over))
                self.assertEqual(r.status_code, 200)
                self.assertFalse(Order.objects.exists())
        r = self.client.post(CHECKOUT, guest_data(str(uuid.uuid4()), **{'ship-region': 'ZZ'}))
        self.assertContains(r, 'Use the 2-letter province or state code')

    def test_checkout_declined_rerenders_with_message_and_keeps_cart(self):
        self.add_to_cart()
        token = str(uuid.uuid4())
        r = self.client.post(CHECKOUT, guest_data(token, test_card='visa_decline'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, DECLINED)
        self.assertNotContains(r, PAYMENT_FAILED)
        self.assertNotEqual(self.token_from(r), token)
        self.assertEqual(self.client.session['cart'], {str(self.mask.pk): 1})
        self.assertFalse(Order.objects.filter(status=Order.Status.CONFIRMED).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_capture_timeout_rerenders_with_message(self):
        self.add_to_cart()
        r = self.client.post(CHECKOUT, guest_data(str(uuid.uuid4()), test_card='visa_timeout'))
        # a capture timeout may have moved money once a real gateway is used
        self.assertContains(r, PAYMENT_FAILED)
        self.assertNotContains(r, DECLINED)
        self.assertEqual(self.client.session['cart'], {str(self.mask.pk): 1})
        self.mask.refresh_from_db()
        self.assertEqual(self.mask.stock_quantity, 5)

    def test_replayed_failed_token_redirects_without_clearing_cart(self):
        self.add_to_cart()
        token = str(uuid.uuid4())
        self.client.post(CHECKOUT, guest_data(token, test_card='visa_decline'))
        r = self.client.post(CHECKOUT, guest_data(token))
        order = Order.objects.get()
        self.assertRedirects(r, guest_order_url(order))
        self.assertEqual(self.client.session['cart'], {str(self.mask.pk): 1})
        self.assertEqual(Order.objects.count(), 1)

    def test_checkout_out_of_stock_redirects_to_cart_with_message(self):
        self.add_to_cart()
        Product.objects.filter(pk=self.mask.pk).update(stock_quantity=0)
        r = self.client.post(CHECKOUT, guest_data(str(uuid.uuid4())), follow=True)
        self.assertRedirects(r, reverse('cart:detail'))
        self.assertContains(r, 'Sorry, Mask sold out before your order completed. You have not been charged.')
        self.assertFalse(Order.objects.filter(status=Order.Status.CONFIRMED).exists())

    def test_price_change_since_checkout_page_blocks_order(self):
        login(self.client, self.alice)
        self.add_to_cart()
        page = self.client.get(CHECKOUT)
        token = self.token_from(page)
        self.assertContains(page, TOTAL)
        Product.objects.filter(pk=self.mask.pk).update(unit_price=Decimal('60.00'))
        r = self.client.post(CHECKOUT, customer_data(token, self.alice_ship))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())
        self.assertContains(r, 'Prices or totals changed. Please review and submit again.')
        # 72.00 + 13% = 81.36
        self.assertContains(r, '81.36')
        self.assertContains(r, 'name="expected_total" value="81.36"')
        # submitting again with the new total goes through
        r = self.client.post(CHECKOUT, customer_data(token, self.alice_ship, total='81.36'))
        self.assertEqual(Order.objects.get().total_amount, Decimal('81.36'))

    def test_missing_expected_total_asks_for_review(self):
        self.add_to_cart()
        r = self.client.post(CHECKOUT, guest_data(str(uuid.uuid4()), total=''))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())
        self.assertContains(r, 'name="expected_total" value="70.06"')

    def test_checkout_rejects_other_customers_or_wrong_type_address(self):
        bob = make_account('bob')
        bob_ship = make_address(bob)
        alice_bill = make_address(self.alice, Address.AddressType.BILLING)
        login(self.client, self.alice)
        self.add_to_cart()
        cases = {
            'other customer shipping': customer_data(str(uuid.uuid4()), bob_ship),
            'billing as shipping': customer_data(str(uuid.uuid4()), alice_bill),
            'other customer billing': customer_data(str(uuid.uuid4()), self.alice_ship,
                                                    billing_same=None, billing_address=bob_ship.pk),
        }
        for label, data in cases.items():
            with self.subTest(label):
                r = self.client.post(CHECKOUT, data)
                self.assertEqual(r.status_code, 200)
                self.assertFalse(Order.objects.exists())
        # the other customer's address is never offered
        self.assertNotContains(self.client.get(CHECKOUT), f'value="{bob_ship.pk}"')

    def test_customer_billing_may_be_any_own_address(self):
        alice_bill = make_address(self.alice, Address.AddressType.BILLING, line1='9 Bill St')
        login(self.client, self.alice)
        self.add_to_cart()
        self.client.post(CHECKOUT, customer_data(str(uuid.uuid4()), self.alice_ship,
                                                 billing_same=None, billing_address=alice_bill.pk))
        self.assertEqual(Order.objects.get().bill_line1, '9 Bill St')

    def test_customer_address_with_bad_region_shows_edit_message(self):
        carl = make_account('carl')
        bad = make_address(carl, region='Ontario')
        login(self.client, carl)
        self.add_to_cart()
        r = self.client.get(CHECKOUT)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse('accounts:address_list'))
        r = self.client.post(CHECKOUT, customer_data(str(uuid.uuid4()), bad))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "calculate tax")
        self.assertFalse(Order.objects.exists())

    def test_customer_without_shipping_address_gets_add_link(self):
        dan = make_account('dan')
        login(self.client, dan)
        self.add_to_cart()
        r = self.client.get(CHECKOUT)
        self.assertContains(r, reverse('accounts:address_create'))

    def test_checkout_double_post_same_token_creates_one_order_and_one_email(self):
        self.add_to_cart()
        data = guest_data(str(uuid.uuid4()))
        r1 = self.client.post(CHECKOUT, data)
        r2 = self.client.post(CHECKOUT, data)
        order = Order.objects.get()
        self.assertEqual(r1.url, guest_order_url(order))
        self.assertEqual(r2.url, guest_order_url(order))
        self.assertEqual(len(mail.outbox), 1)
        self.mask.refresh_from_db()
        self.assertEqual(self.mask.stock_quantity, 4)

    # back button to an old, already-confirmed checkout page must not wipe a new cart
    def test_replayed_confirmed_token_keeps_new_cart(self):
        for who in ('customer', 'guest'):
            with self.subTest(who):
                if who == 'customer':
                    login(self.client, self.alice)
                    data = customer_data(str(uuid.uuid4()), self.alice_ship)
                else:
                    self.client.logout()
                    data = guest_data(str(uuid.uuid4()))
                orders_before = Order.objects.count()
                mail.outbox = []
                self.add_to_cart()
                self.client.post(CHECKOUT, data)
                self.assertFalse(self.client.session.get('cart'))
                self.add_to_cart(2)
                r = self.client.post(CHECKOUT, data)
                order = Order.objects.get(checkout_token=data['checkout_token'])
                self.assertEqual(r.status_code, 302)
                self.assertEqual(self.client.session['cart'], {str(self.mask.pk): 2})
                self.assertEqual(Order.objects.count(), orders_before + 1)
                self.assertEqual(len(mail.outbox), 1)
                self.assertEqual(order.status, Order.Status.CONFIRMED)

    # a concurrent double submit can return an order the other request is still placing
    def test_replay_of_order_still_pending_shows_processing_message(self):
        for who in ('customer', 'guest'):
            with self.subTest(who):
                if who == 'customer':
                    login(self.client, self.alice)
                    data = customer_data(str(uuid.uuid4()), self.alice_ship)
                else:
                    self.client.logout()
                    data = guest_data(str(uuid.uuid4()))
                self.add_to_cart()
                self.client.post(CHECKOUT, data, follow=True)  # consumes the confirmed flash
                order = Order.objects.get(checkout_token=data['checkout_token'])
                Order.objects.filter(pk=order.pk).update(
                    status=Order.Status.PENDING_PAYMENT, confirmed_payment=None)
                self.add_to_cart()
                r = self.client.post(CHECKOUT, data, follow=True)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, PROCESSING)
                self.assertNotContains(r, f'Order #{order.pk} confirmed.')
                self.assertEqual(self.client.session['cart'], {str(self.mask.pk): 1})

    def test_other_owners_token_is_404(self):
        login(self.client, self.alice)
        self.add_to_cart()
        token = str(uuid.uuid4())
        self.client.post(CHECKOUT, customer_data(token, self.alice_ship))
        self.client.logout()
        self.add_to_cart()
        r = self.client.post(CHECKOUT, guest_data(token))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Order.objects.count(), 1)

    def test_staff_and_admin_get_403_on_checkout(self):
        for role in (ROLE_STAFF, ROLE_ADMIN):
            with self.subTest(role=role):
                login(self.client, make_account(role + 'x', role))
                self.assertEqual(self.client.get(CHECKOUT).status_code, 403)
                r = self.client.post(CHECKOUT, guest_data(str(uuid.uuid4())))
                self.assertEqual(r.status_code, 403)
        self.assertFalse(Order.objects.exists())
