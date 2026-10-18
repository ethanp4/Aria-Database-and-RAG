import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from orders.models import Order, OrderItem
from orders.pricing import SHIPPING_METHODS, UnsupportedTaxRegion, quote
from payments.gateway import GatewayTimeout, get_gateway
from payments.models import Payment
from products.models import InventoryMovement, Product

logger = logging.getLogger(__name__)

CENT = Decimal('0.01')
_COUNTRIES = ('CA', 'US')


@dataclass(frozen=True)
class AddressData:
    line1: str
    line2: str | None
    city: str
    region: str
    postal_code: str
    country: str

    @classmethod
    def from_address(cls, address):
        return cls(address.line1, address.line2, address.city, address.region,
                   address.postal_code, address.country)


@dataclass(frozen=True)
class Contact:
    name: str
    email: str | None


class CheckoutError(Exception):
    pass


class OutOfStock(CheckoutError):
    def __init__(self, product_ids):
        super().__init__('Some items are out of stock.')
        self.product_ids = list(product_ids)


class PaymentDeclined(CheckoutError):
    def __init__(self, reason):
        super().__init__('Payment declined.')
        self.reason = reason


# gateway timeout or capture failure; the customer is not charged
class PaymentFailed(CheckoutError):
    pass


# message is shown to the customer
class InvalidCheckout(CheckoutError):
    pass


# message is shown to staff
class InvalidTransition(CheckoutError):
    pass


class _CaptureFailed(Exception):
    pass


def _address_fields(prefix, a):
    return {
        f'{prefix}_line1': a.line1, f'{prefix}_line2': a.line2 or None, f'{prefix}_city': a.city,
        f'{prefix}_region': a.region, f'{prefix}_postal_code': a.postal_code, f'{prefix}_country': a.country,
    }


# step 0: everything that can be checked before a row is written or a card is touched.
# prices come from the db, not the cart lines; a product deleted since it was carted is rejected here.
def _validate(account, cart_lines, contact, shipping, billing, shipping_method):
    quantities = {}
    for cl in cart_lines:
        if not isinstance(cl.quantity, int) or cl.quantity < 1:
            raise InvalidCheckout('Please check the quantities in your cart.')
        quantities[cl.product.pk] = quantities.get(cl.product.pk, 0) + cl.quantity
    if not quantities:
        raise InvalidCheckout('Your cart is empty.')

    email = (contact.email or '').strip() or None
    if account is None and email is None:
        raise InvalidCheckout('Please enter an email address so we can send your order confirmation.')
    if shipping_method not in SHIPPING_METHODS:
        raise InvalidCheckout('Please choose a shipping method.')
    if shipping.country not in _COUNTRIES or billing.country not in _COUNTRIES:
        raise InvalidCheckout('We only ship to and bill addresses in Canada and the United States.')

    products = Product.objects.in_bulk(list(quantities))
    if len(products) != len(quantities):
        raise InvalidCheckout('Some items in your cart are no longer available. Please review your cart.')

    items = []
    subtotal = Decimal('0.00')
    for pid in sorted(quantities):
        price = products[pid].unit_price
        line_total = (price * quantities[pid]).quantize(CENT, ROUND_HALF_UP)
        items.append((pid, quantities[pid], price, line_total))
        subtotal += line_total

    try:
        q = quote(subtotal, shipping_method, shipping.country, shipping.region)
    except UnsupportedTaxRegion:
        raise InvalidCheckout(
            f"We can't calculate tax for {shipping.region}, {shipping.country}. "
            'Please check your shipping address.'
        )
    return items, q, email


def _set_status(order, status):
    order.status = status
    order.confirmed_payment = None
    order.confirmed_at = None
    order.save(update_fields=['status', 'confirmed_payment', 'confirmed_at', 'updated_at'])


def _set_payment_status(payment, status):
    payment.status = status
    payment.save(update_fields=['status'])


# a failed void never changes the outcome; the authorization expires at the gateway
def _void(gateway, order, ref):
    try:
        result = gateway.void(ref)
    except GatewayTimeout:
        logger.error('void timed out: order=%s ref=%s', order.pk, ref)
        return
    except Exception:
        # no traceback: gateway exceptions may carry request details
        logger.error('void raised: order=%s ref=%s', order.pk, ref)
        return
    if not result.ok:
        logger.error('void failed: order=%s ref=%s', order.pk, ref)


# release the authorization, then record the outcome; the void can't skip the status update
def _abandon(gateway, order, payment, ref, payment_status, order_status):
    _void(gateway, order, ref)
    if payment is not None:
        _set_payment_status(payment, payment_status)
    _set_status(order, order_status)


# a retried checkout (double submit, refresh after success) gets its order back, even when
# the cart has since been cleared or prices changed; another owner's token is "not found"
def _replayed(order, account):
    if order.account_id != (account.pk if account else None):
        raise Order.DoesNotExist
    order.was_created = False
    return order


# one checkout token -> at most one order and one authorization.
# raises InvalidCheckout, PaymentDeclined, PaymentFailed, OutOfStock, or Order.DoesNotExist
# when the token belongs to another owner. sets order.was_created (not a db field).
def place_order(account, cart_lines, *, contact, shipping, billing, shipping_method,
                payment_token, last4, method_type, card_brand, checkout_token, gateway=None):
    gateway = gateway or get_gateway()
    existing = Order.objects.filter(checkout_token=checkout_token).first()
    if existing is not None:
        return _replayed(existing, account)
    items, q, email = _validate(account, cart_lines, contact, shipping, billing, shipping_method)

    # step 1: the unique token decides which caller continues. a concurrent caller blocks on
    # the insert until this commits, then gets the existing row and never reaches authorize.
    with transaction.atomic():
        order, created = Order.objects.get_or_create(
            checkout_token=checkout_token,
            defaults=dict(
                account=account, status=Order.Status.PENDING_PAYMENT,
                contact_name=contact.name, contact_email=email,
                **_address_fields('ship', shipping), **_address_fields('bill', billing),
                shipping_method=shipping_method, subtotal=q.subtotal, shipping_cost=q.shipping_cost,
                tax_amount=q.tax_amount, total_amount=q.total,
            ),
        )
        if created:
            OrderItem.objects.bulk_create([
                OrderItem(order=order, product_id=pid, quantity=qty, unit_price=price, line_total=total)
                for pid, qty, price, total in items
            ])
    if not created:
        return _replayed(order, account)

    def new_payment(status, ref=None):
        return Payment.objects.create(
            order=order, amount=order.total_amount, method_type=method_type, token=payment_token,
            last4=last4, card_brand=card_brand or '', status=status, gateway_ref=ref,
        )

    # step 2: authorize only; nothing is charged until capture
    try:
        auth = gateway.authorize(payment_token, order.total_amount)
    except GatewayTimeout:
        logger.error('authorize timed out: order=%s', order.pk)
        new_payment(Payment.Status.FAILED)
        _set_status(order, Order.Status.PAYMENT_FAILED)
        raise PaymentFailed('The payment service did not respond.')
    except Exception:
        # outcome unknown and no ref to void; don't leave the order stuck in PENDING_PAYMENT
        logger.error('authorize raised: order=%s', order.pk)
        new_payment(Payment.Status.FAILED)
        _set_status(order, Order.Status.PAYMENT_FAILED)
        raise
    if not auth.ok:
        new_payment(Payment.Status.DECLINED)
        _set_status(order, Order.Status.PAYMENT_FAILED)
        raise PaymentDeclined(auth.error)

    # step 3: lock, check, decrement, confirm, then capture last so any db error rolls back
    # before money moves. a failed capture raises and rolls the stock back.
    # from here on every exit path either confirms or voids the authorization.
    payment = None
    capture_entered = False
    try:
        # committed before the lock so the authorization ref survives a crash in step 3
        payment = new_payment(Payment.Status.AUTHORIZED, auth.ref)
        with transaction.atomic():
            locked = {
                p.pk: p for p in
                Product.objects.select_for_update().filter(pk__in=[i[0] for i in items]).order_by('pk')
            }
            short = [
                pid for pid, qty, _, _ in items
                if pid not in locked or not locked[pid].is_active or locked[pid].stock_quantity < qty
            ]
            if short:
                raise OutOfStock(short)
            for pid, qty, _, _ in items:
                product = locked[pid]
                product.stock_quantity -= qty
                product.save(update_fields=['stock_quantity', 'updated_at'])
            InventoryMovement.objects.bulk_create([
                InventoryMovement(product_id=pid, change_qty=-qty,
                                  reason=InventoryMovement.Reason.SALE, reference_order=order)
                for pid, qty, _, _ in items
            ])
            _set_payment_status(payment, Payment.Status.CAPTURED)
            order.status = Order.Status.CONFIRMED
            order.confirmed_payment = payment
            order.confirmed_at = timezone.now()
            order.save(update_fields=['status', 'confirmed_payment', 'confirmed_at', 'updated_at'])
            capture_entered = True
            try:
                captured = gateway.capture(auth.ref)
            except GatewayTimeout:
                raise _CaptureFailed('timeout')
            if not captured.ok:
                raise _CaptureFailed(captured.error)
    # step 4: the atomic block rolled back; release the authorization
    except OutOfStock:
        _abandon(gateway, order, payment, auth.ref, Payment.Status.VOIDED, Order.Status.OUT_OF_STOCK)
        raise
    except _CaptureFailed:
        logger.error('capture failed: order=%s ref=%s', order.pk, auth.ref)
        _abandon(gateway, order, payment, auth.ref, Payment.Status.FAILED, Order.Status.PAYMENT_FAILED)
        raise PaymentFailed('The payment could not be completed.')
    except Exception:
        # db error before capture, or capture raised with an unknown outcome: treated like a
        # capture timeout (void + PAYMENT_FAILED), then the original error propagates
        logger.error('unexpected error: order=%s ref=%s capture_entered=%s',
                     order.pk, auth.ref, capture_entered)
        _abandon(gateway, order, payment, auth.ref, Payment.Status.FAILED, Order.Status.PAYMENT_FAILED)
        raise

    logger.info('order confirmed: order=%s ref=%s', order.pk, auth.ref)
    order.was_created = True
    return order


# staff action: only a confirmed order can ship; the row lock makes a double submit a no-op
def mark_shipped(staff, order_id, carrier_id, tracking_number):
    tracking_number = (tracking_number or '').strip()
    if not tracking_number:
        raise InvalidTransition('Please enter a tracking number.')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status != Order.Status.CONFIRMED:
            raise InvalidTransition('Only confirmed orders can be marked as shipped.')
        order.status = Order.Status.SHIPPED
        order.carrier_id = carrier_id
        order.tracking_number = tracking_number
        order.save(update_fields=['status', 'carrier', 'tracking_number', 'updated_at'])
    logger.info('order shipped: order=%s staff=%s', order.pk, staff.pk)
    return order
