from django import forms
from django.db.models import Count
from django.core.validators import MinValueValidator

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


class BrowseFiltersForm(forms.Form):
    PAGE_SIZE_CHOICES = (
        ('20', '20 per page'),
        ('50', '50 per page'),
        ('100', '100 per page'),
    )
    SORT_CHOICES = (
        ('name', 'Name'),
        ('price_low', 'Price: low to high'),
        ('price_high', 'Price: high to low'),
    )

    q = forms.CharField(
        required=False,
        label='Search products',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search products...',
            'aria-label': 'Search products',
        }),
    )
    category = CategoryChoiceField(
        queryset=Category.objects.none(),
        required=False,
        label='Category',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    min_price = forms.DecimalField(
        required=False,
        label='Minimum price',
        validators=[MinValueValidator(0)],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '0.01',
        }),
    )
    max_price = forms.DecimalField(
        required=False,
        label='Maximum price',
        validators=[MinValueValidator(0)],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '0.01',
        }),
    )
    in_stock = forms.BooleanField(
        required=False,
        label='In stock only',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    sort = forms.ChoiceField(
        required=False,
        label='Sort by',
        choices=SORT_CHOICES,
        initial='name',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    per_page = forms.ChoiceField(
        required=False,
        label='Results per page',
        choices=PAGE_SIZE_CHOICES,
        initial='20',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.annotate(
            product_count=Count('product'),
        ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        min_price = cleaned_data.get('min_price')
        max_price = cleaned_data.get('max_price')
        if min_price is not None and max_price is not None and min_price > max_price:
            self.add_error('max_price', 'Maximum price must be at least the minimum price.')
        return cleaned_data


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
