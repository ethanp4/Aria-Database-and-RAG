# Site functions and order status

## What customers can do

- Browse active products by name or category and view descriptions, listed prices, currency, and current availability.
- Register for an account and sign in. Account holders may use saved profile and address details where the site supports them.
- Add products to checkout, provide shipping and billing details, choose an offered shipping method, and pay using the methods shown at checkout.
- Purchase as a guest without creating an account. Guest checkout requires contact information so Aria can send order updates and provide support.
- Contact support about products, orders, delivery, accounts, or returns.

The cart does not reserve stock. Final price, shipping, tax, and availability are confirmed during checkout. Do not claim a site capability (such as order editing or self-service cancellation) unless it is visible in the current site interface.

## Order statuses in the system

- `PENDING_PAYMENT`: checkout has started; payment is not confirmed.
- `PAYMENT_FAILED`: payment did not complete.
- `OUT_OF_STOCK`: the order could not proceed because inventory was unavailable.
- `CONFIRMED`: payment and order have been confirmed.
- `SHIPPED`: carrier handoff has occurred; tracking details may be available.
- `DELIVERED`: delivery is recorded in the system.
- `CANCELLED`: order is cancelled.
- `REFUNDED`: order is marked refunded; consult refund records for the amount and processing state.

The customer chatbot may explain these meanings but must not access another customer's order. Support staff must verify the case before looking up order details. A status timestamp is system-recorded evidence and may not by itself resolve a delivery dispute.
