from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import Account
from accounts.permissions import (
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_STAFF,
    current_account,
    login_required,
    role_required,
)


@login_required
def members_view(request):
    return HttpResponse('ok')


@role_required(ROLE_ADMIN)
def admin_view(request):
    return HttpResponse('ok')


@role_required(ROLE_STAFF, ROLE_ADMIN)
def staff_view(request):
    return HttpResponse('ok')


def make_account(username, account_type=ROLE_CUSTOMER):
    return Account.objects.create(
        username=username,
        password_hash='hash',
        account_type=account_type,
    )


class PermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def make_request(self, account=None):
        request = self.factory.get('/anything/')
        request.session = SessionStore()
        if account is not None:
            request.session['account_id'] = account.account_id
        request._messages = FallbackStorage(request)
        return request

    def test_current_account_returns_account_from_session(self):
        account = make_account('diver')
        self.assertEqual(current_account(self.make_request(account)), account)

    def test_current_account_none_when_not_logged_in(self):
        self.assertIsNone(current_account(self.make_request()))

    def test_current_account_none_when_session_account_deleted(self):
        account = make_account('gone')
        request = self.make_request(account)
        account.delete()

        self.assertIsNone(current_account(request))

    def test_login_required_redirects_anonymous_to_login(self):
        response = members_view(self.make_request())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('accounts:login'))

    def test_login_required_allows_logged_in_account(self):
        response = members_view(self.make_request(make_account('diver')))

        self.assertEqual(response.status_code, 200)

    def test_role_required_redirects_anonymous_to_login(self):
        response = admin_view(self.make_request())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('accounts:login'))

    def test_role_required_forbids_wrong_role(self):
        response = admin_view(self.make_request(make_account('customer')))

        self.assertEqual(response.status_code, 403)

    def test_role_required_allows_listed_roles(self):
        for username, role in [('staffer', ROLE_STAFF), ('boss', ROLE_ADMIN)]:
            with self.subTest(role=role):
                response = staff_view(self.make_request(make_account(username, role)))
                self.assertEqual(response.status_code, 200)

    def test_db_accepts_staff_and_rejects_unknown_account_type(self):
        make_account('staffer', ROLE_STAFF)

        with self.assertRaises(IntegrityError):
            make_account('root', 'superuser')
