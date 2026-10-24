import math

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.aggregates import Count
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db import transaction

from accounts.models import Account, Profile
from accounts.permissions import ROLE_ADMIN, role_required
from cart.forms import AddToCartForm
from .forms import BrowseFiltersForm, CategoryForm, ProductForm
from .models import Category, InventoryMovement, Product


# at most 10 page links, centred on the current page where possible
def page_window(page_obj, size=10):
    paginator = page_obj.paginator
    num_pages = paginator.num_pages
    if num_pages <= size:
        return paginator.page_range
    start_page = max(1, min(page_obj.number - size // 2, num_pages - size + 1))
    return range(start_page, start_page + size)


# sortable columns per dashboard table: url key -> model field.
# only these keys are accepted from the query string; anything else falls back to the default
PRODUCT_SORTS = {
    'name': 'name', 'sku': 'sku', 'price': 'unit_price', 'stock': 'stock_quantity',
    'category': 'category__name', 'status': 'is_active',
}
CATEGORY_SORTS = {'name': 'name', 'products': 'product_count'}
MOVEMENT_SORTS = {
    'product': 'product__name', 'qty': 'change_qty', 'reason': 'reason', 'date': 'created_at',
}
PROFILE_SORTS = {
    'username': 'account__username', 'first': 'first_name', 'last': 'last_name',
    'email': 'email', 'created': 'created_at', 'updated': 'updated_at',
}


# each dashboard table sorts and pages on its own query params ({prefix}_sort, {prefix}_page),
# so changing one table leaves the others where they were
def paginate(request, queryset, per_page, prefix, sorts, default_sort):
    page_param, sort_param = f'{prefix}_page', f'{prefix}_sort'

    sort = request.GET.get(sort_param, default_sort)
    if sort.removeprefix('-') not in sorts:
        sort = default_sort
    descending = sort.startswith('-')
    field = sorts[sort.removeprefix('-')]
    # pk as a tiebreaker keeps rows from shifting between pages
    queryset = queryset.order_by(f'-{field}' if descending else field,
                                 '-pk' if descending else 'pk')

    page_obj = Paginator(queryset, per_page).get_page(request.GET.get(page_param))
    query_params = request.GET.copy()
    query_params.pop(page_param, None)

    # header links: clicking the current column flips direction, others start ascending;
    # a new sort goes back to page 1
    sort_links = {}
    for key in sorts:
        link_params = query_params.copy()
        if sort == key:
            link_params[sort_param], direction = f'-{key}', 'asc'
        elif sort == f'-{key}':
            link_params[sort_param], direction = key, 'desc'
        else:
            link_params[sort_param], direction = key, None
        sort_links[key] = {'url': '?' + link_params.urlencode(), 'direction': direction}

    return {
        'page_obj': page_obj,
        'page_range': page_window(page_obj),
        'query_string': query_params.urlencode(),
        'param': page_param,
        'sort_links': sort_links,
    }


@role_required(ROLE_ADMIN)
def dashboard_view(request):
    product_pages = paginate(
        request, Product.objects.select_related('category'),
        20, 'products', PRODUCT_SORTS, 'name',
    )
    category_pages = paginate(
        request, Category.objects.annotate(product_count=Count('product')),
        10, 'categories', CATEGORY_SORTS, 'name',
    )
    movement_pages = paginate(
        request, InventoryMovement.objects.select_related('product'),
        10, 'movements', MOVEMENT_SORTS, '-date',
    )
    profile_pages = paginate(
        request, Profile.objects.select_related('account'),
        10, 'profiles', PROFILE_SORTS, 'first',
    )

    context = {
        'account_count': Account.objects.count(),

        'products': product_pages['page_obj'].object_list,
        'product_pages': product_pages,
        'product_count': product_pages['page_obj'].paginator.count,

        'inventory_movements': movement_pages['page_obj'].object_list,
        'movement_pages': movement_pages,
        'inventory_movement_count': movement_pages['page_obj'].paginator.count,

        'categories': category_pages['page_obj'].object_list,
        'category_pages': category_pages,
        'category_count': category_pages['page_obj'].paginator.count,

        'profiles': profile_pages['page_obj'].object_list,
        'profile_pages': profile_pages,
        'profile_count': profile_pages['page_obj'].paginator.count,
    }
    return render(request, 'products/dashboard.html', context)


def browse_view(request):
    filter_data = request.GET.copy()
    if not filter_data.get('per_page'):
        filter_data['per_page'] = '20'
    form = BrowseFiltersForm(filter_data)
    products = Product.objects.filter(is_active=True).select_related('category')
    per_page = 20
    if form.is_valid():
        filters = form.cleaned_data
        query = filters['q'].strip()
        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(sku__icontains=query)
            )
        if filters['category']:
            products = products.filter(category=filters['category'])
        if filters['min_price'] is not None:
            products = products.filter(unit_price__gte=filters['min_price'])
        if filters['max_price'] is not None:
            products = products.filter(unit_price__lte=filters['max_price'])
        if filters['in_stock']:
            products = products.filter(stock_quantity__gt=0)

        per_page = int(filters['per_page'] or 20)
        sort = filters['sort'] or 'name'
        if sort == 'price_low':
            products = products.order_by('unit_price', 'name')
        elif sort == 'price_high':
            products = products.order_by('-unit_price', 'name')
        else:
            products = products.order_by('name')
    else:
        products = products.order_by('name')

    result_count = products.count()
    paginator = Paginator(products, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)

    return render(request, 'products/browse.html', {
        'products': page_obj.object_list,
        'filter_form': form,
        'result_count': result_count,
        'page_obj': page_obj,
        'page_range': page_window(page_obj),
        'query_string': query_params.urlencode(),
    })


# public product page; inactive products 404
def product_detail_view(request, product_id):
    product = get_object_or_404(
        Product.objects.select_related('category'), pk=product_id, is_active=True)
    return render(request, 'products/product_details.html', {
        'product': product,
        'add_form': AddToCartForm(),
    })


@role_required(ROLE_ADMIN)
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


# the row is locked while the form is checked and saved, so a checkout can't commit in
# between; a form opened before a sale (stale original_stock) is rejected, not saved
@role_required(ROLE_ADMIN)
def product_edit_view(request, product_id):
    product = get_object_or_404(Product, product_id=product_id)
    if request.method == 'POST':
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product.pk)
            locked_stock = product.stock_quantity
            form = ProductForm(request.POST, instance=product)
            if form.is_valid():
                change_qty = form.cleaned_data['stock_quantity'] - locked_stock
                product = form.save(commit=False)
                update_fields = [f for f in ProductForm.Meta.fields
                                 if f != 'stock_quantity' or change_qty]
                product.save(update_fields=[*update_fields, 'updated_at'])
                if change_qty:
                    InventoryMovement.objects.create(
                        product=product,
                        change_qty=change_qty,
                        reason=form.cleaned_data['inventory_reason'],
                    )
                messages.success(request, f'{product.name} was updated.')
                return redirect('products:dashboard')
            # failed validation may have copied posted values onto the instance
            product.refresh_from_db()
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


@role_required(ROLE_ADMIN)
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

@role_required(ROLE_ADMIN)
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