from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.urls import reverse

from accounts.models import Account


class SessionSecurityTests(TestCase):
    def setUp(self):
        Account.objects.create(username='diver', password_hash=make_password('secret-pass'))

    def start_anonymous_session(self):
        session = self.client.session
        session['visited'] = True
        session.save()
        return session.session_key

    def test_login_rotates_session_key(self):
        before = self.start_anonymous_session()

        self.client.post(reverse('accounts:login'), {'username': 'diver', 'password': 'secret-pass'})

        self.assertIn('account_id', self.client.session)
        self.assertNotEqual(self.client.session.session_key, before)

    def test_register_rotates_session_key(self):
        before = self.start_anonymous_session()

        self.client.post(reverse('accounts:register'), {
            'username': 'newbie',
            'password': 'secret-pass',
            'confirm_password': 'secret-pass',
        })

        self.assertIn('account_id', self.client.session)
        self.assertNotEqual(self.client.session.session_key, before)

    def test_logout_requires_post(self):
        self.client.post(reverse('accounts:login'), {'username': 'diver', 'password': 'secret-pass'})

        response = self.client.get(reverse('accounts:logout'))

        self.assertEqual(response.status_code, 405)
        self.assertIn('account_id', self.client.session)

    def test_logout_post_ends_session(self):
        self.client.post(reverse('accounts:login'), {'username': 'diver', 'password': 'secret-pass'})

        response = self.client.post(reverse('accounts:logout'))

        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('account_id', self.client.session)
