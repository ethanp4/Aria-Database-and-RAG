from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac


# rotating SECRET_KEY invalidates existing guest links (the lookup form still works)
def guest_order_key(order):
    return salted_hmac('aria.guest-order', f'{order.pk}:{order.checkout_token}').hexdigest()


def guest_order_url(order):
    return reverse('orders:guest_detail', args=[order.pk, guest_order_key(order)])


def check_guest_order_key(order, key):
    return constant_time_compare(guest_order_key(order), key)
