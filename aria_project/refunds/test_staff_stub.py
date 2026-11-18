"""Staff refund review screens are read-only UI stubs (no Refund model yet).

They must stay staff/admin only, GET only, and never write anything.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Account
from orders.models import Order

STATES = ('review', 'processing', 'approved', 'decline-reason', 'declined')


def make_account(username, role):
    return Account.objects.create(username=username, password_hash='x', account_type=role)


def login(client, account):
    session = client.session
    session['account_id'] = account.account_id
    session.save()


class StaffRefundStubTests(TestCase):
    def setUp(self):
        self.queue_url = reverse('refunds:staff_queue')
        self.review_url = reverse('refunds:staff_review')

    def test_anonymous_redirected_to_login(self):
        for url in (self.queue_url, self.review_url):
            self.assertRedirects(self.client.get(url), reverse('accounts:login'))

    def test_customer_forbidden(self):
        login(self.client, make_account('cust', 'user'))
        for url in (self.queue_url, self.review_url):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_staff_and_admin_see_every_state(self):
        for account in (make_account('staff1', 'staff'), make_account('admin1', 'admin')):
            login(self.client, account)
            response = self.client.get(self.queue_url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "refunds aren't live yet")
            for state in STATES:
                response = self.client.get(self.review_url, {'state': state})
                self.assertEqual(response.status_code, 200, state)
                self.assertEqual(response.context['state'], state)
                self.assertContains(response, "Preview: refunds aren't live yet; no action is taken.")

    def test_unknown_state_falls_back_to_review(self):
        login(self.client, make_account('staff1', 'staff'))
        response = self.client.get(self.review_url, {'state': 'delete-everything'})
        self.assertEqual(response.context['state'], 'review')

    # nothing inside <main> can submit: states are switched with GET links only
    def test_stub_pages_have_no_forms(self):
        login(self.client, make_account('staff1', 'staff'))
        pages = [self.client.get(self.queue_url)]
        pages += [self.client.get(self.review_url, {'state': state}) for state in STATES]
        for response in pages:
            main = response.content.decode().split('<main id="main"', 1)[1].split('</main>', 1)[0]
            self.assertNotIn('<form', main)
            self.assertNotIn('type="submit"', main)

    def test_post_is_rejected_and_writes_nothing(self):
        login(self.client, make_account('staff1', 'staff'))
        for url in (self.queue_url, self.review_url):
            self.assertEqual(self.client.post(url, {'state': 'approved'}).status_code, 405)
        self.assertFalse(Order.objects.exists())
