from functools import wraps

from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, Account

__all__ = [
    'ROLE_ADMIN',
    'ROLE_CUSTOMER',
    'ROLE_STAFF',
    'current_account',
    'customer_or_guest',
    'login_required',
    'role_required',
]


# returns the logged in account, or None (also None if the account was deleted)
def current_account(request):
    if not hasattr(request, '_aria_account'):
        account_id = request.session.get('account_id')
        request._aria_account = (
            Account.objects.filter(account_id=account_id).first()
            if account_id
            else None
        )
    return request._aria_account


def _redirect_to_login(request):
    messages.error(request, 'You must be logged in to view that page.')
    return redirect('accounts:login')


def login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if current_account(request) is None:
            return _redirect_to_login(request)
        return view(request, *args, **kwargs)
    return wrapper


# usage: @role_required(ROLE_STAFF, ROLE_ADMIN)
def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            account = current_account(request)
            if account is None:
                return _redirect_to_login(request)
            if account.account_type not in roles:
                return HttpResponseForbidden('You do not have permission to access this page.')
            return view(request, *args, **kwargs)
        return wrapper
    return decorator



# storefront views: guests and customers pass, staff and admin get 403
def customer_or_guest(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        account = current_account(request)
        if account is not None and account.account_type != ROLE_CUSTOMER:
            return HttpResponseForbidden('You do not have permission to access this page.')
        return view(request, *args, **kwargs)
    return wrapper
