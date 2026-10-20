# display form of a stored payment method, e.g. "Visa •••• 4242"
def mask_payment(payment):
    if not payment.last4:
        return '•••• ----'
    masked = f'•••• {payment.last4}'
    brand = (payment.card_brand or '').strip()
    return f'{brand} {masked}' if brand else masked
