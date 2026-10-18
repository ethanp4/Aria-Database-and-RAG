from decimal import Decimal

from django.test import SimpleTestCase

from accounts.regions import REGIONS
from orders.pricing import UnsupportedTaxRegion, quote, shipping_cost, tax_rate_for


class ShippingTests(SimpleTestCase):
    def test_standard_shipping_free_at_or_over_150(self):
        self.assertEqual(shipping_cost('STANDARD', Decimal('149.99')), Decimal('12.00'))
        self.assertEqual(shipping_cost('STANDARD', Decimal('150.00')), Decimal('0.00'))

    def test_express_and_priority_never_free(self):
        self.assertEqual(shipping_cost('EXPRESS', Decimal('500.00')), Decimal('20.00'))
        self.assertEqual(shipping_cost('PRIORITY', Decimal('500.00')), Decimal('35.00'))

    def test_unknown_shipping_method_raises(self):
        with self.assertRaises(ValueError):
            shipping_cost('DRONE', Decimal('10.00'))


class QuoteTests(SimpleTestCase):
    def test_ontario_taxes_subtotal_and_shipping(self):
        q = quote(Decimal('100.00'), 'EXPRESS', 'CA', 'on')
        self.assertEqual(q.shipping_cost, Decimal('20.00'))
        self.assertEqual(q.tax_amount, Decimal('15.60'))
        self.assertEqual(q.total, Decimal('135.60'))
        self.assertEqual(q.tax_label, 'HST 13%')

    def test_quebec_rounds_half_up_to_cents(self):
        q = quote(Decimal('10.00'), 'PRIORITY', 'CA', 'QC')
        self.assertEqual(q.tax_amount, Decimal('6.74'))
        self.assertEqual(q.total, Decimal('51.74'))

    def test_us_taxes_subtotal_only(self):
        q = quote(Decimal('100.00'), 'PRIORITY', 'US', 'WA')
        self.assertEqual(q.tax_amount, Decimal('6.50'))
        self.assertEqual(q.total, Decimal('141.50'))

    def test_zero_rate_state(self):
        q = quote(Decimal('100.00'), 'STANDARD', 'US', 'OR')
        self.assertEqual(q.tax_amount, Decimal('0.00'))

    def test_every_region_has_a_tax_rate(self):
        self.assertEqual(len(REGIONS['CA']), 13)
        self.assertEqual(len(REGIONS['US']), 51)
        for country in ('CA', 'US'):
            for code in REGIONS[country]:
                tax_rate_for(country, code)

    def test_unknown_region_raises_unsupported_tax_region(self):
        with self.assertRaises(UnsupportedTaxRegion):
            tax_rate_for('CA', 'Ontaro')
