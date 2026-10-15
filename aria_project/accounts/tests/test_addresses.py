from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.forms import AddressForm
from accounts.models import Account, Address


def make_account(username):
    return Account.objects.create(username=username, password_hash='hash')


def make_address(account, line1='1 Reef Rd', address_type='SHIPPING', is_default=False):
    return Address.objects.create(
        account=account,
        address_type=address_type,
        line1=line1,
        city='Halifax',
        region='NS',
        postal_code='B3H 1A1',
        country='CA',
        is_default=is_default,
    )


def address_data(**overrides):
    data = {
        'address_type': 'SHIPPING',
        'line1': '20 Harbour St',
        'line2': '',
        'city': 'Victoria',
        'region': 'BC',
        'postal_code': 'V8W 1A1',
        'country': 'CA',
    }
    data.update(overrides)
    return data


class AddressTests(TestCase):
    def setUp(self):
        self.me = make_account('me')
        self.other = make_account('other')
        self.others_address = make_address(self.other, line1='99 Private Ln')
        session = self.client.session
        session['account_id'] = self.me.account_id
        session.save()

    def test_address_list_shows_only_own_addresses(self):
        make_address(self.me, line1='1 Mine Ave')

        response = self.client.get(reverse('accounts:address_list'))

        self.assertContains(response, '1 Mine Ave')
        self.assertNotContains(response, '99 Private Ln')

    def test_create_address_links_to_logged_in_account(self):
        response = self.client.post(
            reverse('accounts:address_create'),
            address_data(account=self.other.account_id),
        )

        self.assertRedirects(response, reverse('accounts:address_list'))
        created = Address.objects.get(line1='20 Harbour St')
        self.assertEqual(created.account, self.me)

    def test_edit_own_address(self):
        mine = make_address(self.me)

        self.client.post(
            reverse('accounts:address_edit', args=[mine.address_id]),
            address_data(line1='5 New St'),
        )

        mine.refresh_from_db()
        self.assertEqual(mine.line1, '5 New St')
        self.assertEqual(mine.account, self.me)

    def test_customer_cannot_edit_other_customers_address(self):
        url = reverse('accounts:address_edit', args=[self.others_address.address_id])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, address_data(line1='Hijacked')).status_code, 404)
        self.others_address.refresh_from_db()
        self.assertEqual(self.others_address.line1, '99 Private Ln')

    def test_customer_cannot_delete_other_customers_address(self):
        url = reverse('accounts:address_delete', args=[self.others_address.address_id])

        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Address.objects.filter(pk=self.others_address.pk).exists())

    def test_delete_own_address(self):
        mine = make_address(self.me)

        response = self.client.post(reverse('accounts:address_delete', args=[mine.address_id]))

        self.assertRedirects(response, reverse('accounts:address_list'))
        self.assertFalse(Address.objects.filter(pk=mine.pk).exists())

    def test_delete_requires_post(self):
        mine = make_address(self.me)

        response = self.client.get(reverse('accounts:address_delete', args=[mine.address_id]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Address.objects.filter(pk=mine.pk).exists())

    def test_setting_new_default_clears_previous_default(self):
        old_default = make_address(self.me, line1='Old', is_default=True)
        billing_default = make_address(self.me, line1='Bill', address_type='BILLING', is_default=True)

        self.client.post(
            reverse('accounts:address_create'),
            address_data(line1='New', is_default='on'),
        )

        old_default.refresh_from_db()
        billing_default.refresh_from_db()
        self.assertFalse(old_default.is_default)
        self.assertTrue(billing_default.is_default)
        self.assertTrue(Address.objects.get(line1='New').is_default)

    def test_editing_address_into_default_of_another_type_clears_that_types_default(self):
        billing_default = make_address(self.me, line1='Bill', address_type='BILLING', is_default=True)
        shipping = make_address(self.me, line1='Ship', address_type='SHIPPING')

        response = self.client.post(
            reverse('accounts:address_edit', args=[shipping.address_id]),
            address_data(line1='Ship', address_type='BILLING', is_default='on'),
        )

        self.assertRedirects(response, reverse('accounts:address_list'))
        billing_default.refresh_from_db()
        shipping.refresh_from_db()
        self.assertFalse(billing_default.is_default)
        self.assertEqual(shipping.address_type, 'BILLING')
        self.assertTrue(shipping.is_default)

    def test_resubmitting_same_default_twice_does_not_error(self):
        for _ in range(2):
            response = self.client.post(
                reverse('accounts:address_create'),
                address_data(line1='Twice', is_default='on'),
            )
            self.assertRedirects(response, reverse('accounts:address_list'))

        self.assertEqual(Address.objects.filter(account=self.me, is_default=True).count(), 1)

    def test_db_rejects_two_defaults_of_same_type(self):
        make_address(self.me, is_default=True)

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_address(self.me, line1='Second', is_default=True)

    def test_rejects_country_outside_ca_us(self):
        form = AddressForm(data=address_data(country='FR'))

        self.assertFalse(form.is_valid())
        self.assertIn('country', form.errors)

    def test_address_pages_require_login(self):
        self.client.post(reverse('accounts:logout'))
        mine = make_address(self.me)
        urls = [
            reverse('accounts:address_list'),
            reverse('accounts:address_create'),
            reverse('accounts:address_edit', args=[mine.address_id]),
            reverse('accounts:address_delete', args=[mine.address_id]),
        ]
        for url in urls:
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    self.assertRedirects(method(url), reverse('accounts:login'))
        self.assertTrue(Address.objects.filter(pk=mine.pk).exists())
