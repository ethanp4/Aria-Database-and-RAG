import re
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from payments.gateway import FakeGateway, GatewayTimeout, get_gateway
from payments.test_cards import TEST_CARDS


class FakeGatewayTests(SimpleTestCase):
    def test_fake_gateway_outcomes_by_token(self):
        gw = FakeGateway()

        r = gw.authorize('tok_ok', 10)
        self.assertTrue(r.ok)
        self.assertIsNone(r.error)
        self.assertTrue(r.ref.startswith('fake_tok_ok_'))
        self.assertTrue(gw.capture(r.ref).ok)
        self.assertTrue(gw.void(r.ref).ok)

        r = gw.authorize('tok_decline', 10)
        self.assertFalse(r.ok)
        self.assertEqual(r.error, 'card_declined')

        with self.assertRaises(GatewayTimeout):
            gw.authorize('tok_timeout_authorize', 10)

        r = gw.authorize('tok_timeout_capture', 10)
        self.assertTrue(r.ok)
        with self.assertRaises(GatewayTimeout):
            gw.capture(r.ref)
        self.assertTrue(gw.void(r.ref).ok)

        r = gw.authorize('tok_nonsense', 10)
        self.assertFalse(r.ok)
        self.assertEqual(r.error, 'invalid_token')

    def test_fake_gateway_records_calls(self):
        gw = FakeGateway()
        ref = gw.authorize('tok_ok', 5).ref
        gw.capture(ref)
        gw.void(ref)
        self.assertEqual(gw.calls, [('authorize', 'tok_ok'), ('capture', ref), ('void', ref)])

    @override_settings(ARIA_PAYMENT_GATEWAY='payments.gateway.FakeGateway')
    def test_get_gateway_uses_setting(self):
        self.assertIsInstance(get_gateway(), FakeGateway)


class TestCardsTests(SimpleTestCase):
    def test_test_cards_never_hold_more_than_four_digits(self):
        self.assertTrue(TEST_CARDS)
        for card in TEST_CARDS.values():
            self.assertRegex(card.last4, r'^\d{4}$')
            for value in vars(card).values():
                self.assertFalse(re.fullmatch(r'\d{5,}', str(value)))
