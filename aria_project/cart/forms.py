from django import forms

from .cart import MAX_QUANTITY


class AddToCartForm(forms.Form):
    quantity = forms.IntegerField(
        min_value=1, max_value=MAX_QUANTITY, initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': MAX_QUANTITY}),
    )


class UpdateCartForm(forms.Form):
    quantity = forms.IntegerField(
        min_value=0, max_value=MAX_QUANTITY,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': MAX_QUANTITY}),
    )
