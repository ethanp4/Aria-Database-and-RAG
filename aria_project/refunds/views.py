"""Refund screens from the Figma prototype, as read-only UI stubs.

No Refund model exists yet (CLAUDE.md: planned table). These views render the
designed states but never write: GET only, no forms that submit anywhere.
When refunds are built, replace them with real views that enforce idempotency
(CLAUDE.md invariant 3).
"""
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from accounts.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF
from accounts.permissions import current_account, role_required
from orders.models import Order
from payments.masking import mask_payment

CUSTOMER_STEPS = ('reason', 'items', 'confirm', 'requested')
STAFF_STATES = ('review', 'processing', 'approved', 'decline-reason', 'declined')


@role_required(ROLE_CUSTOMER)
@require_GET
def request_view(request, order_id):
    # own orders only; another customer's order is a 404
    order = get_object_or_404(Order.objects.select_related('confirmed_payment'),
                              pk=order_id, account=current_account(request))
    step = request.GET.get('step', 'reason')
    if step not in CUSTOMER_STEPS:
        step = 'reason'
    payment = order.confirmed_payment
    return render(request, 'refunds/request.html', {
        'order': order, 'step': step, 'steps': CUSTOMER_STEPS,
        'items': list(order.items.select_related('product')),
        # masked display only (brand + last 4); never the token
        'payment_display': mask_payment(payment) if payment else '',
    })


# Staff screens show one SAMPLE request so the designed states can be reviewed.
# Everything below is invented placeholder data: no real order, customer or
# payment is read. Only a masked card display is shown (never a token or PAN).
SAMPLE_REFUND = {
    'reference': 'RF-SAMPLE-1',
    'order_ref': 'AR-SAMPLE-1',
    'order_date': 'Sample order date',
    'customer': 'Sample customer',
    'customer_email': 'customer@example.com',
    'item_name': 'Sample open-heel fins',
    'item_detail': 'Sample size · Qty 1',
    'amount': '189.99',
    'payment_display': 'Visa •••• 4242',
    'reason': 'Size not suitable',
    'reason_text': 'Sample text: the item is unopened and the fit is wrong.',
    'submitted': 'Sample submission time',
    'decline_reason': 'Sample text: the item was opened and used, so it is not eligible under the returns policy.',
    'history': [
        {'order_ref': 'AR-SAMPLE-2', 'amount': '79.00', 'decision': 'Approved'},
        {'order_ref': 'AR-SAMPLE-3', 'amount': '99.00', 'decision': 'Declined'},
    ],
}

SAMPLE_QUEUE = [
    {'reference': 'RF-SAMPLE-1', 'order_ref': 'AR-SAMPLE-1', 'customer': 'Sample customer A',
     'amount': '189.99', 'reason': 'Size not suitable', 'risk': 'Low'},
    {'reference': 'RF-SAMPLE-2', 'order_ref': 'AR-SAMPLE-4', 'customer': 'Sample customer B',
     'amount': '89.95', 'reason': 'Arrived damaged', 'risk': 'Medium'},
    {'reference': 'RF-SAMPLE-3', 'order_ref': 'AR-SAMPLE-5', 'customer': 'Sample customer C',
     'amount': '249.00', 'reason': 'Duplicate request', 'risk': 'High'},
]

STAFF_STATE_LABELS = {
    'review': 'Refund review',
    'processing': 'Processing refund',
    'approved': 'Refund approved',
    'decline-reason': 'Decline reason',
    'declined': 'Refund declined',
}


@role_required(ROLE_STAFF, ROLE_ADMIN)
@require_GET
def staff_queue_view(request):
    return render(request, 'refunds/staff_queue.html', {'requests': SAMPLE_QUEUE})


@role_required(ROLE_STAFF, ROLE_ADMIN)
@require_GET
def staff_review_view(request):
    state = request.GET.get('state', 'review')
    if state not in STAFF_STATES:
        state = 'review'
    return render(request, 'refunds/staff_review.html', {
        'state': state,
        'state_label': STAFF_STATE_LABELS[state],
        'states': STAFF_STATE_LABELS.items(),
        'refund': SAMPLE_REFUND,
    })
