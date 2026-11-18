from django.test import TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account

ASK = reverse('chat:ask')
REFUSAL = "I couldn't find this in Aria's policies, so I won't guess."
HUMAN_OFFER = 'Contact customer service'


class AskAriaStubTests(TestCase):
    """Ask Aria is a UI stub: GET-only, fixed sample content, no actions (invariants 5 and 6)."""

    def login_as(self, role):
        account = Account.objects.create(username=f'{role}-chat', password_hash='h', account_type=role)
        session = self.client.session
        session['account_id'] = account.account_id
        session['username'] = account.username
        session.save()

    def test_get_works_for_guest_customer_staff_and_admin(self):
        self.assertEqual(self.client.get(ASK).status_code, 200)
        for role in (ROLE_CUSTOMER, ROLE_STAFF, ROLE_ADMIN):
            with self.subTest(role=role):
                self.client.logout()
                self.login_as(role)
                response = self.client.get(ASK)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Ask Aria isn't connected yet")

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(ASK, {'message': 'Cancel my order'}).status_code, 405)
        self.login_as(ROLE_CUSTOMER)
        self.assertEqual(self.client.post(ASK, {'message': 'Refund me'}).status_code, 405)

    def test_unknown_state_falls_back_to_policy_answer(self):
        response = self.client.get(ASK, {'state': 'execute-refund'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['state'], 'answer')
        self.assertContains(response, 'Returns Policy §2')

    def test_answer_cites_a_policy_source(self):
        response = self.client.get(ASK, {'state': 'answer'})
        self.assertContains(response, 'Cited sources')
        self.assertContains(response, 'Returns Policy §2')
        self.assertNotContains(response, REFUSAL)

    def test_no_source_refuses_and_offers_a_human(self):
        response = self.client.get(ASK, {'state': 'no-source'})
        self.assertContains(response, REFUSAL)
        self.assertContains(response, HUMAN_OFFER)
        self.assertNotContains(response, 'Returns Policy §2')

    def test_action_boundary_does_not_act(self):
        response = self.client.get(ASK, {'state': 'action-boundary'})
        self.assertContains(response, "I can't cancel, refund or change orders")
        self.assertContains(response, 'No cancellation has been made.')

    def test_composer_cannot_submit(self):
        response = self.client.get(ASK)
        self.assertContains(response, 'id="ask-message"')
        self.assertNotContains(response, 'name="message"')
        self.assertContains(response, 'Sending is turned off in this preview.')
