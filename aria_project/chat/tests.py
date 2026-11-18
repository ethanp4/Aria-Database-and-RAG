from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account
from chatbot.views import MAX_QUESTION_LENGTH

ASK = reverse('chat:ask')
STREAM = reverse('chatbot:stream')


class AskAriaPageTests(TestCase):
    """The Ask Aria page renders the chat UI; questions go to chatbot:stream (invariants 5 and 6)."""

    def login_as(self, role):
        account = Account.objects.create(username=f'{role}-chat', password_hash='h', account_type=role)
        session = self.client.session
        session['account_id'] = account.account_id
        session['username'] = account.username
        session.save()

    def test_signed_in_roles_get_the_composer_wired_to_the_stream_endpoint(self):
        for role in (ROLE_CUSTOMER, ROLE_STAFF, ROLE_ADMIN):
            with self.subTest(role=role):
                self.client = Client()
                self.login_as(role)
                response = self.client.get(ASK)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'data-stream-url="{STREAM}"')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                self.assertContains(response, f'maxlength="{MAX_QUESTION_LENGTH}"')
                self.assertContains(response, 'js/ask-aria.js')

    def test_guest_is_asked_to_sign_in_and_gets_no_composer(self):
        # chatbot:stream returns 401 to anonymous users, so guests don't get a box that can't work
        response = self.client.get(ASK)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign in to ask Aria')
        self.assertContains(response, reverse('accounts:login'))
        self.assertNotContains(response, 'id="ask-form"')
        self.assertNotContains(response, 'js/ask-aria.js')

    def test_page_has_no_preview_sample_data(self):
        self.login_as(ROLE_CUSTOMER)
        response = self.client.get(ASK)
        for sample in ('Sample data', 'AR-20418', "isn't connected yet", '?state='):
            self.assertNotContains(response, sample)

    def test_page_offers_a_human_and_states_aria_cannot_act(self):
        self.login_as(ROLE_CUSTOMER)
        response = self.client.get(ASK)
        self.assertContains(response, "It can't place, cancel or refund anything.")
        self.assertContains(response, 'data-help-label="Contact customer service"')
        self.assertContains(response, f'data-help-url="{reverse("orders:history")}"')

    def test_staff_help_goes_to_the_staff_order_list(self):
        self.login_as(ROLE_STAFF)
        response = self.client.get(ASK)
        self.assertContains(response, f'data-help-url="{reverse("orders:staff_list")}"')

    def test_page_itself_is_get_only(self):
        self.assertEqual(self.client.post(ASK, {'message': 'Cancel my order'}).status_code, 405)
        self.login_as(ROLE_CUSTOMER)
        self.assertEqual(self.client.post(ASK, {'message': 'Refund me'}).status_code, 405)

    def test_stream_endpoint_enforces_csrf_for_the_page_script(self):
        # the page sends X-CSRFToken; a cross-site POST without it must be rejected
        client = Client(enforce_csrf_checks=True)
        account = Account.objects.create(username='csrf-chat', password_hash='h', account_type=ROLE_CUSTOMER)
        session = client.session
        session['account_id'] = account.account_id
        session.save()
        response = client.post(STREAM, data='{"message": "hi"}', content_type='application/json')
        self.assertEqual(response.status_code, 403)
