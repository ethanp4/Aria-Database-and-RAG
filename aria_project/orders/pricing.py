# TEMPORARY placeholder rates, statewide/provincial only, as of 2026.
# Replace with Stripe Tax when the payment API is connected; see docs/follow-ups.md.
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal('0.01')


def _money(value):
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ShippingMethod:
    code: str
    label: str
    price: Decimal
    free_over: Decimal | None


SHIPPING_METHODS = {
    'STANDARD': ShippingMethod('STANDARD', 'Standard', Decimal('12.00'), Decimal('150.00')),
    'EXPRESS': ShippingMethod('EXPRESS', 'Express', Decimal('20.00'), None),
    'PRIORITY': ShippingMethod('PRIORITY', 'Priority', Decimal('35.00'), None),
}


# free shipping applies when subtotal reaches the method's free_over threshold
def shipping_cost(method, subtotal):
    try:
        m = SHIPPING_METHODS[method]
    except KeyError:
        raise ValueError(f'Unknown shipping method: {method}')
    if m.free_over is not None and subtotal >= m.free_over:
        return Decimal('0.00')
    return m.price


@dataclass(frozen=True)
class TaxRate:
    label: str
    rate: Decimal
    taxes_shipping: bool


class UnsupportedTaxRegion(Exception):
    def __init__(self, country, region):
        super().__init__(f'No tax rate for {country}/{region}')
        self.country = country
        self.region = region


# Canada: (label, percent); applies to goods and shipping
_CA = {
    'AB': ('GST 5%', '5'), 'BC': ('GST+PST 12%', '12'), 'MB': ('GST+RST 12%', '12'),
    'NB': ('HST 15%', '15'), 'NL': ('HST 15%', '15'), 'NS': ('HST 14%', '14'),
    'NT': ('GST 5%', '5'), 'NU': ('GST 5%', '5'), 'ON': ('HST 13%', '13'),
    'PE': ('HST 15%', '15'), 'QC': ('GST+QST 14.975%', '14.975'),
    'SK': ('GST+PST 11%', '11'), 'YT': ('GST 5%', '5'),
}

# US: percent; applies to goods only
_US = {
    'AL': '4', 'AK': '0', 'AZ': '5.6', 'AR': '6.5', 'CA': '7.25', 'CO': '2.9',
    'CT': '6.35', 'DE': '0', 'DC': '6', 'FL': '6', 'GA': '4', 'HI': '4', 'ID': '6',
    'IL': '6.25', 'IN': '7', 'IA': '6', 'KS': '6.5', 'KY': '6', 'LA': '5', 'ME': '5.5',
    'MD': '6', 'MA': '6.25', 'MI': '6', 'MN': '6.875', 'MS': '7', 'MO': '4.225',
    'MT': '0', 'NE': '5.5', 'NV': '6.85', 'NH': '0', 'NJ': '6.625', 'NM': '4.875',
    'NY': '4', 'NC': '4.75', 'ND': '5', 'OH': '5.75', 'OK': '4.5', 'OR': '0',
    'PA': '6', 'RI': '7', 'SC': '6', 'SD': '4.2', 'TN': '7', 'TX': '6.25', 'UT': '6.1',
    'VT': '6', 'VA': '5.3', 'WA': '6.5', 'WV': '6', 'WI': '5', 'WY': '4',
}

TAX_RATES = {
    'CA': {
        code: TaxRate(label, Decimal(pct) / 100, True) for code, (label, pct) in _CA.items()
    },
    'US': {
        code: TaxRate(f'{code} sales tax', Decimal(pct) / 100, False) for code, pct in _US.items()
    },
}


def tax_rate_for(country, region):
    code = (region or '').strip().upper()
    try:
        return TAX_RATES[country][code]
    except KeyError:
        raise UnsupportedTaxRegion(country, region)


@dataclass(frozen=True)
class Quote:
    subtotal: Decimal
    shipping_cost: Decimal
    tax_amount: Decimal
    tax_label: str
    total: Decimal


def quote(subtotal, shipping_method, country, region):
    shipping = shipping_cost(shipping_method, subtotal)
    rate = tax_rate_for(country, region)
    taxable = subtotal + shipping if rate.taxes_shipping else subtotal
    tax = _money(taxable * rate.rate)
    return Quote(subtotal, shipping, tax, rate.label, subtotal + shipping + tax)
