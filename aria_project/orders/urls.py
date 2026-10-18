from django.urls import path

from . import staff_views, views

app_name = 'orders'

urlpatterns = [
    path('staff/orders/', staff_views.staff_list_view, name='staff_list'),
    path('staff/orders/<int:order_id>/', staff_views.staff_detail_view, name='staff_detail'),
    path('staff/orders/<int:order_id>/ship/', staff_views.staff_mark_shipped_view, name='staff_mark_shipped'),
    path('orders/', views.history_view, name='history'),
    path('orders/find/', views.lookup_view, name='lookup'),
    path('orders/guest/<int:order_id>/<str:key>/', views.guest_detail_view, name='guest_detail'),
    path('orders/<int:order_id>/', views.detail_view, name='detail'),
]
