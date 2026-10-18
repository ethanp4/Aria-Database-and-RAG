"""TEMPORARY fake test cards for FakeGateway. Only a token and last 4 digits are held."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TestCard:
    __test__ = False  # not a test case; keep test runners from collecting it

    key: str
    label: str
    token: str
    last4: str
    brand: str
    method_type: str


def _card(key, label, token, last4, brand):
    return TestCard(key, label, token, last4, brand, 'CREDIT_CARD')


TEST_CARDS = {c.key: c for c in [
    _card('visa_ok', 'Visa •••• 4242 (approves)', 'tok_ok', '4242', 'Visa'),
    _card('mc_ok', 'Mastercard •••• 4444 (approves)', 'tok_ok', '4444', 'Mastercard'),
    _card('visa_decline', 'Visa •••• 0002 (declined)', 'tok_decline', '0002', 'Visa'),
    _card('visa_timeout', 'Visa •••• 0119 (capture times out)', 'tok_timeout_capture', '0119', 'Visa'),
]}
