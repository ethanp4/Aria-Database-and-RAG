from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account
from cart.cart import Cart
from products.models import Category, Product


def make_product(sku, name, price='10.00', stock=5, active=True):
    return Product.objects.create(
        sku=sku, name=name, unit_price=Decimal(price),
        stock_quantity=stock, is_active=active,
    )


def make_cart():
    request = RequestFactory().get('/')
    request.session = SessionStore()
    return Cart(request)


class CartClassTests(TestCase):
    def setUp(self):
        self.mask = make_product('MASK-1', 'Mask', '19.99')
        self.fin = make_product('FIN-1', 'Fins', '40.50')

    def test_add_set_remove_and_subtotal(self):
        cart = make_cart()
        cart.add(self.mask.product_id, 2)
        cart.add(self.mask.product_id, 1)
        cart.add(self.fin.product_id, 1)
        self.assertEqual(cart.count(), 4)
        self.assertEqual(cart.subtotal(), Decimal('100.47'))
        cart.set(self.mask.product_id, 1)
        self.assertEqual(cart.subtotal(), Decimal('60.49'))
        cart.set(self.fin.product_id, 0)
        cart.remove(self.mask.product_id)
        self.assertEqual(cart.count(), 0)
        self.assertEqual(cart.lines(), [])

    def test_quantity_capped_at_99(self):
        cart = make_cart()
        cart.add(self.mask.product_id, 98)
        cart.add(self.mask.product_id, 50)
        self.assertEqual(cart.count(), 99)

    def test_cart_drops_inactive_and_deleted_products(self):
        gone = make_product('GONE-1', 'Gone')
        cart = make_cart()
        for p in (self.mask, self.fin, gone):
            cart.add(p.product_id, 1)
        self.fin.is_active = False
        self.fin.save()
        gone.delete()
        lines = cart.lines()
        self.assertEqual([line.product.pk for line in lines], [self.mask.pk])
        self.assertEqual(cart.dropped, ['Fins'])
        self.assertEqual(set(cart.request.session['cart']), {str(self.mask.pk)})


class CartViewTests(TestCase):
    def setUp(self):
        self.mask = make_product('MASK-1', 'Mask', '19.99', stock=3)

    def login_as(self, role):
        account = Account.objects.create(
            username=role + 'x', password_hash='h', account_type=role)
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

    def test_guest_can_add_to_cart_and_view_it(self):
        resp = self.client.post(
            reverse('cart:add', args=[self.mask.product_id]), {'quantity': 2})
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(reverse('cart:detail'))
        self.assertContains(resp, 'Mask')
        self.assertContains(resp, '39.98')

    def test_staff_and_admin_get_403_on_cart(self):
        for role in (ROLE_STAFF, ROLE_ADMIN):
            with self.subTest(role=role):
                self.client.logout()
                self.login_as(role)
                self.assertEqual(self.client.get(reverse('cart:detail')).status_code, 403)
                resp = self.client.post(
                    reverse('cart:add', args=[self.mask.product_id]), {'quantity': 1})
                self.assertEqual(resp.status_code, 403)

    def test_cart_survives_login(self):
        Account.objects.create(
            username='diver', password_hash=make_password('pw-12345-x'),
            account_type=ROLE_CUSTOMER)
        self.client.post(reverse('cart:add', args=[self.mask.product_id]), {'quantity': 1})
        self.client.post(reverse('accounts:login'),
                         {'username': 'diver', 'password': 'pw-12345-x'})
        self.assertIn('account_id', self.client.session)
        self.assertContains(self.client.get(reverse('cart:detail')), 'Mask')

    def test_add_inactive_product_404(self):
        self.mask.is_active = False
        self.mask.save()
        resp = self.client.post(
            reverse('cart:add', args=[self.mask.product_id]), {'quantity': 1})
        self.assertEqual(resp.status_code, 404)

    def test_update_to_zero_removes_line(self):
        self.client.post(reverse('cart:add', args=[self.mask.product_id]), {'quantity': 1})
        self.client.post(reverse('cart:update', args=[self.mask.product_id]), {'quantity': 0})
        self.assertContains(self.client.get(reverse('cart:detail')), 'Your cart is empty')

    def test_cart_add_is_post_only(self):
        resp = self.client.get(reverse('cart:add', args=[self.mask.product_id]))
        self.assertEqual(resp.status_code, 405)

    def test_over_stock_line_shows_only_n_left(self):
        self.client.post(reverse('cart:add', args=[self.mask.product_id]), {'quantity': 5})
        self.assertContains(self.client.get(reverse('cart:detail')), 'Only 3 left')

    def test_navbar_cart_shown_for_guest_hidden_for_staff(self):
        self.client.post(reverse('cart:add', args=[self.mask.product_id]), {'quantity': 2})
        self.assertContains(self.client.get(reverse('products:browse')), 'Cart (2)')
        self.client.logout()
        self.login_as(ROLE_STAFF)
        self.assertNotContains(self.client.get(reverse('products:browse')), 'Cart (')


class ProductDetailTests(TestCase):
    def test_product_detail_public_and_hides_inactive(self):
        cat = Category.objects.create(name='Masks')
        p = make_product('MASK-1', 'Mask', '19.99')
        p.category = cat
        p.save()
        hidden = make_product('HID-1', 'Hidden', active=False)
        resp = self.client.get(reverse('products:detail', args=[p.product_id]))
        self.assertContains(resp, 'Mask')
        self.assertContains(resp, 'Masks')
        resp = self.client.get(reverse('products:detail', args=[hidden.product_id]))
        self.assertEqual(resp.status_code, 404)


class CorruptSessionCartTests(TestCase):
    def test_bad_session_cart_shapes_do_not_break_pages(self):
        product = make_product('MASK-1', 'Mask')
        pid = str(product.product_id)
        bad_shapes = {
            'non-dict': ['1', 2],
            'bad key': {'abc': 1, pid: 1},
            'bad quantity': {pid: 'lots', '99999': -3, '7': True, '8': 1.5},
            'over 99': {pid: 500},
        }
        for name, value in bad_shapes.items():
            with self.subTest(shape=name):
                session = self.client.session
                session['cart'] = value
                session.save()
                self.assertEqual(self.client.get(reverse('cart:detail')).status_code, 200)
                self.assertEqual(self.client.get(reverse('products:browse')).status_code, 200)
        session = self.client.session
        session['cart'] = {pid: 500}
        session.save()
        self.assertContains(self.client.get(reverse('cart:detail')), 'value="99"')

