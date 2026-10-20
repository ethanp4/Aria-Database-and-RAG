"""Object-oriented model of an Aria Order and its mapping to/from the order_document JSONB.

The same entity exists three ways:
  * relational: orders + order_items + payments + refunds + carriers (SQL_Scripts/01_tables.sql)
  * objects:    the dataclasses below
  * document:   order_document.doc, one JSONB value per order (01_order_document.sql)

Relationships shown here:
  * composition: an Order owns its OrderItems, two Addresses, a Payment, a Shipment and its
    RefundSummaries; they have no life outside the order document
  * inheritance: ShippingAddress / BillingAddress extend Address;
                 CardPayment / WalletPayment extend PaymentSummary
  * association: an Order references a Customer (or none, for a guest checkout)

Only safe fields are mapped: no payment token and no risk score, so a document can be handed
to an API client, the customer's order page or the chatbot as-is.

Standard library only. Run it to load sample_order_document.json, validate it and confirm
that JSON -> objects -> JSON gives back the identical document:
    python order_model.py
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Optional

SCHEMA_VERSION = 1


class OrderStatus(str, Enum):
    PENDING_PAYMENT = 'PENDING_PAYMENT'
    PAYMENT_FAILED = 'PAYMENT_FAILED'
    OUT_OF_STOCK = 'OUT_OF_STOCK'
    CONFIRMED = 'CONFIRMED'
    SHIPPED = 'SHIPPED'
    DELIVERED = 'DELIVERED'
    CANCELLED = 'CANCELLED'
    REFUNDED = 'REFUNDED'

    @property
    def is_paid(self) -> bool:
        return self in {OrderStatus.CONFIRMED, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.REFUNDED}


def _ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


# --- association --------------------------------------------------------------
@dataclass(frozen=True)
class Customer:
    account_id: int
    username: str

    def to_dict(self) -> dict[str, Any]:
        return {'account_id': self.account_id, 'username': self.username}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Customer:
        return cls(d['account_id'], d['username'])


# --- inheritance: Address -----------------------------------------------------
@dataclass(frozen=True)
class Address:
    kind: ClassVar[str] = 'address'
    line1: str
    city: str
    region: str
    postal_code: str
    country: str
    line2: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {'kind': self.kind, 'line1': self.line1, 'line2': self.line2, 'city': self.city,
                'region': self.region, 'postal_code': self.postal_code, 'country': self.country}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Address:
        subtype = {'shipping': ShippingAddress, 'billing': BillingAddress}[d['kind']]
        return subtype(line1=d['line1'], line2=d['line2'], city=d['city'], region=d['region'],
                       postal_code=d['postal_code'], country=d['country'])


@dataclass(frozen=True)
class ShippingAddress(Address):
    kind: ClassVar[str] = 'shipping'


@dataclass(frozen=True)
class BillingAddress(Address):
    kind: ClassVar[str] = 'billing'


# --- inheritance: PaymentSummary ---------------------------------------------
@dataclass(frozen=True)
class PaymentSummary(ABC):
    """What the order shows about how it was paid. Never the token."""
    method: str
    status: str

    @property
    @abstractmethod
    def display(self) -> str: ...

    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PaymentSummary:
        if d['type'] == 'card':
            return CardPayment(method=d['method'], status=d['status'], brand=d['brand'], last4=d['last4'])
        return WalletPayment(method=d['method'], status=d['status'])


@dataclass(frozen=True)
class CardPayment(PaymentSummary):
    brand: str
    last4: str

    def __post_init__(self):
        if not (len(self.last4) == 4 and self.last4.isdigit()):
            raise ValueError('last4 must be exactly 4 digits')

    @property
    def display(self) -> str:
        return f'{self.brand} **** {self.last4}'

    def to_dict(self) -> dict[str, Any]:
        return {'type': 'card', 'method': self.method, 'brand': self.brand, 'last4': self.last4,
                'status': self.status}


@dataclass(frozen=True)
class WalletPayment(PaymentSummary):
    """PayPal and gift cards: no card number of any kind."""

    @property
    def display(self) -> str:
        return self.method.replace('_', ' ').title()

    def to_dict(self) -> dict[str, Any]:
        return {'type': 'wallet', 'method': self.method, 'status': self.status}


# --- composition parts --------------------------------------------------------
@dataclass(frozen=True)
class OrderItem:
    sku: str
    name: str
    category: str
    quantity: int
    unit_price: Decimal

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {'sku': self.sku, 'name': self.name, 'category': self.category, 'quantity': self.quantity,
                'unit_price': self.unit_price, 'line_total': self.line_total}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OrderItem:
        item = cls(d['sku'], d['name'], d['category'], d['quantity'], d['unit_price'])
        if item.line_total != d['line_total']:
            raise ValueError(f'{item.sku}: line_total {d["line_total"]} != {item.line_total}')
        return item


@dataclass(frozen=True)
class Shipment:
    method: str
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {'method': self.method, 'carrier': self.carrier, 'tracking_number': self.tracking_number,
                'tracking_url': self.tracking_url, 'shipped_at': _iso(self.shipped_at),
                'delivered_at': _iso(self.delivered_at)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Shipment:
        return cls(d['method'], d['carrier'], d['tracking_number'], d['tracking_url'],
                   _ts(d['shipped_at']), _ts(d['delivered_at']))


@dataclass(frozen=True)
class RefundSummary:
    refund_id: int
    amount: Decimal
    status: str
    reason: str
    requested_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {'refund_id': self.refund_id, 'amount': self.amount, 'status': self.status,
                'reason': self.reason, 'requested_at': _iso(self.requested_at)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RefundSummary:
        return cls(d['refund_id'], d['amount'], d['status'], d['reason'], _ts(d['requested_at']))


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
    currency: str = 'CAD'

    def to_dict(self) -> dict[str, Any]:
        return {'subtotal': self.subtotal, 'shipping': self.shipping, 'tax': self.tax,
                'total': self.total, 'currency': self.currency}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Totals:
        return cls(d['subtotal'], d['shipping'], d['tax'], d['total'], d['currency'])


# --- the aggregate root -------------------------------------------------------
@dataclass
class Order:
    order_id: int
    status: OrderStatus
    created_at: datetime
    contact_name: str
    contact_email: Optional[str]
    customer: Optional[Customer]                      # None = guest checkout
    shipping_address: ShippingAddress
    billing_address: BillingAddress
    items: list[OrderItem]
    totals: Totals
    shipment: Shipment
    payment: Optional[PaymentSummary] = None          # None while the order is still processing
    refunds: list[RefundSummary] = field(default_factory=list)
    confirmed_at: Optional[datetime] = None

    def validate(self) -> None:
        """The same rules the relational schema enforces with CHECK constraints."""
        if not self.items:
            raise ValueError('an order needs at least one item')
        if self.totals.subtotal != sum(i.line_total for i in self.items):
            raise ValueError('subtotal must equal the sum of the line totals')
        if self.totals.total != self.totals.subtotal + self.totals.shipping + self.totals.tax:
            raise ValueError('total must equal subtotal + shipping + tax')
        if self.status.is_paid and (self.payment is None or self.confirmed_at is None):
            raise ValueError(f'a {self.status.value} order needs a payment and a confirmation time')
        if self.customer is None and not self.contact_email:
            raise ValueError('a guest order needs a contact email')
        completed = sum((r.amount for r in self.refunds if r.status in ('APPROVED', 'COMPLETED')), Decimal('0'))
        if completed > self.totals.total:
            raise ValueError('refunds exceed the order total')

    @property
    def refunded_amount(self) -> Decimal:
        return sum((r.amount for r in self.refunds if r.status == 'COMPLETED'), Decimal('0'))

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': SCHEMA_VERSION,
            'order_id': self.order_id,
            'status': self.status.value,
            'created_at': _iso(self.created_at),
            'confirmed_at': _iso(self.confirmed_at),
            'customer': self.customer.to_dict() if self.customer else None,
            'contact': {'name': self.contact_name, 'email': self.contact_email},
            'shipping_address': self.shipping_address.to_dict(),
            'billing_address': self.billing_address.to_dict(),
            'items': [i.to_dict() for i in self.items],
            'payment': self.payment.to_dict() if self.payment else None,
            'shipment': self.shipment.to_dict(),
            'totals': self.totals.to_dict(),
            'refunds': [r.to_dict() for r in self.refunds],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Order:
        if d.get('schema_version') != SCHEMA_VERSION:
            raise ValueError(f'unsupported schema_version {d.get("schema_version")}')
        order = cls(
            order_id=d['order_id'],
            status=OrderStatus(d['status']),
            created_at=_ts(d['created_at']),
            confirmed_at=_ts(d['confirmed_at']),
            contact_name=d['contact']['name'],
            contact_email=d['contact']['email'],
            customer=Customer.from_dict(d['customer']) if d['customer'] else None,
            shipping_address=Address.from_dict(d['shipping_address']),
            billing_address=Address.from_dict(d['billing_address']),
            items=[OrderItem.from_dict(i) for i in d['items']],
            payment=PaymentSummary.from_dict(d['payment']) if d['payment'] else None,
            shipment=Shipment.from_dict(d['shipment']),
            totals=Totals.from_dict(d['totals']),
            refunds=[RefundSummary.from_dict(r) for r in d['refunds']],
        )
        order.validate()
        return order

    # JSON helpers: Decimal in, Decimal out, so money never passes through a float
    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), default=_json_default, **kwargs)

    @classmethod
    def from_json(cls, text: str) -> Order:
        return cls.from_dict(json.loads(text, parse_float=Decimal))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value) if value != value.to_integral() else int(value)
    raise TypeError(f'{type(value).__name__} is not JSON serializable')


def main() -> None:
    sample = Path(__file__).with_name('sample_order_document.json')
    original = json.loads(sample.read_text(encoding='utf-8'), parse_float=Decimal)
    order = Order.from_dict(original)

    print(f'Order {order.order_id} ({order.status.value}) for '
          f'{order.customer.username if order.customer else "guest " + str(order.contact_email)}')
    print(f'  ship to   {type(order.shipping_address).__name__}: {order.shipping_address.city}, '
          f'{order.shipping_address.region}')
    print(f'  paid with {type(order.payment).__name__}: {order.payment.display if order.payment else "-"}')
    for item in order.items:
        print(f'  {item.quantity} x {item.sku:<16} {item.unit_price:>8} = {item.line_total:>8}')
    print(f'  total {order.totals.total} {order.totals.currency}, refunded {order.refunded_amount}')
    print(f'  carrier {order.shipment.carrier} {order.shipment.tracking_number}')

    # round trip: objects -> dict must equal the document we loaded from PostgreSQL
    assert order.to_dict() == original, 'round trip changed the document'
    print('Round trip OK: JSONB -> Order objects -> JSON gives the identical document.')


if __name__ == '__main__':
    main()
