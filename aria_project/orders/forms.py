from django import forms


class OrderLookupForm(forms.Form):
    order_number = forms.IntegerField(min_value=1, max_value=2**62)
    email = forms.EmailField()
