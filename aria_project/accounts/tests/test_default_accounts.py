from io import StringIO
from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account, Profile


DEFAULT_ENV = {
    'DEFAULT_ADMIN_USERNAME': 'Test_Admin',
    'DEFAULT_ADMIN_PASSWORD': 'admin-pass',
    'DEFAULT_ADMIN_EMAIL': 'test.admin@example.test',
    'DEFAULT_STAFF_USERNAME': 'test_staff',
    'DEFAULT_STAFF_PASSWORD': 'staff-pass',
    'DEFAULT_STAFF_EMAIL': 'test.staff@example.test',
}


#blank out any real DEFAULT_* values from .env so only the test's values are used
def run_command(env):
    with patch.dict('os.environ', {**dict.fromkeys(DEFAULT_ENV, ''), **env}):
        call_command('create_default_accounts', stdout=StringIO())


class CreateDefaultAccountsTests(TestCase):
    def test_creates_admin_and_staff_with_roles(self):
        run_command(DEFAULT_ENV)

        admin = Account.objects.get(username='test_admin')
        staff = Account.objects.get(username='test_staff')
        self.assertEqual(admin.account_type, ROLE_ADMIN)
        self.assertEqual(staff.account_type, ROLE_STAFF)
        self.assertTrue(check_password('admin-pass', admin.password_hash))
        self.assertTrue(check_password('staff-pass', staff.password_hash))
        self.assertEqual(admin.profile.email, 'test.admin@example.test')

    def test_running_twice_does_not_duplicate_or_reset_password(self):
        run_command(DEFAULT_ENV)
        run_command({**DEFAULT_ENV, 'DEFAULT_ADMIN_PASSWORD': 'changed-pass'})

        self.assertEqual(Account.objects.count(), 2)
        self.assertEqual(Profile.objects.count(), 2)
        admin = Account.objects.get(username='test_admin')
        self.assertTrue(check_password('admin-pass', admin.password_hash))

    def test_skips_accounts_missing_from_env(self):
        run_command({})

        self.assertFalse(Account.objects.exists())

    def test_does_not_promote_existing_account(self):
        Account.objects.create(
            username='test_admin',
            password_hash=make_password('customer-pass'),
            account_type=ROLE_CUSTOMER,
        )

        run_command(DEFAULT_ENV)

        account = Account.objects.get(username='test_admin')
        self.assertEqual(account.account_type, ROLE_CUSTOMER)
        self.assertTrue(check_password('customer-pass', account.password_hash))

    def test_default_admin_can_log_in(self):
        run_command(DEFAULT_ENV)

        self.client.post(reverse('accounts:login'), {'username': 'test_admin', 'password': 'admin-pass'})

        self.assertEqual(
            self.client.session.get('account_id'),
            Account.objects.get(username='test_admin').account_id,
        )
