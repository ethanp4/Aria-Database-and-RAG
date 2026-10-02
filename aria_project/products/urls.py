from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('browse/', views.browse_view, name='browse'),
]