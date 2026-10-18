from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Account
from orders.models import Carrier, Order
from orders.tests.test_models import make_order, make_payment
from orders.tests.test_views import add_item, confirm, login


def make_staff(username='staff1', role='staff'):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


class StaffOrderViewTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.customer = Account.objects.create(username='cust1', password_hash='x')
        self.carrier = Carrier.objects.create(name='UPS')

    def test_staff_list_shows_customer_and_guest_orders_and_filters_by_status(self):
        login(self.client, self.staff)
        mine = make_order(account=self.customer, contact_name='Casey Customer')
        guest = make_order(account=None, contact_name='Gina Guest')
        confirm(guest)
        response = self.client.get(reverse('orders:staff_list'))
        self.assertContains(response, f'#{mine.order_id}')
        self.assertContains(response, f'#{guest.order_id}')
        self.assertContains(response, 'cust1')
        self.assertContains(response, 'Guest')
        self.assertContains(response, 'Gina Guest')
        response = self.client.get(reverse('orders:staff_list'), {'status': 'CONFIRMED'})
        self.assertContains(response, f'#{guest.order_id}')
        self.assertNotContains(response, f'#{mine.order_id}')

    def test_admin_can_view_list(self):
        login(self.client, make_staff('boss', 'admin'))
        self.assertEqual(self.client.get(reverse('orders:staff_list')).status_code, 200)

    def test_customer_gets_403_on_staff_order_pages(self):
        login(self.client, self.customer)
        order = make_order(account=self.customer)
        self.assertEqual(self.client.get(reverse('orders:staff_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('orders:staff_detail', args=[order.pk])).status_code, 403)
        r = self.client.post(reverse('orders:staff_mark_shipped', args=[order.pk]),
                             {'carrier': self.carrier.pk, 'tracking_number': 'X1'})
        self.assertEqual(r.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        order = make_order()
        for url in (reverse('orders:staff_list'), reverse('orders:staff_detail', args=[order.pk])):
            self.assertRedirects(self.client.get(url), reverse('accounts:login'))

    def test_staff_order_detail_shows_masked_payment_only(self):
        login(self.client, self.staff)
        order = make_order(account=None, risk_score='12.50')
        p = make_payment(order, token='tok_ok')
        Order.objects.filter(pk=order.pk).update(status='CONFIRMED', confirmed_payment=p)
        add_item(order)
        response = self.client.get(reverse('orders:staff_detail', args=[order.pk]))
        self.assertContains(response, '•••• 4242')
        self.assertNotContains(response, 'tok_ok')
        self.assertContains(response, 'guest@example.com')
        self.assertContains(response, '12.50')

    def test_customer_pages_never_show_risk_score(self):
        order = make_order(account=self.customer, risk_score='77.77')
        login(self.client, self.customer)
        response = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertNotContains(response, '77.77')

    def test_mark_shipped_sets_carrier_and_tracking(self):
        login(self.client, self.staff)
        order = confirm(make_order())
        r = self.client.post(reverse('orders:staff_mark_shipped', args=[order.pk]),
                             {'carrier': self.carrier.pk, 'tracking_number': '  1Z999  '})
        self.assertRedirects(r, reverse('orders:staff_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'SHIPPED')
        self.assertEqual(order.carrier, self.carrier)
        self.assertEqual(order.tracking_number, '1Z999')

    def test_mark_shipped_requires_post(self):
        login(self.client, self.staff)
        order = confirm(make_order())
        r = self.client.get(reverse('orders:staff_mark_shipped', args=[order.pk]))
        self.assertEqual(r.status_code, 405)

    def test_mark_shipped_rejects_unconfirmed_order(self):
        login(self.client, self.staff)
        order = make_order(status='PAYMENT_FAILED')
        r = self.client.post(reverse('orders:staff_mark_shipped', args=[order.pk]),
                             {'carrier': self.carrier.pk, 'tracking_number': 'X1'}, follow=True)
        self.assertContains(r, 'Only confirmed orders can be marked as shipped.')
        order.refresh_from_db()
        self.assertEqual(order.status, 'PAYMENT_FAILED')
        self.assertIsNone(order.carrier)

    def test_mark_shipped_rejects_blank_tracking(self):
        login(self.client, self.staff)
        order = confirm(make_order())
        self.client.post(reverse('orders:staff_mark_shipped', args=[order.pk]),
                         {'carrier': self.carrier.pk, 'tracking_number': '   '})
        order.refresh_from_db()
        self.assertEqual(order.status, 'CONFIRMED')

    def test_mark_shipped_twice_is_rejected(self):
        login(self.client, self.staff)
        order = confirm(make_order())
        url = reverse('orders:staff_mark_shipped', args=[order.pk])
        self.client.post(url, {'carrier': self.carrier.pk, 'tracking_number': 'A1'})
        self.client.post(url, {'carrier': self.carrier.pk, 'tracking_number': 'B2'})
        order.refresh_from_db()
        self.assertEqual(order.tracking_number, 'A1')

    def test_staff_list_query_count_constant(self):
        login(self.client, self.staff)
        url = reverse('orders:staff_list')

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(ctx)

        for i in range(3):
            make_order(account=self.customer if i % 2 else None)
        self.client.get(url)
        small = count_queries()
        for i in range(27):
            make_order(account=self.customer if i % 2 else None)
        self.assertEqual(count_queries(), small)
