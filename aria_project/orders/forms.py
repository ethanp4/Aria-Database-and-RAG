from django import forms

from orders.models import Carrier, Order


class OrderLookupForm(forms.Form):
    order_number = forms.IntegerField(min_value=1, max_value=2**62)
    email = forms.EmailField()


class MarkShippedForm(forms.Form):
    carrier = forms.ModelChoiceField(queryset=Carrier.objects.order_by('name'))
    tracking_number = forms.CharField(max_length=100)


class StaffOrderFilterForm(forms.Form):
    status = forms.ChoiceField(required=False, choices=[('', 'All statuses'), *Order.Status.choices])
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
