import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from accounts.permissions import current_account, customer_or_guest
from accounts.regions import normalize_region
from orders.emails import send_order_confirmation
from orders.links import guest_order_url
from orders.models import Order
from orders.pricing import SHIPPING_METHODS, UnsupportedTaxRegion, quote
from orders.services import InvalidCheckout, OutOfStock, PaymentDeclined, PaymentFailed, place_order
from payments.test_cards import TEST_CARDS
from products.models import Product

from .cart import Cart
from .forms import AddToCartForm, CheckoutForm, UpdateCartForm


@customer_or_guest
def cart_detail_view(request):
    cart = Cart(request)
    lines = cart.lines()
    for name in cart.dropped:
        messages.warning(request, f'{name} is no longer available and was removed from your cart.')
    return render(request, 'cart/detail.html', {
        'lines': lines,
        'subtotal': cart.subtotal(),
        'has_stock_problem': any(l.quantity > l.product.stock_quantity for l in lines),
    })


@customer_or_guest
@require_POST
def cart_add_view(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    form = AddToCartForm(request.POST)
    if form.is_valid():
        Cart(request).add(product.pk, form.cleaned_data['quantity'])
        messages.success(request, f'{product.name} was added to your cart.')
    else:
        messages.error(request, 'Please enter a quantity between 1 and 99.')
    return redirect('products:detail', product_id=product.pk)


@customer_or_guest
@require_POST
def cart_update_view(request, product_id):
    form = UpdateCartForm(request.POST)
    if form.is_valid():
        Cart(request).set(product_id, form.cleaned_data['quantity'])
        messages.success(request, 'Your cart was updated.')
    else:
        messages.error(request, 'Please enter a quantity between 0 and 99.')
    return redirect('cart:detail')


MSG_DECLINED = "Your payment didn't go through. You have not been charged."
MSG_TOTALS_CHANGED = 'Prices or totals changed. Please review and submit again.'
MSG_REVIEW_TOTAL = 'Please review your total and submit again.'

# query keys the "Update totals" GET may carry back into the form
_GUEST_KEYS = ('contact_name', 'contact_email') + tuple(
    f'{prefix}-{name}' for prefix in ('ship', 'bill')
    for name in ('line1', 'line2', 'city', 'region', 'postal_code', 'country'))


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _shipping_method(values):
    method = values.get('shipping_method')
    return method if method in SHIPPING_METHODS else 'STANDARD'


# (country, region) to quote with, from submitted values that may not be valid yet.
# a customer's choice is looked up in their own address book only.
def _ship_location(form, values):
    if form.account is not None:
        own = form.fields['shipping_address'].queryset
        chosen = str(values.get('shipping_address') or '')
        address = (own.filter(pk=chosen).first() if chosen.isdigit() else None) or own.first()
        return (address.country, address.region) if address else None
    country = values.get('ship-country')
    try:
        return country, normalize_region(country, values.get('ship-region'))
    except ValidationError:
        return None


# returns (quote or None, bad_region); prices come from the db through the cart
def _quote_for(cart, form, values):
    location = _ship_location(form, values)
    if location is None:
        return None, False
    try:
        return quote(cart.subtotal(), _shipping_method(values), *location), False
    except UnsupportedTaxRegion:
        return None, True


def _initial_from_query(account, values):
    initial = {'billing_same': 'billing_same' in values}
    keys = ('shipping_address', 'billing_address') if account is not None else _GUEST_KEYS
    for key in keys:
        if key in values:
            initial[key] = values[key]
    if values.get('shipping_method') in SHIPPING_METHODS:
        initial['shipping_method'] = values['shipping_method']
    if values.get('test_card') in TEST_CARDS:
        initial['test_card'] = values['test_card']
    return initial


def _render_checkout(request, cart, form, q, *, error=None, bad_region=False):
    return render(request, 'cart/checkout.html', {
        'form': form,
        'lines': cart.lines(),
        'subtotal': cart.subtotal(),
        'quote': q,
        'error': error,
        'bad_region': bad_region,
        'is_guest': form.account is None,
        'no_shipping_address': (form.account is not None
                                and not form.fields['shipping_address'].queryset.exists()),
    })


# re-render a POST with a fresh quote; the hidden total is replaced so the next submit
# confirms the total the customer is now looking at
def _rerender(request, account, cart, *, error=None, fresh_token=False):
    data = request.POST.copy()
    if fresh_token or _parse_uuid(data.get('checkout_token')) is None:
        data['checkout_token'] = str(uuid.uuid4())
    form = CheckoutForm(account, data=data)
    q, bad_region = _quote_for(cart, form, data)
    data['expected_total'] = str(q.total) if q else ''
    form.is_valid()
    return _render_checkout(request, cart, form, q, error=error, bad_region=bad_region)


def _order_url(account, order):
    if account is not None:
        return reverse('orders:detail', args=[order.pk])
    return guest_order_url(order)


# only a confirmed order empties the cart; only the request that confirmed it sends the email
def _finish(request, account, cart, order):
    url = _order_url(account, order)
    if order.status == Order.Status.CONFIRMED:
        cart.clear()
        if getattr(order, 'was_created', False):
            send_order_confirmation(order, request.build_absolute_uri(url))
        messages.success(request, f'Order #{order.pk} confirmed.')
    return redirect(url)


# GET shows a fresh checkout token; POST places at most one order per token.
# place_order manages its own transactions, so this view must not run inside one.
@customer_or_guest
@require_http_methods(['GET', 'POST'])
def checkout_view(request):
    account = current_account(request)
    if request.method == 'POST':
        return _checkout_post(request, account)
    cart = Cart(request)
    if not cart.lines():
        return redirect('cart:detail')
    for name in cart.dropped:
        messages.warning(request, f'{name} is no longer available and was removed from your cart.')
    initial = _initial_from_query(account, request.GET) if 'update' in request.GET else {}
    form = CheckoutForm(account, initial=initial)
    q, bad_region = _quote_for(cart, form, request.GET)
    form.initial.update(checkout_token=uuid.uuid4(), expected_total=q.total if q else None)
    return _render_checkout(request, cart, form, q, bad_region=bad_region)


def _checkout_post(request, account):
    cart = Cart(request)
    # a retried submit gets its order back even after the cart was cleared;
    # a token that belongs to someone else is "not found"
    token = _parse_uuid(request.POST.get('checkout_token'))
    existing = Order.objects.filter(checkout_token=token).first() if token else None
    if existing is not None:
        if existing.account_id != (account.pk if account else None):
            raise Http404
        return _finish(request, account, cart, existing)

    lines = cart.lines()
    if not lines:
        messages.info(request, 'Your cart is empty.')
        return redirect('cart:detail')
    form = CheckoutForm(account, data=request.POST)
    if not form.is_valid():
        return _rerender(request, account, cart)

    # re-quote from current prices; the customer must have seen this exact total
    method = form.cleaned_data['shipping_method']
    shipping = form.shipping_data()
    try:
        q = quote(cart.subtotal(), method, shipping.country, shipping.region)
    except UnsupportedTaxRegion:
        return _rerender(request, account, cart)
    expected = form.cleaned_data['expected_total']
    if expected is None:
        return _rerender(request, account, cart, error=MSG_REVIEW_TOTAL)
    if expected != q.total:
        return _rerender(request, account, cart, error=MSG_TOTALS_CHANGED)

    card = form.selected_card()
    try:
        order = place_order(
            account, lines, contact=form.contact(), shipping=shipping, billing=form.billing_data(),
            shipping_method=method, payment_token=card.token, last4=card.last4,
            method_type=card.method_type, card_brand=card.brand,
            checkout_token=form.cleaned_data['checkout_token'],
        )
    except (PaymentDeclined, PaymentFailed):
        return _rerender(request, account, cart, error=MSG_DECLINED, fresh_token=True)
    except OutOfStock as e:
        names = ', '.join(Product.objects.filter(pk__in=e.product_ids)
                          .order_by('name').values_list('name', flat=True))
        messages.error(request, f'Sorry, {names} sold out before your order completed. '
                                'You have not been charged.')
        return redirect('cart:detail')
    except InvalidCheckout as e:
        return _rerender(request, account, cart, error=str(e))
    except Order.DoesNotExist:
        raise Http404
    return _finish(request, account, cart, order)
