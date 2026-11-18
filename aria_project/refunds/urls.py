from django.urls import path

from . import views

app_name = 'refunds'

# UI prototype only: there is no Refund model yet (planned in schema.sql). Every view here
# is GET-only and writes nothing; the steps are selected with ?step= / ?state=.
urlpatterns = [
    path('orders/<int:order_id>/refund/', views.request_view, name='request'),
    path('staff/refunds/', views.staff_queue_view, name='staff_queue'),
    path('staff/refunds/review/', views.staff_review_view, name='staff_review'),
]
