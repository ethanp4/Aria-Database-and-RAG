"""Customer refund request: a read-only UI preview (no Refund model yet).

Checks the access rules and that the preview never claims a refund request was created.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account
from orders.links import guest_order_url
from orders.tests.test_models import make_order
from orders.tests.test_views import add_item, confirm

NOT_CREATED = 'No refund request was created.'
PREVIEW = "Preview only: refunds aren't live yet. Contact us to request a refund."


def make_account(username, role=ROLE_CUSTOMER):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def login(client, account):
    session = client.session
    session['account_id'] = account.account_id
    session.save()


def request_url(order, step=None):
    url = reverse('refunds:request', args=[order.pk])
    return f'{url}?step={step}' if step else url


class RefundRequestPreviewTests(TestCase):
    def setUp(self):
        self.alice = make_account('alice')
        self.bob = make_account('bob')
        self.order = confirm(make_order(account=self.alice))
        add_item(self.order)

    def test_customer_sees_every_step_of_own_order(self):
        login(self.client, self.alice)
        for step in ('reason', 'items', 'confirm', 'requested'):
            with self.subTest(step=step):
                r = self.client.get(request_url(self.order, step))
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.context['step'], step)
                self.assertContains(r, f'Order #{self.order.pk}')
                self.assertContains(r, 'Mask P1')
                self.assertContains(r, 'class="prototype-notice"')
                # nothing on the preview submits anywhere
                main = r.content.decode().split('<main', 1)[1].split('</main>', 1)[0]
                self.assertNotIn('<form', main)
                # masked payment only, never the token
                self.assertNotContains(r, 'tok_test')

    def test_requested_step_says_no_request_was_created(self):
        login(self.client, self.alice)
        r = self.client.get(request_url(self.order, 'requested'))
        self.assertContains(r, NOT_CREATED)
        self.assertContains(r, PREVIEW)
        self.assertNotContains(r, 'Refund requested')
        self.assertContains(r, '•••• 4242')

    def test_unknown_step_falls_back_to_reason(self):
        login(self.client, self.alice)
        r = self.client.get(request_url(self.order, 'approved'))
        self.assertEqual(r.context['step'], 'reason')

    def test_other_customers_order_is_404(self):
        login(self.client, self.bob)
        self.assertEqual(self.client.get(request_url(self.order)).status_code, 404)

    def test_guest_order_is_404_for_a_customer(self):
        guest_order = make_order()
        login(self.client, self.alice)
        self.assertEqual(self.client.get(request_url(guest_order)).status_code, 404)

    def test_staff_and_admin_get_403(self):
        for role in (ROLE_STAFF, ROLE_ADMIN):
            with self.subTest(role=role):
                login(self.client, make_account(f'u_{role}', role))
                self.assertEqual(self.client.get(request_url(self.order)).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        r = self.client.get(request_url(self.order))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('accounts:login'), r.url)

    def test_post_is_405(self):
        login(self.client, self.alice)
        r = self.client.post(request_url(self.order, 'confirm'), {'reason': 'x'})
        self.assertEqual(r.status_code, 405)


class RefundEntryPointTests(TestCase):
    def setUp(self):
        self.alice = make_account('alice')

    def test_confirmed_order_detail_links_to_refund_request(self):
        order = confirm(make_order(account=self.alice))
        login(self.client, self.alice)
        r = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertContains(r, reverse('refunds:request', args=[order.pk]))

    def test_unconfirmed_order_detail_has_no_refund_link(self):
        login(self.client, self.alice)
        for status in ('PENDING_PAYMENT', 'PAYMENT_FAILED', 'OUT_OF_STOCK'):
            with self.subTest(status=status):
                order = make_order(account=self.alice, status=status)
                r = self.client.get(reverse('orders:detail', args=[order.pk]))
                self.assertNotContains(r, reverse('refunds:request', args=[order.pk]))

    def test_guest_order_page_has_no_refund_link(self):
        order = confirm(make_order())
        r = self.client.get(guest_order_url(order))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Request a refund')
