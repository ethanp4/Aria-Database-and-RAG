from urllib.parse import quote

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import current_account, login_required
from orders.forms import OrderLookupForm
from orders.links import check_guest_order_key, guest_order_url
from orders.models import Order
from orders.pricing import SHIPPING_METHODS
from payments.masking import mask_payment

LOOKUP_MISS = "We couldn't find an order with that number and email."


# context for the shared order body; never includes risk_score
def _order_context(order):
    method = SHIPPING_METHODS.get(order.shipping_method)
    payment = order.confirmed_payment
    tracking_url = None
    template = order.carrier.tracking_url_template if order.carrier else None
    if template and order.tracking_number and template.startswith(('http://', 'https://')):
        tracking_url = template.replace('{tracking_number}', quote(order.tracking_number, safe=''))
    return {
        'order': order,
        'items': list(order.items.select_related('product')),
        'shipping_label': method.label if method else order.shipping_method,
        'ship_lines': order.ship_address_lines(),
        'bill_lines': order.bill_address_lines(),
        'payment_display': mask_payment(payment) if payment else '',
        'tracking_url': tracking_url,
    }


def _order_queryset():
    return Order.objects.select_related('carrier', 'confirmed_payment')


@login_required
def history_view(request):
    orders = Order.objects.filter(account=current_account(request)).order_by('-created_at', '-order_id')
    page_obj = Paginator(orders, 20).get_page(request.GET.get('page'))
    return render(request, 'orders/history.html', {'page_obj': page_obj})


@login_required
def detail_view(request, order_id):
    order = get_object_or_404(_order_queryset(), pk=order_id, account=current_account(request))
    return render(request, 'orders/detail.html', _order_context(order))


def guest_detail_view(request, order_id, key):
    order = get_object_or_404(_order_queryset(), pk=order_id, account__isnull=True)
    if not check_guest_order_key(order, key):
        raise Http404
    response = render(request, 'orders/detail.html', {**_order_context(order), 'is_guest': True})
    response['Referrer-Policy'] = 'no-referrer'
    return response


# same response for every miss so the page does not reveal whether an order exists
def lookup_view(request):
    form = OrderLookupForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        order = Order.objects.filter(
            pk=form.cleaned_data['order_number'], account__isnull=True,
            contact_email__iexact=form.cleaned_data['email'],
        ).first()
        if order:
            return redirect(guest_order_url(order))
        error = LOOKUP_MISS
    return render(request, 'orders/lookup.html', {'form': form, 'error': error})
