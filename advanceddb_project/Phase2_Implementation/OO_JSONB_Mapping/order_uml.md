# Order: UML class diagram

This diagram matches the dataclasses in `order_model.py`. GitHub renders the Mermaid source below, and `order_uml.png` is the same diagram as an image for the report.

```mermaid
classDiagram
    direction TB

    class Order {
        +int order_id
        +OrderStatus status
        +datetime created_at
        +datetime confirmed_at
        +str contact_name
        +str contact_email
        +validate() None
        +refunded_amount() Decimal
        +to_dict() dict
        +from_dict(dict)$ Order
        +to_json() str
        +from_json(str)$ Order
    }
    class OrderStatus {
        <<enumeration>>
        PENDING_PAYMENT
        PAYMENT_FAILED
        OUT_OF_STOCK
        CONFIRMED
        SHIPPED
        DELIVERED
        CANCELLED
        REFUNDED
        +is_paid() bool
    }
    class Customer {
        +int account_id
        +str username
    }
    class Address {
        +str line1
        +str line2
        +str city
        +str region
        +str postal_code
        +str country
    }
    class ShippingAddress
    class BillingAddress
    class OrderItem {
        +str sku
        +str name
        +str category
        +int quantity
        +Decimal unit_price
        +line_total() Decimal
    }
    class PaymentSummary {
        <<abstract>>
        +str method
        +str status
        +display()* str
    }
    class CardPayment {
        +str brand
        +str last4
        +display() str
    }
    class WalletPayment {
        +display() str
    }
    class Shipment {
        +str method
        +str carrier
        +str tracking_number
        +str tracking_url
        +datetime shipped_at
        +datetime delivered_at
    }
    class Totals {
        +Decimal subtotal
        +Decimal shipping
        +Decimal tax
        +Decimal total
        +str currency
    }
    class RefundSummary {
        +int refund_id
        +Decimal amount
        +str status
        +str reason
        +datetime requested_at
    }

    Order --> OrderStatus : status
    Order "0..*" --> "0..1" Customer : placed by (none = guest)
    Order *-- "1" ShippingAddress : ships to
    Order *-- "1" BillingAddress : bills to
    Order *-- "1..*" OrderItem : items
    Order *-- "0..1" PaymentSummary : paid with
    Order *-- "1" Shipment : shipment
    Order *-- "1" Totals : totals
    Order *-- "0..*" RefundSummary : refunds
    Address <|-- ShippingAddress
    Address <|-- BillingAddress
    PaymentSummary <|-- CardPayment
    PaymentSummary <|-- WalletPayment
```

## How each class maps to PostgreSQL

| Class | Relational (authoritative) | JSONB (`order_document.doc`) |
|---|---|---|
| `Order` | `orders` row | the whole document |
| `OrderStatus` | `orders.status` + `orders_status_valid` CHECK | `"status"` |
| `Customer` (association) | `orders.account_id` → `accounts` | `"customer": {account_id, username}` or `null` for a guest |
| `ShippingAddress` / `BillingAddress` (inheritance) | `orders.ship_*` / `orders.bill_*` snapshot columns | `"shipping_address"` / `"billing_address"`, with `"kind"` naming the subclass |
| `OrderItem` (composition, 1..*) | `order_items` rows (FK `ON DELETE CASCADE`) joined to `products`, `categories` | `"items": [ ... ]` array |
| `PaymentSummary` → `CardPayment` / `WalletPayment` (inheritance) | latest `payments` row; card vs wallet enforced by `payments_card_fields` CHECK | `"payment"`, with `"type": "card"` or `"wallet"` as the subclass marker |
| `Shipment` | `orders.shipping_method`, `carrier_id` → `carriers`, `tracking_number`, `shipped_at`, `delivered_at` | `"shipment"` |
| `Totals` | `orders.subtotal`, `shipping_cost`, `tax_amount`, `total_amount` | `"totals"` |
| `RefundSummary` (composition, 0..*) | `refunds` rows | `"refunds": [ ... ]` array |

There are two ways to store a subclass:
- **Relational:** a discriminator column guarded by a CHECK constraint (`payments.method_type` plus `payments_card_fields`).
- **JSONB:** a discriminator key (`"type"` or `"kind"`), which `PaymentSummary.from_dict()` and `Address.from_dict()` use to build the right subclass.

Composition parts never outlive the order:
- **Relational:** `order_items` cascade on delete.
- **JSONB:** the parts are embedded inside the order's own document.
