from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Account
from orders.models import Order, OrderItem
from orders.tests.test_models import make_order
from orders.tests.test_views import confirm, login
from products.models import Product


def make_account(username, role):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def paid_order(total, status='CONFIRMED', items=()):
    order = confirm(make_order(total_amount=Decimal(total)))
    if status != 'CONFIRMED':
        Order.objects.filter(pk=order.pk).update(status=status)
    for product, qty in items:
        OrderItem.objects.create(order=order, product=product, quantity=qty,
                                 unit_price=product.unit_price, line_total=product.unit_price * qty)
    return order


class AnalyticsAccessTests(TestCase):
    def test_admin_sees_both_pages(self):
        login(self.client, make_account('boss', 'admin'))
        for name in ('analytics:dashboard', 'analytics:data'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_staff_and_customer_forbidden(self):
        for account in (make_account('staff1', 'staff'), make_account('cust', 'user')):
            login(self.client, account)
            for name in ('analytics:dashboard', 'analytics:data'):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        for name in ('analytics:dashboard', 'analytics:data'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('accounts:login'))

    def test_post_not_allowed(self):
        login(self.client, make_account('boss', 'admin'))
        self.assertEqual(self.client.post(reverse('analytics:dashboard')).status_code, 405)


class AnalyticsFigureTests(TestCase):
    def setUp(self):
        login(self.client, make_account('boss', 'admin'))
        self.fins = Product.objects.create(sku='FIN-1', name='Test fins', unit_price=Decimal('50.00'),
                                           stock_quantity=2, reorder_level=5)
        self.mask = Product.objects.create(sku='MASK-1', name='Test mask', unit_price=Decimal('20.00'),
                                           stock_quantity=40, reorder_level=5)
        Product.objects.create(sku='OLD-1', name='Hidden low item', unit_price=Decimal('1.00'),
                               stock_quantity=0, reorder_level=5, is_active=False)
        paid_order('100.00', items=[(self.fins, 2)])
        paid_order('60.00', status='SHIPPED', items=[(self.mask, 3)])
        paid_order('40.00', status='DELIVERED', items=[(self.fins, 1)])
        # not revenue: refunded, failed and unpaid orders
        paid_order('999.00', status='REFUNDED', items=[(self.mask, 50)])
        make_order(total_amount=Decimal('500.00'), status='PAYMENT_FAILED')
        make_order(total_amount=Decimal('700.00'))

    def test_figures_match_fixture(self):
        context = self.client.get(reverse('analytics:dashboard')).context
        self.assertEqual(context['kpi_revenue'], Decimal('200.00'))
        self.assertEqual(context['kpi_orders'], 3)
        self.assertEqual(context['monthly'][-1]['revenue'], Decimal('200.00'))
        self.assertEqual(len(context['monthly']), 12)
        self.assertEqual(context['daily_total'], 3)
        self.assertEqual(context['latest_day']['orders'], 3)
        by_status = {s['label']: s['orders'] for s in context['by_status']}
        self.assertEqual(by_status, {'Confirmed': 1, 'Shipped': 1, 'Delivered': 1, 'Refunded': 1,
                                     'Payment failed': 1, 'Processing': 1})
        top = [(p['product__name'], p['units']) for p in context['top_products']]
        self.assertEqual(top, [('Test fins', 3), ('Test mask', 3)])
        self.assertEqual([p['sku'] for p in context['low_stock']], ['FIN-1'])

    def test_data_page_shows_the_same_figures(self):
        response = self.client.get(reverse('analytics:data'))
        self.assertContains(response, '$200.00 CAD')
        self.assertContains(response, 'Total · 3 paid orders')
        self.assertContains(response, 'Test fins')

    def test_refund_figures_are_unavailable_not_invented(self):
        response = self.client.get(reverse('analytics:dashboard'))
        self.assertContains(response, 'Unavailable', count=2)
        self.assertContains(response, 'No refund data yet.')

    def test_no_payment_data_on_page(self):
        response = self.client.get(reverse('analytics:dashboard'))
        self.assertNotContains(response, 'tok_test')
        self.assertNotContains(response, '4242')

    # aggregates run in the DB: more orders must not add queries (no N+1)
    def test_query_count_is_bounded(self):
        url = reverse('analytics:dashboard')
        with CaptureQueriesContext(connection) as small:
            self.client.get(url)
        for _ in range(10):
            paid_order('10.00', items=[(self.mask, 1)])
        with CaptureQueriesContext(connection) as large:
            self.client.get(url)
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 12)
