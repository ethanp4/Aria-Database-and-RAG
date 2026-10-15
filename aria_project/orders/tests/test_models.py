import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Account
from orders.models import Order, OrderItem
from payments.models import Payment
from products.models import Category, Product


def make_order(account=None, **kw):
    fields = dict(
        account=account,
        contact_name='Guest Buyer',
        contact_email='guest@example.com',
        ship_line1='1 Test St', ship_city='Vancouver', ship_region='BC',
        ship_postal_code='V6B 1A1', ship_country='CA',
        bill_line1='1 Test St', bill_city='Vancouver', bill_region='BC',
        bill_postal_code='V6B 1A1', bill_country='CA',
        shipping_method='STANDARD',
        subtotal=Decimal('10.00'), shipping_cost=Decimal('12.00'),
        tax_amount=Decimal('1.00'), total_amount=Decimal('23.00'),
        checkout_token=uuid.uuid4(),
    )
    fields.update(kw)
    return Order.objects.create(**fields)


def make_payment(order, **kw):
    fields = dict(order=order, amount=order.total_amount, method_type='CREDIT_CARD',
                  token='tok_test', last4='4242', status='CAPTURED')
    fields.update(kw)
    return Payment.objects.create(**fields)


class OrderModelTests(TestCase):
    def test_db_rejects_confirmed_order_without_payment(self):
        o = make_order()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Order.objects.filter(pk=o.pk).update(status='CONFIRMED')

    def test_db_accepts_confirmed_order_with_payment(self):
        o = make_order()
        p = make_payment(o)
        Order.objects.filter(pk=o.pk).update(status='CONFIRMED', confirmed_payment=p)
        o.refresh_from_db()
        self.assertEqual(o.status, 'CONFIRMED')

    def test_db_rejects_order_without_account_or_email(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(account=None, contact_email=None)

    def test_db_rejects_guest_order_with_blank_email(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(account=None, contact_email='')

    def test_account_order_without_email_ok(self):
        acct = Account.objects.create(username='buyer1', password_hash='x')
        make_order(account=acct, contact_email=None)

    def test_checkout_token_unique(self):
        token = uuid.uuid4()
        make_order(checkout_token=token)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(checkout_token=token)

    def test_invalid_shipping_method_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(shipping_method='TELEPORT')

    def test_invalid_country_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(ship_country='FR')

    def test_negative_money_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_order(subtotal=Decimal('-1.00'))

    def test_address_lines(self):
        o = make_order(ship_line2='Unit 5')
        self.assertEqual(o.ship_address_lines(),
                         ['1 Test St', 'Unit 5', 'Vancouver, BC V6B 1A1', 'Canada'])
        self.assertEqual(o.bill_address_lines()[1], 'Vancouver, BC V6B 1A1')


class PaymentModelTests(TestCase):
    def test_payment_rejects_non_digit_last4(self):
        o = make_order()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_payment(o, last4='42a2')
        make_payment(o, last4=None)


class OrderItemTests(TestCase):
    def test_order_item_quantity_must_be_positive(self):
        o = make_order()
        cat = Category.objects.create(name='Masks')
        prod = Product.objects.create(sku='MASK-1', category=cat, name='Mask', unit_price=Decimal('10.00'), stock_quantity=5)
        OrderItem.objects.create(order=o, product=prod, quantity=1,
                                 unit_price=Decimal('10.00'), line_total=Decimal('10.00'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderItem.objects.create(order=o, product=prod, quantity=0,
                                     unit_price=Decimal('10.00'), line_total=Decimal('0.00'))
