# Refund decision guide (support use)

Audience: support staff. This demo policy supplements `shared/returns-and-refunds.md`. Apply applicable consumer protection requirements and escalate unclear, high-value, suspected-fraud, or safety-related cases. Never treat a SQL result as the policy decision by itself.

## Normally eligible for standard return

- Request is within 30 calendar days after recorded delivery.
- Item is unused, resalable, and has original packaging and included components.
- Item is not a used hygiene-sensitive product excluded by the customer policy.
- Order and payment can be matched to the verified customer or guest checkout contact through the approved support workflow.
- Refund amount does not exceed the amount paid for the returned item, after any applicable partial-return calculation.

## Normally not eligible for change-of-mind refund

- Request is made more than 30 calendar days after delivery.
- Item has been used, damaged after delivery, materially altered, or is missing required components or packaging.
- Hygiene-sensitive item (used mask, snorkel, mouthpiece, or exposure suit) has been used.
- The same order/item already has a completed refund, or an open request is already being processed.

These are standard rules, not grounds to deny a defective, unsafe, misdescribed, or incorrectly supplied item. Escalate those cases and follow applicable legal obligations.

## Decision and workflow

1. Verify the order through authenticated case context; guest orders require matching the checkout contact using the approved process. Do not reveal order data before verification.
2. Check delivery date, item and quantity, order-item price snapshot, payment status, and existing refund history.
3. Record the customer's reason and evidence. For damage, defect, or wrong-item claims, request only reasonable supporting details and escalate safety concerns.
4. If standard criteria are met, explain return instructions and that refund follows receipt and inspection. Support staff do not promise a provider settlement date.
5. If criteria are not met, explain the relevant rule respectfully and offer escalation when the customer disputes condition, date, delivery record, or legal entitlement.
6. Do not create, approve, deny, or complete refunds with this read-only assistant. Use the authorized refund workflow; investigate suspected duplicate requests through the designated supervisor process.

## Data interpretation notes

The schema records `orders.delivered_at`, but a missing delivery timestamp means the database does not establish delivery; it is not proof the customer received the parcel. `refunds.status` values are `REQUESTED`, `APPROVED`, `DENIED`, and `COMPLETED`. A requested or approved refund is not necessarily paid. `order_items.unit_price` is the price at checkout. Never use or disclose `risk_score` as the reason for a customer-facing decision.
