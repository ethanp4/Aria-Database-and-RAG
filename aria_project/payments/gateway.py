"""TEMPORARY. No real money moves. Replace with a Stripe gateway; see docs/follow-ups.md."""
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class GatewayResult:
    ok: bool
    ref: str
    error: str | None = None


class GatewayTimeout(Exception):
    pass


class PaymentGateway(Protocol):
    def authorize(self, token: str, amount) -> GatewayResult: ...
    def capture(self, ref: str) -> GatewayResult: ...
    def void(self, ref: str) -> GatewayResult: ...


# outcomes depend only on the token, which is embedded in the ref
class FakeGateway:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def _record(self, action, value):
        with self._lock:
            self.calls.append((action, value))

    @staticmethod
    def _token_from_ref(ref):
        return ref.removeprefix('fake_').rsplit('_', 1)[0]

    def authorize(self, token, amount):
        self._record('authorize', token)
        if token == 'tok_timeout_authorize':
            raise GatewayTimeout('authorize timed out')
        if token == 'tok_decline':
            return GatewayResult(ok=False, ref='', error='card_declined')
        if token in ('tok_ok', 'tok_timeout_capture'):
            return GatewayResult(ok=True, ref=f'fake_{token}_{uuid.uuid4().hex}', error=None)
        return GatewayResult(ok=False, ref='', error='invalid_token')

    def capture(self, ref):
        self._record('capture', ref)
        if self._token_from_ref(ref) == 'tok_timeout_capture':
            raise GatewayTimeout('capture timed out')
        return GatewayResult(ok=True, ref=ref, error=None)

    def void(self, ref):
        self._record('void', ref)
        return GatewayResult(ok=True, ref=ref, error=None)


def get_gateway() -> PaymentGateway:
    return import_string(settings.ARIA_PAYMENT_GATEWAY)()
