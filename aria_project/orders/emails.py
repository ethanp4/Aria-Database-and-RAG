import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string

from orders.pricing import SHIPPING_METHODS
from payments.masking import mask_payment

logger = logging.getLogger(__name__)


# mail errors are logged (order id only) and never fail the checkout
def send_order_confirmation(order, order_url):
    if not order.contact_email:
        return
    try:
        payment = order.confirmed_payment
        method = SHIPPING_METHODS.get(order.shipping_method)
        body = render_to_string('orders/email/confirmation.txt', {
            'order': order,
            'items': list(order.items.select_related('product')),
            'shipping_label': method.label if method else order.shipping_method,
            'payment_display': mask_payment(payment) if payment else '',
            'order_url': order_url,
        })
        send_mail(f'Your Aria order #{order.pk}', body, None, [order.contact_email])
    except Exception as exc:
        # no exc_info: SMTP errors can include the recipient address
        logger.error('Failed to send confirmation email for order %s (%s)', order.pk, type(exc).__name__)
