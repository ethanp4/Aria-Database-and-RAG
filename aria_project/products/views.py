from django.contrib import messages
from django.db.models.aggregates import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db import transaction

from accounts.models import Account
from .forms import CategoryForm, ProductForm
from .models import Category, InventoryMovement, Product


def dashboard_view(request):
    context = {
        'account_count': Account.objects.count(),
        'product_count': Product.objects.count(),

        
        'products': Product.objects.all(),

        'inventory_movements': InventoryMovement.objects.select_related('product').order_by('-created_at')[:10],
        'inventory_movement_count': InventoryMovement.objects.count(),

        'categories': Category.objects.annotate(product_count=Count('product')).order_by('name'),
        'category_count': Category.objects.count(),
    }
    return render(request, 'products/dashboard.html', context)


def browse_view(request):
    products = Product.objects.filter(is_active=True)
    return render(request, 'products/browse.html', {'products': products})


def product_create_view(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save()
            messages.success(request, f'{product.name} was created.')
            return redirect('products:dashboard')
    else:
        initial = {}
        category_id = request.GET.get('category')
        if category_id and Category.objects.filter(pk=category_id).exists():
            initial['category'] = category_id
        form = ProductForm(initial=initial)

    return render(request, 'products/product_form.html', {
        'form': form,
        'page_title': 'Add product',
        'submit_label': 'Create product',
    })


def product_edit_view(request, product_id):
    product = get_object_or_404(Product, product_id=product_id)
    if request.method == 'POST':
        current_stock_quantity = product.stock_quantity
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            updated_product = form.save(commit=False)
            change_qty = updated_product.stock_quantity - current_stock_quantity
            with transaction.atomic():
                updated_product.save()
                if change_qty:
                    InventoryMovement.objects.create(
                        product=updated_product,
                        change_qty=change_qty,
                        reason=form.cleaned_data['inventory_reason'],
                    )
            product = updated_product
            messages.success(request, f'{product.name} was updated.')
            return redirect('products:dashboard')
    else:
        initial = {}
        category_id = request.GET.get('category')
        if category_id and Category.objects.filter(pk=category_id).exists():
            initial['category'] = category_id
        form = ProductForm(instance=product, initial=initial)

    return render(request, 'products/product_form.html', {
        'form': form,
        'product': product,
        'page_title': f'Edit {product.name}',
        'submit_label': 'Save changes',
    })


def category_create_view(request):
    for_product = request.POST.get(
        'for_product',
        request.GET.get('for_product', ''),
    )
    product = None
    if for_product:
        product = get_object_or_404(Product, product_id=for_product)

    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'{category.name} was created.')
            if product:
                url = reverse(
                    'products:product_edit',
                    kwargs={'product_id': product.product_id},
                )
            else:
                url = reverse('products:product_create')
            return redirect(f'{url}?category={category.pk}')
    else:
        form = CategoryForm()

    return render(request, 'products/category_form.html', {
        'form': form,
        'product': product
    })

def category_edit_view(request, category_id):
    category = get_object_or_404(Category, category_id=category_id)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'{category.name} was updated.')
            return redirect('products:dashboard')
    else:
        form = CategoryForm(instance=category)

    return render(request, 'products/category_form.html', {
        'form': form,
        'category': category,
        'page_title': f'Edit {category.name}',
        'submit_label': 'Save changes',
    })