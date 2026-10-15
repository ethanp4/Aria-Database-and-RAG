import uuid
from decimal import Decimal
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase

from accounts.models import Account, Address
from cart.cart import CartLine
from orders.models import Order
from orders.pricing import quote
from orders.services import (
    AddressData, Contact, InvalidCheckout, OutOfStock, PaymentDeclined, PaymentFailed, place_order,
)
from payments.gateway import FakeGateway
from payments.models import Payment
from products.models import InventoryMovement, Product

BC = AddressData(line1='1 Reef Rd', line2='Unit 4', city='Victoria', region='BC',
                 postal_code='V8W 1A1', country='CA')
WA = AddressData(line1='9 Dock St', line2=None, city='Seattle', region='WA',
                 postal_code='98101', country='US')


def make_product(sku='MASK-1', price='40.00', stock=5, active=True):
    return Product.objects.create(sku=sku, name=f'Product {sku}', unit_price=Decimal(price),
                                  stock_quantity=stock, is_active=active)


def line(product, qty):
    return CartLine(product, qty, product.unit_price * qty)


class CaptureRaisesGateway(FakeGateway):
    def capture(self, ref):
        self._record('capture', ref)
        raise RuntimeError('connection reset')


class VoidRaisesGateway(FakeGateway):
    def void(self, ref):
        self._record('void', ref)
        raise RuntimeError('connection reset')


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.gw = FakeGateway()
        self.mask = make_product('MASK-1', '40.00', stock=5)
        self.fins = make_product('FINS-1', '25.50', stock=3)
        self.alice = Account.objects.create(username='alice', password_hash='x')
        self.bob = Account.objects.create(username='bob', password_hash='x')

    def place(self, account=None, lines=None, **kw):
        args = dict(
            contact=Contact('Alice Diver', 'alice@example.com'),
            shipping=BC, billing=BC, shipping_method='STANDARD',
            payment_token='tok_ok', last4='4242', method_type='CREDIT_CARD', card_brand='Visa',
            checkout_token=uuid.uuid4(), gateway=self.gw,
        )
        args.update(kw)
        if lines is None:
            lines = [line(self.mask, 2), line(self.fins, 1)]
        return place_order(account, lines, **args)

    def stock(self, product):
        product.refresh_from_db()
        return product.stock_quantity

    def sales(self):
        return InventoryMovement.objects.filter(reason=InventoryMovement.Reason.SALE)

    def test_successful_checkout_confirms_order_decrements_stock_and_logs_sale(self):
        order = self.place(self.alice)
        order.refresh_from_db()

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertIsNotNone(order.confirmed_at)
        self.assertEqual(order.confirmed_payment.status, Payment.Status.CAPTURED)
        self.assertEqual(order.account, self.alice)
        self.assertEqual(self.stock(self.mask), 3)
        self.assertEqual(self.stock(self.fins), 2)

        moves = self.sales()
        self.assertEqual(moves.count(), 2)
        self.assertEqual({(m.product_id, m.change_qty) for m in moves},
                         {(self.mask.pk, -2), (self.fins.pk, -1)})
        self.assertTrue(all(m.reference_order_id == order.pk for m in moves))

        q = quote(Decimal('105.50'), 'STANDARD', 'CA', 'BC')
        self.assertEqual(order.subtotal, q.subtotal)
        self.assertEqual(order.shipping_cost, q.shipping_cost)
        self.assertEqual(order.tax_amount, q.tax_amount)
        self.assertEqual(order.total_amount, q.total)
        self.assertEqual(order.confirmed_payment.amount, q.total)

        items = {i.product_id: i for i in order.items.all()}
        self.assertEqual(items[self.mask.pk].quantity, 2)
        self.assertEqual(items[self.mask.pk].unit_price, Decimal('40.00'))
        self.assertEqual(items[self.mask.pk].line_total, Decimal('80.00'))
        self.assertEqual(items[self.fins.pk].line_total, Decimal('25.50'))

        self.assertEqual(
            (order.ship_line1, order.ship_line2, order.ship_city, order.ship_region,
             order.ship_postal_code, order.ship_country),
            ('1 Reef Rd', 'Unit 4', 'Victoria', 'BC', 'V8W 1A1', 'CA'),
        )
        self.assertEqual(order.bill_line1, '1 Reef Rd')
        self.assertEqual([c[0] for c in self.gw.calls], ['authorize', 'capture'])

    def test_order_uses_current_db_price_not_cart_line_price(self):
        stale = line(self.mask, 1)
        Product.objects.filter(pk=self.mask.pk).update(unit_price=Decimal('50.00'))
        order = self.place(self.alice, lines=[stale])
        self.assertEqual(order.subtotal, Decimal('50.00'))
        self.assertEqual(order.items.get().unit_price, Decimal('50.00'))

    def test_guest_checkout_creates_order_without_account(self):
        order = self.place(None, contact=Contact('Gina Guest', 'gina@example.com'))
        order.refresh_from_db()
        self.assertIsNone(order.account)
        self.assertEqual(order.contact_email, 'gina@example.com')
        self.assertEqual(order.contact_name, 'Gina Guest')
        self.assertEqual(order.status, Order.Status.CONFIRMED)

    def test_guest_without_email_rejected_before_payment(self):
        for email in (None, '', '   '):
            with self.assertRaises(InvalidCheckout):
                self.place(None, contact=Contact('Gina Guest', email))
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.gw.calls, [])

    def test_empty_cart_and_unknown_shipping_method_rejected_before_payment(self):
        with self.assertRaises(InvalidCheckout):
            self.place(self.alice, lines=[])
        with self.assertRaises(InvalidCheckout):
            self.place(self.alice, shipping_method='TELEPORT')
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.gw.calls, [])

    def test_declined_payment_leaves_order_payment_failed_and_stock_untouched(self):
        token = uuid.uuid4()
        with self.assertRaises(PaymentDeclined) as ctx:
            self.place(self.alice, payment_token='tok_decline', checkout_token=token)
        self.assertEqual(ctx.exception.reason, 'card_declined')
        order = Order.objects.get(checkout_token=token)
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertIsNone(order.confirmed_payment)
        self.assertEqual(order.payments.get().status, Payment.Status.DECLINED)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertFalse(self.sales().exists())
        self.assertEqual([c[0] for c in self.gw.calls], ['authorize'])

    def test_authorize_timeout_leaves_order_payment_failed(self):
        token = uuid.uuid4()
        with self.assertRaises(PaymentFailed):
            self.place(self.alice, payment_token='tok_timeout_authorize', checkout_token=token)
        order = Order.objects.get(checkout_token=token)
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertIsNone(order.confirmed_payment)
        self.assertEqual(order.payments.get().status, Payment.Status.FAILED)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual([c[0] for c in self.gw.calls], ['authorize'])

    def test_capture_timeout_leaves_order_unconfirmed_and_restores_stock(self):
        token = uuid.uuid4()
        with self.assertRaises(PaymentFailed):
            self.place(self.alice, payment_token='tok_timeout_capture', checkout_token=token)
        order = Order.objects.get(checkout_token=token)
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertIsNone(order.confirmed_payment)
        self.assertIsNone(order.confirmed_at)
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(self.stock(self.fins), 3)
        self.assertFalse(self.sales().exists())
        ref = payment.gateway_ref
        self.assertEqual(self.gw.calls, [('authorize', 'tok_timeout_capture'),
                                         ('capture', ref), ('void', ref)])

    def test_out_of_stock_voids_authorization_and_shows_clear_message(self):
        token = uuid.uuid4()
        with self.assertRaises(OutOfStock) as ctx:
            self.place(self.alice, lines=[line(self.mask, 1), line(self.fins, 4)], checkout_token=token)
        self.assertEqual(ctx.exception.product_ids, [self.fins.pk])
        order = Order.objects.get(checkout_token=token)
        self.assertEqual(order.status, Order.Status.OUT_OF_STOCK)
        self.assertIsNone(order.confirmed_payment)
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.VOIDED)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(self.stock(self.fins), 3)
        self.assertFalse(self.sales().exists())
        self.assertEqual(self.gw.calls, [('authorize', 'tok_ok'), ('void', payment.gateway_ref)])

    def test_inactive_product_treated_as_out_of_stock(self):
        cart = [line(self.mask, 1), line(self.fins, 1)]
        Product.objects.filter(pk=self.mask.pk).update(is_active=False)
        with self.assertRaises(OutOfStock) as ctx:
            self.place(self.alice, lines=cart)
        self.assertEqual(ctx.exception.product_ids, [self.mask.pk])
        self.assertEqual(self.stock(self.fins), 3)
        self.assertNotIn('capture', [c[0] for c in self.gw.calls])
        self.assertIn('void', [c[0] for c in self.gw.calls])

    def test_deleted_product_rejected_before_payment(self):
        ghost = make_product('GHOST-1')
        cart = [line(ghost, 1)]
        ghost.delete()
        with self.assertRaises(InvalidCheckout):
            self.place(self.alice, lines=cart)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.gw.calls, [])

    def test_same_checkout_token_twice_returns_same_order_and_charges_once(self):
        token = uuid.uuid4()
        first = self.place(self.alice, checkout_token=token)
        second = self.place(self.alice, checkout_token=token)
        self.assertEqual(first.pk, second.pk)
        self.assertTrue(first.was_created)
        self.assertFalse(second.was_created)
        self.assertEqual(second.status, Order.Status.CONFIRMED)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.stock(self.mask), 3)
        actions = [c[0] for c in self.gw.calls]
        self.assertEqual(actions.count('authorize'), 1)
        self.assertEqual(actions.count('capture'), 1)

    def test_replay_after_success_with_cleared_cart_returns_same_order(self):
        token = uuid.uuid4()
        first = self.place(self.alice, checkout_token=token)
        calls = list(self.gw.calls)
        Product.objects.filter(pk=self.mask.pk).update(unit_price=Decimal('99.00'))
        bad = AddressData(line1='1 Lake Rd', line2=None, city='Toronto', region='Ontaro',
                          postal_code='M5V 1A1', country='CA')
        again = self.place(self.alice, lines=[], shipping=bad, checkout_token=token)
        self.assertEqual(again.pk, first.pk)
        self.assertFalse(again.was_created)
        self.assertEqual(again.status, Order.Status.CONFIRMED)
        self.assertEqual(self.gw.calls, calls)
        with self.assertRaises(Order.DoesNotExist):
            self.place(self.bob, lines=[], checkout_token=token)

    def assert_abandoned_after_authorize(self, token):
        order = Order.objects.get(checkout_token=token)
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertIsNone(order.confirmed_payment)
        self.assertIsNone(order.confirmed_at)
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertIn(('void', payment.gateway_ref), self.gw.calls)
        self.assertEqual(self.stock(self.mask), 5)
        self.assertEqual(self.stock(self.fins), 3)
        self.assertFalse(self.sales().exists())

    def test_db_error_before_capture_voids_and_marks_payment_failed(self):
        token = uuid.uuid4()
        with mock.patch.object(InventoryMovement.objects, 'bulk_create',
                               side_effect=DatabaseError('disk full')):
            with self.assertRaises(DatabaseError):
                self.place(self.alice, checkout_token=token)
        self.assert_abandoned_after_authorize(token)
        self.assertNotIn('capture', [c[0] for c in self.gw.calls])

    def test_capture_raising_unexpected_error_voids_and_marks_payment_failed(self):
        self.gw = CaptureRaisesGateway()
        token = uuid.uuid4()
        with self.assertRaises(RuntimeError):
            self.place(self.alice, checkout_token=token)
        self.assert_abandoned_after_authorize(token)
        self.assertEqual([c[0] for c in self.gw.calls], ['authorize', 'capture', 'void'])

    def test_failing_void_still_records_outcome(self):
        self.gw = VoidRaisesGateway()
        token = uuid.uuid4()
        with self.assertRaises(OutOfStock):
            self.place(self.alice, lines=[line(self.fins, 4)], checkout_token=token)
        order = Order.objects.get(checkout_token=token)
        self.assertEqual(order.status, Order.Status.OUT_OF_STOCK)
        self.assertEqual(order.payments.get().status, Payment.Status.VOIDED)

    def test_same_token_after_failure_does_not_retry_payment(self):
        token = uuid.uuid4()
        with self.assertRaises(PaymentDeclined):
            self.place(self.alice, payment_token='tok_decline', checkout_token=token)
        again = self.place(self.alice, checkout_token=token)
        self.assertEqual(again.status, Order.Status.PAYMENT_FAILED)
        self.assertFalse(again.was_created)
        self.assertEqual([c[0] for c in self.gw.calls], ['authorize'])

    def test_checkout_token_of_other_owner_is_rejected(self):
        token = uuid.uuid4()
        self.place(self.alice, checkout_token=token)
        calls_before = list(self.gw.calls)

        with self.assertRaises(Order.DoesNotExist):
            self.place(self.bob, checkout_token=token)
        with self.assertRaises(Order.DoesNotExist):
            self.place(None, contact=Contact('Gina Guest', 'gina@example.com'), checkout_token=token)

        guest_token = uuid.uuid4()
        self.place(None, contact=Contact('Gina Guest', 'gina@example.com'), checkout_token=guest_token)
        calls_before = list(self.gw.calls)
        with self.assertRaises(Order.DoesNotExist):
            self.place(self.alice, checkout_token=guest_token)

        self.assertEqual(self.gw.calls, calls_before)
        self.assertEqual(Order.objects.count(), 2)

    def test_unsupported_tax_region_blocks_checkout_before_payment(self):
        bad = AddressData(line1='1 Lake Rd', line2=None, city='Toronto', region='Ontaro',
                          postal_code='M5V 1A1', country='CA')
        with self.assertRaises(InvalidCheckout) as ctx:
            self.place(self.alice, shipping=bad)
        self.assertEqual(
            str(ctx.exception),
            "We can't calculate tax for Ontaro, CA. Please check your shipping address.",
        )
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.gw.calls, [])

    def test_editing_address_book_does_not_change_existing_order(self):
        addr = Address.objects.create(account=self.alice, address_type='SHIPPING', line1='1 Reef Rd',
                                      city='Halifax', region='NS', postal_code='B3H 1A1', country='CA')
        data = AddressData.from_address(addr)
        order = self.place(self.alice, shipping=data, billing=data)

        addr.line1 = '99 Moved Ave'
        addr.city = 'Toronto'
        addr.region = 'ON'
        addr.save()
        addr.delete()

        order.refresh_from_db()
        self.assertEqual((order.ship_line1, order.ship_city, order.ship_region),
                         ('1 Reef Rd', 'Halifax', 'NS'))
        self.assertEqual(order.bill_line1, '1 Reef Rd')

    def test_us_shipping_address_and_separate_billing_copied(self):
        order = self.place(self.alice, shipping=WA, billing=BC)
        self.assertEqual((order.ship_city, order.ship_country, order.ship_line2), ('Seattle', 'US', None))
        self.assertEqual((order.bill_city, order.bill_country), ('Victoria', 'CA'))
        q = quote(Decimal('105.50'), 'STANDARD', 'US', 'WA')
        self.assertEqual(order.total_amount, q.total)

    def test_payment_row_stores_only_token_last4_and_brand(self):
        order = self.place(self.alice)
        p = Payment.objects.get(order=order)
        self.assertEqual(p.token, 'tok_ok')
        self.assertEqual(p.last4, '4242')
        self.assertEqual(p.card_brand, 'Visa')
        self.assertEqual(p.method_type, 'CREDIT_CARD')
        self.assertTrue(p.gateway_ref.startswith('fake_tok_ok_'))
        stored = [str(getattr(p, f.attname)) for f in Payment._meta.concrete_fields]
        self.assertFalse(any(v.isdigit() and len(v) >= 12 for v in stored if v != str(p.pk)))
        self.assertEqual(
            {f.name for f in Payment._meta.concrete_fields},
            {'payment_id', 'order', 'amount', 'method_type', 'token', 'last4', 'card_brand',
             'status', 'gateway_ref', 'created_at'},
        )
