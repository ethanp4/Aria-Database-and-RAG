from django.urls import path

from .views import stream_chat

app_name = 'chatbot'

urlpatterns = [
    path('stream/', stream_chat, name='stream'),
]
