from accounts.models import ROLE_ADMIN, ROLE_STAFF
from accounts.permissions import current_account
from products.models import Category


# site shell (base.html): admin flag for role nav, storefront category links.
# Categories are only loaded for shoppers; staff/admin see a role nav instead.
def site_nav(request):
    account = current_account(request)
    is_admin = account is not None and account.account_type == ROLE_ADMIN
    shopper = account is None or account.account_type not in (ROLE_STAFF, ROLE_ADMIN)
    # lazy queryset: only queried by templates that render the storefront nav
    categories = Category.objects.order_by('name')[:6] if shopper else Category.objects.none()
    return {
        'is_admin_viewer': is_admin,
        'nav_categories': categories,
        'current_view': getattr(getattr(request, 'resolver_match', None), 'view_name', ''),
    }
