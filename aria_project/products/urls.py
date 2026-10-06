from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('products/new/', views.product_create_view, name='product_create'),
    path('categories/new/', views.category_create_view, name='category_create'),
    path(
        'categories/<int:category_id>/edit/',
        views.category_edit_view,
        name='category_edit',
    ),
    path(
        'products/<int:product_id>/edit/',
        views.product_edit_view,
        name='product_edit',
    ),
    path('browse/', views.browse_view, name='browse'),
]