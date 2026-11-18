"""Hostile cart input: quantities and product ids a browser form would never send.

Spec (phase 1 plan, Task 4): add takes 1..99, update takes 0..99 (0 removes), quantity per
line capped at 99, cart:add 404s for an inactive product, and the cart never holds an
unknown or inactive product. Bad input must give a message, not a 500, and must leave the
cart as it was.
"""
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from products.models import Product


class CartQuantityAbuseTests(TestCase):
    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.mask = Product.objects.create(sku='MASK-1', name='Mask', unit_price=Decimal('50.00'),
                                           stock_quantity=5)

    def cart(self):
        return dict(self.client.session.get('cart') or {})

    def add(self, qty, product_id=None):
        return self.client.post(reverse('cart:add', args=[product_id or self.mask.pk]),
                                {'quantity': qty})

    def update(self, qty, product_id=None):
        return self.client.post(reverse('cart:update', args=[product_id or self.mask.pk]),
                                {'quantity': qty})

    def test_add_rejects_non_positive_non_integer_and_huge_quantities(self):
        for qty in ['0', '-1', '-99999', '1.5', '2e3', 'abc', '', ' ', '99999999999999999999999',
                    '100', '1; DROP TABLE products']:
            with self.subTest(qty=qty):
                r = self.add(qty)
                self.assertLess(r.status_code, 500, qty)
                self.assertEqual(self.cart(), {}, f'quantity {qty!r} changed the cart')
        self.mask.refresh_from_db()
        self.assertEqual(self.mask.stock_quantity, 5)

    def test_add_with_missing_quantity_field_changes_nothing(self):
        r = self.client.post(reverse('cart:add', args=[self.mask.pk]), {})
        self.assertLess(r.status_code, 500)
        self.assertEqual(self.cart(), {})

    def test_update_rejects_negative_non_integer_and_huge_quantities_and_keeps_line(self):
        self.add('2')
        self.assertEqual(self.cart(), {str(self.mask.pk): 2})
        for qty in ['-1', '-5', '1.5', 'abc', '', '100', '99999999999999999999999']:
            with self.subTest(qty=qty):
                r = self.update(qty)
                self.assertLess(r.status_code, 500, qty)
                self.assertEqual(self.cart(), {str(self.mask.pk): 2},
                                 f'quantity {qty!r} changed the cart')

    def test_repeated_adds_never_exceed_99(self):
        for _ in range(3):
            self.add('60')
        self.assertEqual(self.cart(), {str(self.mask.pk): 99})

    def test_add_nonexistent_product_is_404_and_cart_empty(self):
        r = self.add('1', product_id=999999)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.cart(), {})

    def test_update_cannot_slip_unavailable_products_into_the_cart(self):
        # cart:add refuses inactive/unknown products; cart:update must not be a way around that.
        # The navbar count is what the shopper sees on every page.
        hidden = Product.objects.create(sku='HID-1', name='Hidden', unit_price=Decimal('1.00'),
                                        stock_quantity=5, is_active=False)
        self.update('5', product_id=hidden.pk)
        self.update('7', product_id=999999)
        page = self.client.get(reverse('products:browse'))
        self.assertContains(page, 'Cart (0)')
        detail = self.client.get(reverse('cart:detail'))
        self.assertNotContains(detail, 'Hidden')
        self.assertEqual(detail.context['subtotal'], Decimal('0.00'))
