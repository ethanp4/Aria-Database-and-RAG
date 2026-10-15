from django.test import TestCase
from django.urls import reverse

from accounts.models import Account, Profile


class ProfileTests(TestCase):
    def register(self, username):
        return self.client.post(reverse('accounts:register'), {
            'username': username,
            'password': 'secret-pass',
            'confirm_password': 'secret-pass',
        }, follow=True)

    def test_two_users_can_register_before_filling_profile(self):
        for username in ['first_diver', 'second_diver']:
            with self.subTest(username=username):
                response = self.register(username)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    self.client.get(reverse('accounts:update_profile')).status_code,
                    200,
                )
                self.client.post(reverse('accounts:logout'))

        self.assertEqual(Account.objects.count(), 2)
        self.assertEqual(Profile.objects.count(), 0)

    def test_profile_created_on_first_valid_submit(self):
        self.register('new_diver')

        response = self.client.post(reverse('accounts:update_profile'), {
            'first_name': 'Avery',
            'last_name': 'Morgan',
            'phone': '555-0101',
            'email': 'avery@example.test',
        })

        self.assertRedirects(response, reverse('products:browse'))
        profile = Profile.objects.get()
        self.assertEqual(profile.account.username, 'new_diver')
        self.assertEqual(profile.email, 'avery@example.test')

    def test_existing_profile_is_updated_not_duplicated(self):
        self.register('new_diver')
        data = {'first_name': 'Avery', 'last_name': 'Morgan', 'phone': '', 'email': 'avery@example.test'}
        self.client.post(reverse('accounts:update_profile'), data)

        self.client.post(reverse('accounts:update_profile'), {**data, 'first_name': 'Ari'})

        self.assertEqual(Profile.objects.get().first_name, 'Ari')

    def test_update_profile_requires_login(self):
        response = self.client.get(reverse('accounts:update_profile'))

        self.assertRedirects(response, reverse('accounts:login'))
