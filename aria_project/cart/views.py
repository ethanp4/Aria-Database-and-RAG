from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import customer_or_guest
from products.models import Product

from .cart import Cart
from .forms import AddToCartForm, UpdateCartForm


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
