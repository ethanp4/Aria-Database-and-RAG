from django import forms

from accounts.models import Address, Profile
from accounts.regions import normalize_region
from orders.pricing import SHIPPING_METHODS
from orders.services import AddressData, Contact
from payments.test_cards import TEST_CARDS

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


def _text(autocomplete):
    return forms.TextInput(attrs={'class': 'form-control', 'autocomplete': autocomplete})


def _shipping_label(m):
    free = f', free over ${m.free_over}' if m.free_over is not None else ''
    return f'{m.label} (${m.price}{free})'


# a guest's typed address; region is normalized to the 2-letter code
class CheckoutAddressForm(forms.Form):
    line1 = forms.CharField(label='Address line 1', max_length=255, widget=_text('address-line1'))
    line2 = forms.CharField(label='Address line 2', max_length=255, required=False,
                            widget=_text('address-line2'))
    city = forms.CharField(max_length=100, widget=_text('address-level2'))
    region = forms.CharField(label='Province / state', max_length=100,
                             help_text='2-letter code, e.g. ON or WA.', widget=_text('address-level1'))
    postal_code = forms.CharField(max_length=20, widget=_text('postal-code'))
    country = forms.ChoiceField(choices=Address.Country.choices,
                                widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, prefix, data=None, initial=None):
        super().__init__(data=data, initial=initial, prefix=prefix)

    def clean(self):
        cleaned = super().clean()
        country, region = cleaned.get('country'), cleaned.get('region')
        if country and region:
            try:
                cleaned['region'] = normalize_region(country, region)
            except forms.ValidationError as e:
                self.add_error('region', e)
        return cleaned

    def to_address_data(self):
        c = self.cleaned_data
        return AddressData(c['line1'], c['line2'] or None, c['city'], c['region'],
                           c['postal_code'], c['country'])


class _AddressChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj} ({obj.get_address_type_display()})'


def _unprefix(initial, prefix):
    start = prefix + '-'
    return {k[len(start):]: v for k, v in initial.items() if k.startswith(start)}


# account is None for a guest. a customer's address choices are scoped to their own
# address book, so another customer's address id fails validation.
class CheckoutForm(forms.Form):
    billing_same = forms.BooleanField(
        label='Billing address is the same as shipping', required=False, initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    shipping_method = forms.ChoiceField(
        choices=[(m.code, _shipping_label(m)) for m in SHIPPING_METHODS.values()],
        initial='STANDARD', widget=forms.RadioSelect(attrs={'class': 'form-check-input'}))
    # labels only; the gateway token is looked up server side and never rendered
    test_card = forms.ChoiceField(
        label='Test card', choices=[(c.key, c.label) for c in TEST_CARDS.values()],
        initial='visa_ok', widget=forms.RadioSelect(attrs={'class': 'form-check-input'}))
    checkout_token = forms.UUIDField(widget=forms.HiddenInput)
    expected_total = forms.DecimalField(max_digits=10, decimal_places=2, required=False,
                                        widget=forms.HiddenInput)

    def __init__(self, account, data=None, initial=None):
        initial = dict(initial or {})
        super().__init__(data=data, initial=initial)
        self.account = account
        self.ship_form = self.bill_form = None
        self.validate_billing = False
        if account is not None:
            own = Address.objects.filter(account=account)
            select = {'class': 'form-select'}
            self.fields['shipping_address'] = _AddressChoiceField(
                queryset=own.filter(address_type=Address.AddressType.SHIPPING)
                .order_by('-is_default', 'address_id'),
                label='Shipping address', empty_label=None, widget=forms.Select(attrs=select))
            self.fields['billing_address'] = _AddressChoiceField(
                queryset=own.order_by('address_type', '-is_default', 'address_id'),
                label='Billing address', required=False, empty_label='Choose a billing address',
                widget=forms.Select(attrs=select))
            if 'shipping_address' not in initial:
                first = self.fields['shipping_address'].queryset.first()
                self.initial['shipping_address'] = first.pk if first else None
            if 'billing_address' not in initial:
                default = own.filter(address_type=Address.AddressType.BILLING, is_default=True).first()
                self.initial['billing_address'] = default.pk if default else None
        else:
            self.fields['contact_name'] = forms.CharField(label='Full name', max_length=200,
                                                          widget=_text('name'))
            self.fields['contact_email'] = forms.EmailField(
                label='Email', max_length=254,
                widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email'}))
            self.ship_form = CheckoutAddressForm('ship', data=data, initial=_unprefix(initial, 'ship'))
            # billing fields are only bound and validated when the box is unchecked;
            # otherwise the typed values are kept as initial so they are not lost
            self.validate_billing = data is not None and not self['billing_same'].data
            if self.validate_billing:
                self.bill_form = CheckoutAddressForm('bill', data=data)
            else:
                bill_initial = _unprefix(dict(data.items()) if data is not None else initial, 'bill')
                self.bill_form = CheckoutAddressForm('bill', initial=bill_initial)
            self.bill_form.use_required_attribute = False

    def is_valid(self):
        ok = super().is_valid()
        if self.account is None:
            ok = self.ship_form.is_valid() and ok
            if self.validate_billing:
                ok = self.bill_form.is_valid() and ok
        return ok

    def clean(self):
        cleaned = super().clean()
        if (self.account is not None and not cleaned.get('billing_same')
                and not cleaned.get('billing_address')):
            self.add_error('billing_address', 'Choose a billing address.')
        return cleaned

    def shipping_data(self):
        if self.account is not None:
            return AddressData.from_address(self.cleaned_data['shipping_address'])
        return self.ship_form.to_address_data()

    def billing_data(self):
        if self.cleaned_data['billing_same']:
            return self.shipping_data()
        if self.account is not None:
            return AddressData.from_address(self.cleaned_data['billing_address'])
        return self.bill_form.to_address_data()

    # customer: profile name and email when there is a profile, else the username and no email
    def contact(self):
        if self.account is None:
            return Contact(self.cleaned_data['contact_name'], self.cleaned_data['contact_email'])
        profile = Profile.objects.filter(account=self.account).first()
        if profile is None:
            return Contact(self.account.username, None)
        name = f'{profile.first_name or ""} {profile.last_name or ""}'.strip()
        return Contact(name or self.account.username, profile.email)

    def selected_card(self):
        return TEST_CARDS[self.cleaned_data['test_card']]
