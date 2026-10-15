from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('orders/', views.history_view, name='history'),
    path('orders/find/', views.lookup_view, name='lookup'),
    path('orders/guest/<int:order_id>/<str:key>/', views.guest_detail_view, name='guest_detail'),
    path('orders/<int:order_id>/', views.detail_view, name='detail'),
]
