from django.urls import path

from . import views

app_name = 'cart'

urlpatterns = [
    path('cart/', views.cart_detail_view, name='detail'),
    path('cart/add/<int:product_id>/', views.cart_add_view, name='add'),
    path('cart/update/<int:product_id>/', views.cart_update_view, name='update'),
]
