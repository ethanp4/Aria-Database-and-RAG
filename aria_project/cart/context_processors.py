from accounts.models import ROLE_CUSTOMER
from accounts.permissions import current_account

from .cart import Cart


# navbar: cart count, and whether the viewer may shop (guests and customers only)
def cart_info(request):
    account = current_account(request)
    can_shop = account is None or account.account_type == ROLE_CUSTOMER
    return {
        'can_shop': can_shop,
        'cart_count': Cart(request).count() if can_shop else 0,
    }
