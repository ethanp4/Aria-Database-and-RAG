from django import forms

from .models import Account, Address, Profile
from .regions import normalize_region


class RegisterForm(forms.Form):
    username = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'username',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
        min_length=4,
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'new-password',
        }),
    )

    def clean_username(self):
        username = self.cleaned_data['username'].lower()
        if Account.objects.filter(username=username).exists():
            raise forms.ValidationError('An account with this username already exists.')
        return username

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm_password = cleaned.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'username',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'current-password',
        }),
    )

class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['first_name', 'last_name', 'phone', 'email']

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['address_type', 'line1', 'line2', 'city', 'region', 'postal_code', 'country', 'is_default']
        widgets = {
            'address_type': forms.Select(attrs={'class': 'form-select'}),
            'line1': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'address-line1'}),
            'line2': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'address-line2'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'address-level2'}),
            'region': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'address-level1'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'postal-code'}),
            'country': forms.Select(attrs={'class': 'form-select'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {'region': '2-letter code, e.g. ON or WA.'}

    # region must be a valid 2-letter code for the chosen country
    def clean(self):
        cleaned = super().clean()
        country = cleaned.get('country')
        region = cleaned.get('region')
        if country and region:
            try:
                cleaned['region'] = normalize_region(country, region)
            except forms.ValidationError as e:
                self.add_error('region', e)
        return cleaned
