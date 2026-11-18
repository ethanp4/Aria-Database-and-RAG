from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('ask-aria/', views.ask_view, name='ask'),
]
