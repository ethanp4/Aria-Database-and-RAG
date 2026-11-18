from django.urls import path

from . import views

app_name = 'analytics'

urlpatterns = [
    path('analytics/', views.dashboard_view, name='dashboard'),
    path('analytics/data/', views.data_view, name='data'),
]
