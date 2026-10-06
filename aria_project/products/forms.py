from django import forms
from django.db.models import Count

from .models import Category, InventoryMovement, Product


class CategoryChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        item_word = 'item' if obj.product_count == 1 else 'items'
        return f'{obj.name} ({obj.product_count} {item_word})'


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'description')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
            }),
        }


class ProductForm(forms.ModelForm):
    inventory_reason = forms.ChoiceField(
        choices=[('', 'Select a reason')],
        required=False,
        label='Reason for stock change',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    category = CategoryChoiceField(
        queryset=Category.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Product
        fields = (
            'sku',
            'name',
            'description',
            'category',
            'unit_price',
            'currency',
            'stock_quantity',
            'reorder_level',
            'is_active',
        )
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'currency': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': '3',
            }),
            'stock_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
            }),
            'reorder_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance._state.adding:
            self.fields.pop('inventory_reason')
        # Query the number of products in that category for displaying in the dropdown
        self.fields['category'].queryset = Category.objects.annotate(
            product_count=Count('product'),
        ).order_by('name')

        if 'inventory_reason' in self.fields:
            self.fields['inventory_reason'].choices = [
                ('', 'Select a reason'),
                *[
                    (value, label)
                    for value, label in InventoryMovement.Reason.choices
                ],
            ]

    def clean(self):
        cleaned_data = super().clean()
        stock_quantity = cleaned_data.get('stock_quantity')
        current_quantity = self.instance.stock_quantity
        if (
            not self.instance._state.adding
            and stock_quantity is not None
            and stock_quantity != current_quantity
            and not cleaned_data.get('inventory_reason')
        ):
            self.add_error(
                'inventory_reason',
                'Select a reason when changing stock quantity.',
            )
        return cleaned_data
