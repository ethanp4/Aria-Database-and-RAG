from types import SimpleNamespace

from django.test import SimpleTestCase

from payments.masking import mask_payment


class MaskingTests(SimpleTestCase):
    def test_mask_payment_formats_brand_and_last4(self):
        p = SimpleNamespace(last4='4242', card_brand='Visa')
        self.assertEqual(mask_payment(p), 'Visa •••• 4242')
        self.assertEqual(mask_payment(SimpleNamespace(last4='4242', card_brand='')), '•••• 4242')

    def test_mask_payment_without_last4(self):
        self.assertEqual(mask_payment(SimpleNamespace(last4=None, card_brand='Visa')), '•••• ----')
