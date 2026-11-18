"""Adversarial checkout and order tests, grouped by the CLAUDE.md invariant they attack.

Assertions use DB state, status codes, response context and the message strings defined
in the views, never template markup: templates are being restyled independently.
"""
import logging
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core import mail
from django.db import DatabaseError, IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import ROLE_STAFF, Account, Address, Profile
from cart.cart import SESSION_KEY, CartLine
from cart.views import MSG_DECLINED, MSG_PAYMENT_FAILED, MSG_TOTALS_CHANGED
from orders.links import guest_order_key, guest_order_url
from orders.models import Order, OrderItem
from orders.pricing import quote
from orders.services import AddressData, Contact, place_order
from orders.views import LOOKUP_MISS
from payments.gateway import FakeGateway, GatewayTimeout
from payments.models import Payment
from products.models import InventoryMovement, Product

CHECKOUT = reverse('cart:checkout')
LOOKUP = reverse('orders:lookup')
ON = AddressData('1 Reef Rd', None, 'Toronto', 'ON', 'M5V 1A1', 'CA')
# Luhn-valid test PAN; it must never be stored, logged or rendered anywhere
FULL_PAN = '4111111111111111'


def make_account(username, role='user'):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def login(client, account):
    session = client.session
    session['account_id'] = account.account_id
    session.save()


def total_for(subtotal, method='STANDARD', country='CA', region='ON'):
    return str(quote(Decimal(subtotal), method, country, region).total)


def guest_data(token, total, /, **over):
    data = {
        'contact_name': 'Gina Guest', 'contact_email': 'gina@example.com',
        'ship-line1': '1 Reef Rd', 'ship-line2': '', 'ship-city': 'Toronto', 'ship-region': 'ON',
        'ship-postal_code': 'M5V 1A1', 'ship-country': 'CA',
        'billing_same': 'on', 'shipping_method': 'STANDARD', 'test_card': 'visa_ok',
        'checkout_token': str(token), 'expected_total': total,
    }
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def customer_data(token, address, total, /, **over):
    data = {
        'shipping_address': address.pk, 'billing_same': 'on', 'shipping_method': 'STANDARD',
        'test_card': 'visa_ok', 'checkout_token': str(token), 'expected_total': total,
    }
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def flashes(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def set_cart(client, items):
    session = client.session
    session[SESSION_KEY] = items
    session.save()


@contextmanager
def capture_all_logs():
    records = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    root = logging.getLogger()
    handler, old_level = Grab(level=logging.DEBUG), root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


class AuthorizeRaisesGateway(FakeGateway):
    def authorize(self, token, amount):
        self._record('authorize', token)
        raise RuntimeError('socket closed')


class AuthorizeTimeoutGateway(FakeGateway):
    def authorize(self, token, amount):
        self._record('authorize', token)
        raise GatewayTimeout('no answer')


class CaptureDeclinedGateway(FakeGateway):
    def capture(self, ref):
        self._record('capture', ref)
        from payments.gateway import GatewayResult
        return GatewayResult(ok=False, ref=ref, error='capture_rejected')


class CheckoutBase(TestCase):
    """Patches the gateway with one shared FakeGateway so its calls can be counted."""
    gateway_class = FakeGateway

    def setUp(self):
        self.gw = self.gateway_class()
        patcher = patch('orders.services.get_gateway', return_value=self.gw)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mask = Product.objects.create(sku='MASK-1', name='Mask', unit_price=Decimal('50.00'),
                                           stock_quantity=5)
        self.fins = Product.objects.create(sku='FINS-1', name='Fins', unit_price=Decimal('30.00'),
                                           stock_quantity=3)
        self.alice = make_account('alice')
        Profile.objects.create(account=self.alice, first_name='Alice', last_name='Diver',
                               email='alice@example.com')
        self.alice_ship = Address.objects.create(
            account=self.alice, address_type=Address.AddressType.SHIPPING, line1='1 Reef Rd',
            city='Toronto', region='ON', postal_code='M5V 1A1', country='CA', is_default=True)

    def add(self, product, qty=1, client=None):
        (client or self.client).post(reverse('cart:add', args=[product.pk]), {'quantity': qty})

    # token and total the customer is shown; a guest presses "Update totals" to get a quote
    def checkout_token(self, client=None):
        client = client or self.client
        r = client.get(CHECKOUT)
        self.assertEqual(r.status_code, 200)
        token, q = r.context['form'].initial['checkout_token'], r.context['quote']
        if q is None:
            r = client.post(CHECKOUT, guest_data(token, '', action='update'))
            q = r.context['quote']
        return token, str(q.total)

    def calls(self, action):
        return [v for a, v in self.gw.calls if a == action]

    def stock(self, product):
        product.refresh_from_db()
        return product.stock_quantity

    def assert_not_confirmed(self, response):
        self.assertFalse(Order.objects.filter(status=Order.Status.CONFIRMED).exists())
        self.assertFalse(Payment.objects.filter(status=Payment.Status.CAPTURED).exists())
        self.assertFalse(any('confirmed' in m.lower() for m in flashes(response)))
        self.assertEqual(len(mail.outbox), 0)


# --- invariant 1: an order is never "Confirmed" unless payment succeeded ---------------------

class NeverConfirmedWithoutPaymentTests(CheckoutBase):
    def test_declined_card_leaves_order_unconfirmed_everywhere_the_customer_looks(self):
        login(self.client, self.alice)
        self.add(self.mask)
        token, total = self.checkout_token()
        r = self.client.post(CHECKOUT, customer_data(token, self.alice_ship, total,
                                                     test_card='visa_decline'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['error'], MSG_DECLINED)
        self.assert_not_confirmed(r)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertIsNone(order.confirmed_payment)
        self.assertIsNone(order.confirmed_at)
        self.assertEqual(Payment.objects.get().status, Payment.Status.DECLINED)
        self.assertEqual(self.calls('capture'), [])
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(self.client.session[SESSION_KEY], {str(self.mask.pk): 1})
        # the order pages the customer can reach report it as failed
        detail = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertEqual(detail.context['order'].status, Order.Status.PAYMENT_FAILED)
        self.assertEqual(detail.context['payment_display'], '')
        history = self.client.get(reverse('orders:history'))
        self.assertEqual([o.status for o in history.context['page_obj']], [Order.Status.PAYMENT_FAILED])

    def test_capture_failures_leave_order_unconfirmed_stock_restored_and_auth_voided(self):
        cases = {
            'capture timeout': (FakeGateway, 'visa_timeout'),
            'capture rejected': (CaptureDeclinedGateway, 'visa_ok'),
        }
        for label, (gw_class, card) in cases.items():
            with self.subTest(label):
                self.gw = gw_class()
                with patch('orders.services.get_gateway', return_value=self.gw):
                    self.add(self.mask)
                    token, total = self.checkout_token()
                    r = self.client.post(CHECKOUT, guest_data(token, total, test_card=card))
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.context['error'], MSG_PAYMENT_FAILED)
                self.assert_not_confirmed(r)
                order = Order.objects.get(checkout_token=token)
                self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
                self.assertEqual(Payment.objects.get(order=order).status, Payment.Status.FAILED)
                self.assertEqual(len(self.calls('void')), 1)
                self.assertEqual(self.stock(self.mask), 5)
                self.assertFalse(InventoryMovement.objects.exists())
                # a fresh token is issued so the next submit is a new attempt, not a replay
                self.assertNotEqual(r.context['form']['checkout_token'].value(), str(token))

    def test_authorize_timeout_is_reported_as_unknown_outcome_not_confirmed(self):
        self.gw = AuthorizeTimeoutGateway()
        with patch('orders.services.get_gateway', return_value=self.gw):
            self.add(self.mask)
            token, total = self.checkout_token()
            r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertEqual(r.context['error'], MSG_PAYMENT_FAILED)
        self.assert_not_confirmed(r)
        self.assertEqual(Order.objects.get().status, Order.Status.PAYMENT_FAILED)
        self.assertEqual(Payment.objects.get().status, Payment.Status.FAILED)

    def test_unexpected_gateway_exception_never_confirms(self):
        self.gw = AuthorizeRaisesGateway()
        client = Client(raise_request_exception=False)
        with patch('orders.services.get_gateway', return_value=self.gw):
            self.add(self.mask, client=client)
            token, total = self.checkout_token(client)
            with self.assertLogs('django.request', 'ERROR'):
                r = client.post(CHECKOUT, guest_data(token, total))
        self.assertEqual(r.status_code, 500)
        self.assert_not_confirmed(r)
        self.assertEqual(Order.objects.get().status, Order.Status.PAYMENT_FAILED)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(client.session[SESSION_KEY], {str(self.mask.pk): 1})

    def test_db_error_mid_flow_rolls_back_stock_and_voids(self):
        login(self.client, self.alice)
        self.add(self.mask, 2)
        token, total = self.checkout_token()
        client = self.client
        client.raise_request_exception = False
        with patch.object(InventoryMovement.objects, 'bulk_create', side_effect=DatabaseError('disk full')):
            with self.assertLogs('django.request', 'ERROR'):
                r = client.post(CHECKOUT, customer_data(token, self.alice_ship, total))
        self.assertEqual(r.status_code, 500)
        self.assert_not_confirmed(r)
        self.assertEqual(Order.objects.get().status, Order.Status.PAYMENT_FAILED)
        self.assertEqual(Payment.objects.get().status, Payment.Status.FAILED)
        self.assertEqual(self.calls('capture'), [])
        self.assertEqual(len(self.calls('void')), 1)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(client.session[SESSION_KEY], {str(self.mask.pk): 2})
        # retrying the same (failed) token never re-authorizes or confirms
        r = client.post(CHECKOUT, customer_data(token, self.alice_ship, total))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.calls('authorize')), 1)
        self.assertEqual(Order.objects.get().status, Order.Status.PAYMENT_FAILED)

    def test_db_rejects_confirmed_status_without_a_payment(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, guest_data(token, total, test_card='visa_decline'))
        order = Order.objects.get()
        for status in ('CONFIRMED', 'SHIPPED', 'DELIVERED', 'REFUNDED'):
            with self.subTest(status), self.assertRaises(IntegrityError), transaction.atomic():
                Order.objects.filter(pk=order.pk).update(status=status)


# --- invariant 2: stock is checked and decremented in the confirming transaction --------------

class StockTests(CheckoutBase):
    def assert_movements_explain_stock(self, start):
        for product, initial in start.items():
            moved = sum(m.change_qty for m in InventoryMovement.objects.filter(product=product))
            self.assertEqual(initial + moved, self.stock(product), product.sku)
            self.assertGreaterEqual(self.stock(product), 0, product.sku)

    def test_last_unit_raced_by_two_checkouts_one_wins_loser_not_charged(self):
        Product.objects.filter(pk=self.mask.pk).update(stock_quantity=1)
        a, b = self.client, Client()
        self.add(self.mask, client=a)
        self.add(self.mask, client=b)
        token_a, total = self.checkout_token(a)
        token_b, _ = self.checkout_token(b)  # both saw the item in stock

        ra = a.post(CHECKOUT, guest_data(token_a, total))
        rb = b.post(CHECKOUT, guest_data(token_b, total, contact_email='other@example.com'))

        self.assertEqual(Order.objects.get(checkout_token=token_a).status, Order.Status.CONFIRMED)
        self.assertEqual(ra.status_code, 302)
        loser = Order.objects.get(checkout_token=token_b)
        self.assertEqual(loser.status, Order.Status.OUT_OF_STOCK)
        self.assertIsNone(loser.confirmed_payment)
        self.assertEqual(Payment.objects.get(order=loser).status, Payment.Status.VOIDED)
        self.assertRedirects(rb, reverse('cart:detail'), fetch_redirect_response=False)
        self.assertEqual(flashes(rb), ['Sorry, Mask sold out before your order completed. '
                                       'You have not been charged.'])
        # loser's authorization was released and never captured
        loser_ref = Payment.objects.get(order=loser).gateway_ref
        self.assertIn(loser_ref, self.calls('void'))
        self.assertNotIn(loser_ref, self.calls('capture'))
        self.assertEqual(self.stock(self.mask), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(b.session[SESSION_KEY], {str(self.mask.pk): 1})
        self.assert_movements_explain_stock({self.mask: 1})

    def test_one_short_line_rejects_whole_order_and_touches_no_stock(self):
        self.add(self.mask, 2)
        self.add(self.fins, 1)
        token, total = self.checkout_token()
        Product.objects.filter(pk=self.fins.pk).update(stock_quantity=0)
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertRedirects(r, reverse('cart:detail'), fetch_redirect_response=False)
        self.assertIn('Fins', flashes(r)[0])
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(self.stock(self.fins), 0)
        self.assertFalse(InventoryMovement.objects.exists())
        self.assertEqual(self.calls('capture'), [])
        self.assertEqual(Order.objects.get().status, Order.Status.OUT_OF_STOCK)

    def test_session_quantity_above_stock_cannot_drive_stock_negative(self):
        # tampered session: 99 of an item with 3 in stock
        set_cart(self.client, {str(self.fins.pk): 99})
        token, total = self.checkout_token()
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertRedirects(r, reverse('cart:detail'), fetch_redirect_response=False)
        self.assertEqual(self.stock(self.fins), 3)
        self.assert_not_confirmed(r)
        # quantities beyond the cart cap are clamped, never trusted
        set_cart(self.client, {str(self.fins.pk): 10**9})
        r = self.client.get(CHECKOUT)
        self.assertEqual([line.quantity for line in r.context['lines']], [99])

    def test_buying_exactly_the_remaining_stock_reaches_zero_then_next_is_refused(self):
        self.add(self.fins, 3)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, guest_data(token, total))
        self.assertEqual(self.stock(self.fins), 0)
        self.add(self.fins, 1)
        token, total = self.checkout_token()
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertRedirects(r, reverse('cart:detail'), fetch_redirect_response=False)
        self.assertEqual(self.stock(self.fins), 0)
        self.assertEqual(Order.objects.filter(status=Order.Status.CONFIRMED).count(), 1)
        self.assert_movements_explain_stock({self.fins: 3})

    def test_every_stock_change_through_checkout_has_a_movement(self):
        start = {self.mask: 5, self.fins: 3}
        login(self.client, self.alice)
        for card in ('visa_ok', 'visa_decline', 'visa_timeout', 'mc_ok'):
            set_cart(self.client, {})
            self.add(self.mask)
            self.add(self.fins)
            token, total = self.checkout_token()
            self.client.post(CHECKOUT, customer_data(token, self.alice_ship, total, test_card=card))
        self.assertEqual(self.stock(self.mask), 3)
        self.assertEqual(self.stock(self.fins), 1)
        sales = InventoryMovement.objects.filter(reason=InventoryMovement.Reason.SALE)
        self.assertEqual(sales.count(), 4)
        confirmed = set(Order.objects.filter(status=Order.Status.CONFIRMED).values_list('pk', flat=True))
        self.assertEqual(set(sales.values_list('reference_order', flat=True)), confirmed)
        self.assert_movements_explain_stock(start)

    def test_db_forbids_negative_stock(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.filter(pk=self.mask.pk).update(stock_quantity=-1)


# --- invariant 4: one order per checkout (double submit, replay, back button) ----------------

class ExactlyOnceTests(CheckoutBase):
    def test_same_token_from_two_browsers_of_same_customer_is_one_order_one_payment(self):
        tab1, tab2 = self.client, Client()
        for c in (tab1, tab2):
            login(c, self.alice)
            self.add(self.mask, client=c)
        token, total = self.checkout_token(tab1)
        r1 = tab1.post(CHECKOUT, customer_data(token, self.alice_ship, total))
        r2 = tab2.post(CHECKOUT, customer_data(token, self.alice_ship, total))
        order = Order.objects.get()
        self.assertEqual(r1.url, r2.url)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(len(self.calls('authorize')), 1)
        self.assertEqual(len(self.calls('capture')), 1)
        self.assertEqual(self.stock(self.mask), 4)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(order.confirmed_payment, Payment.objects.get())
        # the replaying tab's own cart is not wiped
        self.assertEqual(tab2.session[SESSION_KEY], {str(self.mask.pk): 1})

    def test_token_spelled_differently_is_still_the_same_checkout(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, guest_data(token, total))
        self.add(self.mask)
        u = uuid.UUID(str(token))
        for spelling in (str(u).upper(), u.hex, '{%s}' % u, u.urn, f'  {u}  '):
            with self.subTest(spelling):
                r = self.client.post(CHECKOUT, guest_data(spelling, total))
                self.assertIn(r.status_code, (200, 302))
                self.assertEqual(Order.objects.count(), 1)
                self.assertEqual(len(self.calls('authorize')), 1)
        self.assertEqual(self.stock(self.mask), 4)

    def test_replay_with_tampered_cart_and_total_returns_original_order_unchanged(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, guest_data(token, total))
        order = Order.objects.get()
        self.add(self.fins, 3)
        r = self.client.post(CHECKOUT, guest_data(token, total_for('90.00'), test_card='mc_ok',
                                                  shipping_method='PRIORITY'))
        self.assertEqual(r.url, guest_order_url(order))
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Decimal(total))
        self.assertEqual(list(order.items.values_list('product_id', 'quantity')), [(self.mask.pk, 1)])
        self.assertEqual(self.stock(self.fins), 3)
        self.assertEqual(Payment.objects.count(), 1)

    def test_failed_token_replayed_with_working_card_does_not_retry_payment(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, guest_data(token, total, test_card='visa_decline'))
        r = self.client.post(CHECKOUT, guest_data(token, total, test_card='visa_ok'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.calls('authorize')), 1)
        self.assertEqual(Order.objects.get().status, Order.Status.PAYMENT_FAILED)
        self.assertFalse(any('confirmed' in m.lower() for m in flashes(r)))

    def test_missing_or_garbage_token_never_places_an_order(self):
        self.add(self.mask)
        _, total = self.checkout_token()
        for token in ('', 'not-a-uuid', '1', '00000000-0000-0000-0000-00000000000g', 'a' * 5000):
            with self.subTest(token=token[:20]):
                r = self.client.post(CHECKOUT, guest_data(token, total))
                self.assertEqual(r.status_code, 200)
                self.assertFalse(Order.objects.exists())
                self.assertEqual(self.calls('authorize'), [])
                # the re-rendered form carries a real token for the next submit
                uuid.UUID(r.context['form']['checkout_token'].value())

    def test_update_totals_with_a_used_token_never_places_or_charges(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, guest_data(token, total))
        self.add(self.mask)
        r = self.client.post(CHECKOUT, guest_data(token, total, action='update'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(len(self.calls('authorize')), 1)

    def test_other_customer_replaying_a_token_gets_404_and_learns_nothing(self):
        login(self.client, self.alice)
        self.add(self.mask)
        token, total = self.checkout_token()
        self.client.post(CHECKOUT, customer_data(token, self.alice_ship, total))
        bob = make_account('bob')
        bob_ship = Address.objects.create(account=bob, address_type=Address.AddressType.SHIPPING,
                                          line1='2 Kelp Ave', city='Ottawa', region='ON',
                                          postal_code='K1A 0A1', country='CA', is_default=True)
        mallory = Client()
        login(mallory, bob)
        self.add(self.mask, client=mallory)
        r = mallory.post(CHECKOUT, customer_data(token, bob_ship, total))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(len(self.calls('authorize')), 1)


# --- tampering: the server never trusts posted money, products or payment details -----------

class TamperingTests(CheckoutBase):
    def test_posted_prices_status_owner_and_payment_fields_are_ignored(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        bob = make_account('bob')
        r = self.client.post(CHECKOUT, guest_data(
            token, total, unit_price='0.01', price='0.01', subtotal='0.01', total_amount='0.01',
            tax_amount='0', shipping_cost='0', status='CONFIRMED', account=bob.pk,
            account_id=bob.pk, payment_token='tok_ok', last4=FULL_PAN, card_number=FULL_PAN,
            product_id=self.fins.pk, quantity='99', risk_score='0'))
        self.assertEqual(r.status_code, 302)
        order = Order.objects.get()
        self.assertIsNone(order.account)
        self.assertIsNone(order.risk_score)
        self.assertEqual(str(order.total_amount), total)
        self.assertEqual(list(order.items.values_list('product_id', 'quantity', 'unit_price')),
                         [(self.mask.pk, 1, Decimal('50.00'))])
        payment = Payment.objects.get()
        self.assertEqual((payment.token, payment.last4), ('tok_ok', '4242'))

    def test_posted_gateway_token_cannot_turn_a_declined_card_into_a_success(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        r = self.client.post(CHECKOUT, guest_data(token, total, test_card='visa_decline',
                                                  payment_token='tok_ok', token='tok_ok'))
        self.assertEqual(r.context['error'], MSG_DECLINED)
        self.assertEqual(self.calls('authorize'), ['tok_decline'])
        self.assert_not_confirmed(r)

    def test_forged_expected_total_or_bad_choices_never_place_an_order(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        cases = {
            'lower total': {'expected_total': '0.01'},
            'higher total': {'expected_total': str(Decimal(total) + 1)},
            'negative total': {'expected_total': '-' + total},
            'nan': {'expected_total': 'NaN'},
            'infinity': {'expected_total': 'Infinity'},
            'junk': {'expected_total': total + 'abc'},
            'unknown card': {'test_card': 'amex_free'},
            'unknown shipping': {'shipping_method': 'FREE'},
            'lowercase shipping': {'shipping_method': 'standard'},
            'country outside CA/US': {'ship-country': 'MX'},
            'unknown region': {'ship-region': 'ZZ'},
        }
        for label, over in cases.items():
            with self.subTest(label):
                r = self.client.post(CHECKOUT, guest_data(token, total, **over))
                self.assertEqual(r.status_code, 200)
                self.assertFalse(Order.objects.exists())
                self.assertEqual(self.calls('authorize'), [])

    def test_quote_changed_between_review_and_submit_is_blocked(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        cases = {
            # expected total is the ON/STANDARD quote shown on the page
            'shipping method swapped': {'shipping_method': 'PRIORITY'},
            'region swapped to lower tax': {'ship-region': 'AB'},
            'country swapped': {'ship-country': 'US', 'ship-region': 'OR', 'ship-postal_code': '97201'},
        }
        for label, over in cases.items():
            with self.subTest(label):
                r = self.client.post(CHECKOUT, guest_data(token, total, **over))
                self.assertEqual(r.context['error'], MSG_TOTALS_CHANGED)
                self.assertFalse(Order.objects.exists())
        Product.objects.filter(pk=self.mask.pk).update(unit_price=Decimal('40.00'))  # price drop
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertEqual(r.context['error'], MSG_TOTALS_CHANGED)
        self.assertEqual(str(r.context['quote'].total), total_for('40.00'))
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.calls('authorize'), [])

    def test_product_deactivated_between_review_and_submit_is_never_ordered(self):
        self.add(self.mask)
        self.add(self.fins)
        token, total = self.checkout_token()
        Product.objects.filter(pk=self.fins.pk).update(is_active=False)
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertEqual(r.context['error'], MSG_TOTALS_CHANGED)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.client.session[SESSION_KEY], {str(self.mask.pk): 1})
        # submitting the new total buys only the active item
        r = self.client.post(CHECKOUT, guest_data(r.context['form']['checkout_token'].value(),
                                                  total_for('50.00')))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(list(OrderItem.objects.values_list('product_id', flat=True)), [self.mask.pk])
        self.assertEqual(self.stock(self.fins), 3)

    def test_only_item_deactivated_before_submit_places_nothing(self):
        self.add(self.fins)
        token, total = self.checkout_token()
        Product.objects.filter(pk=self.fins.pk).update(is_active=False)
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertRedirects(r, reverse('cart:detail'), fetch_redirect_response=False)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.calls('authorize'), [])

    def test_tampered_session_cart_entries_are_ignored(self):
        set_cart(self.client, {
            str(self.mask.pk): 1, '999999': 3, '-1': 1, 'abc': 1, str(self.fins.pk): -4,
            '１': 1, '0x10': 1,
        })
        token, total = self.checkout_token()
        self.assertEqual(str(total), total_for('50.00'))
        r = self.client.post(CHECKOUT, guest_data(token, total))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(list(OrderItem.objects.values_list('product_id', 'quantity')), [(self.mask.pk, 1)])
        self.assertEqual(self.stock(self.fins), 3)

    def test_customer_cannot_ship_to_or_bill_another_customers_address_by_id(self):
        bob = make_account('bob')
        bob_addr = Address.objects.create(account=bob, address_type=Address.AddressType.SHIPPING,
                                          line1='2 Kelp Ave', city='Ottawa', region='ON',
                                          postal_code='K1A 0A1', country='CA', is_default=True)
        login(self.client, self.alice)
        self.add(self.mask)
        token, total = self.checkout_token()
        for over in ({'shipping_address': bob_addr.pk},
                     {'billing_same': None, 'billing_address': bob_addr.pk},
                     {'shipping_address': '%d OR 1=1' % bob_addr.pk}):
            with self.subTest(over=over):
                r = self.client.post(CHECKOUT, customer_data(token, self.alice_ship, total, **over))
                self.assertEqual(r.status_code, 200)
                self.assertFalse(Order.objects.exists())
        self.assertEqual(self.calls('authorize'), [])


# --- invariant / data isolation: customers, guests and staff see only what they may ---------

class IsolationTests(CheckoutBase):
    def place(self, account=None, email='gina@example.com', card=('tok_ok', '4242')):
        return place_order(account, [CartLine(self.mask, 1, self.mask.unit_price)],
                           contact=Contact('Someone', email), shipping=ON, billing=ON,
                           shipping_method='STANDARD', payment_token=card[0], last4=card[1],
                           method_type='CREDIT_CARD', card_brand='Visa', checkout_token=uuid.uuid4())

    def test_customer_cannot_reach_another_customers_or_a_guests_order(self):
        bob = make_account('bob')
        bobs = self.place(bob, 'bob@example.com')
        guest = self.place(None)
        mine = self.place(self.alice, 'alice@example.com')
        login(self.client, self.alice)
        for order in (bobs, guest):
            with self.subTest(order=order.pk):
                self.assertEqual(self.client.get(reverse('orders:detail', args=[order.pk])).status_code, 404)
        r = self.client.get(reverse('orders:history'))
        self.assertEqual([o.pk for o in r.context['page_obj']], [mine.pk])
        for bad in ('0', '99999999999999999999999999'):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.get(f'/orders/{bad}/').status_code, 404)

    def test_guest_link_rejects_wrong_forged_or_swapped_keys(self):
        g1, g2 = self.place(None), self.place(None, 'other@example.com')
        good = guest_order_key(g1)
        self.assertEqual(self.client.get(guest_order_url(g1)).status_code, 200)
        bad_keys = {
            "another order's key": guest_order_key(g2),
            'uppercased': good.upper(),
            'truncated': good[:-1],
            'extended': good + '0',
            'one char flipped': good[:-1] + ('0' if good[-1] != '0' else '1'),
            'zeros': '0' * len(good),
            'percent-encoded': good.replace(good[0], '%%%02X' % ord(good[0]), 1),
        }
        for label, key in bad_keys.items():
            with self.subTest(label):
                url = reverse('orders:guest_detail', args=[g1.pk, key])
                self.assertEqual(self.client.get(url).status_code, 404)
        # a valid key moved onto another order id does not open that order
        url = reverse('orders:guest_detail', args=[g2.pk, good])
        self.assertEqual(self.client.get(url).status_code, 404)
        # a key computed for a customer's order never opens it via the guest route
        acct = self.place(self.alice, 'alice@example.com')
        url = reverse('orders:guest_detail', args=[acct.pk, guest_order_key(acct)])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(f'/orders/guest/99999999999999999999999/{good}/').status_code, 404)

    def test_lookup_variations_only_match_the_guest_order_with_its_email(self):
        guest = self.place(None, 'Gina@Example.com')
        acct = self.place(self.alice, 'alice@example.com')
        hit = self.client.post(LOOKUP, {'order_number': guest.pk, 'email': '  gina@EXAMPLE.com '})
        self.assertRedirects(hit, guest_order_url(guest), fetch_redirect_response=False)
        misses = {
            'customer order with its email': {'order_number': acct.pk, 'email': 'alice@example.com'},
            'wildcard email': {'order_number': guest.pk, 'email': '%@example.com'},
            'underscore email': {'order_number': guest.pk, 'email': 'gin_@example.com'},
            'neighbouring order number': {'order_number': guest.pk + 1, 'email': 'gina@example.com'},
            'email prefix': {'order_number': guest.pk, 'email': 'gina@example.co'},
        }
        for label, data in misses.items():
            with self.subTest(label):
                r = self.client.post(LOOKUP, data)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.context['error'], LOOKUP_MISS)
        invalid = {
            'order number too big': {'order_number': str(2**63), 'email': 'gina@example.com'},
            'order number zero': {'order_number': '0', 'email': 'gina@example.com'},
            'order number negative': {'order_number': '-%d' % guest.pk, 'email': 'gina@example.com'},
            'sql in order number': {'order_number': f'{guest.pk} OR 1=1', 'email': 'gina@example.com'},
            'sql in email': {'order_number': guest.pk, 'email': "x' OR '1'='1"},
            'missing email': {'order_number': guest.pk},
        }
        for label, data in invalid.items():
            with self.subTest(label):
                r = self.client.post(LOOKUP, data)
                self.assertEqual(r.status_code, 200)
                self.assertIsNone(r.context['error'])
        # GET parameters never perform a lookup
        r = self.client.get(LOOKUP, {'order_number': guest.pk, 'email': 'gina@example.com'})
        self.assertEqual(r.status_code, 200)

    def test_staff_sees_only_masked_payment_and_never_the_token_or_gateway_ref(self):
        order = self.place(None)
        payment = order.confirmed_payment
        login(self.client, make_account('sam', ROLE_STAFF))
        r = self.client.get(reverse('orders:staff_detail', args=[order.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['payment_display'], 'Visa •••• 4242')
        body = r.content.decode()
        self.assertNotIn(payment.gateway_ref, body)
        self.assertNotIn(payment.token, body)
        for page in (reverse('orders:staff_list'),):
            self.assertNotIn(payment.gateway_ref, self.client.get(page).content.decode())

    def test_customer_and_guest_pages_and_email_show_only_last4(self):
        login(self.client, self.alice)
        self.add(self.mask)
        token, total = self.checkout_token()
        r = self.client.post(CHECKOUT, customer_data(token, self.alice_ship, total), follow=True)
        payment = Payment.objects.get()
        self.assertEqual(r.context['payment_display'], 'Visa •••• 4242')
        for text in (r.content.decode(), mail.outbox[0].body):
            self.assertNotIn(payment.gateway_ref, text)
            self.assertNotIn(payment.token, text)

    def test_full_card_number_posted_anywhere_is_never_stored_logged_or_rendered(self):
        self.add(self.mask)
        token, total = self.checkout_token()
        with capture_all_logs() as records:
            r = self.client.post(CHECKOUT, guest_data(
                token, total, card_number=FULL_PAN, last4=FULL_PAN, pan=FULL_PAN, cc=FULL_PAN,
                payment_token=FULL_PAN), follow=True)
            # declined and timeout paths log too
            for card in ('visa_decline', 'visa_timeout'):
                self.add(self.mask)
                t, tot = self.checkout_token()
                self.client.post(CHECKOUT, guest_data(t, tot, test_card=card, card_number=FULL_PAN))
        self.assertNotIn(FULL_PAN, r.content.decode())
        for record in records:
            self.assertNotIn(FULL_PAN, record.getMessage())
        for message in mail.outbox:
            self.assertNotIn(FULL_PAN, message.body)
        for model in (Order, OrderItem, Payment):
            for row in model.objects.values():
                for field, value in row.items():
                    self.assertNotIn(FULL_PAN, str(value), f'{model.__name__}.{field}')
        for payment in Payment.objects.all():
            self.assertRegex(payment.last4, r'^\d{4}$')
