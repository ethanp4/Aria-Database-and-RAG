from datetime import datetime, time, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import ROLE_ADMIN, ROLE_STAFF
from accounts.permissions import current_account, role_required
from orders.forms import MarkShippedForm, StaffOrderFilterForm
from orders.models import Order
from orders.services import InvalidTransition, mark_shipped
from orders.views import _order_context, _order_queryset

PER_PAGE = 50


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _render_detail(request, order, ship_form=None, status=200):
    context = _order_context(order)
    if order.status == Order.Status.CONFIRMED:
        context['ship_form'] = ship_form or MarkShippedForm()
    return render(request, 'orders/staff_detail.html', context, status=status)


def _staff_order(order_id):
    return get_object_or_404(_order_queryset().select_related('account'), pk=order_id)


@role_required(ROLE_STAFF, ROLE_ADMIN)
def staff_list_view(request):
    form = StaffOrderFilterForm(request.GET)
    orders = Order.objects.select_related('account').order_by('-created_at', '-order_id')
    if form.is_valid():
        data = form.cleaned_data
        if data['status']:
            orders = orders.filter(status=data['status'])
        # range bounds on created_at itself so the index stays usable
        if data['date_from']:
            orders = orders.filter(created_at__gte=_day_start(data['date_from']))
        if data['date_to']:
            orders = orders.filter(created_at__lt=_day_start(data['date_to'] + timedelta(days=1)))
    page_obj = Paginator(orders, PER_PAGE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'orders/staff_list.html', {
        'page_obj': page_obj, 'form': form, 'query': params.urlencode(),
    })


@role_required(ROLE_STAFF, ROLE_ADMIN)
def staff_detail_view(request, order_id):
    return _render_detail(request, _staff_order(order_id))


@role_required(ROLE_STAFF, ROLE_ADMIN)
@require_POST
def staff_mark_shipped_view(request, order_id):
    form = MarkShippedForm(request.POST)
    if not form.is_valid():
        return _render_detail(request, _staff_order(order_id), ship_form=form, status=400)
    try:
        mark_shipped(current_account(request), order_id,
                     form.cleaned_data['carrier'].pk, form.cleaned_data['tracking_number'])
    except Order.DoesNotExist:
        raise Http404
    except InvalidTransition as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Order marked as shipped.')
    return redirect('orders:staff_detail', order_id=order_id)
