from django.db import models


_STATUS_VALUES = ['AUTHORIZED', 'CAPTURED', 'DECLINED', 'VOIDED', 'FAILED', 'REFUNDED']
_METHOD_VALUES = ['CREDIT_CARD', 'DEBIT_CARD', 'PAYPAL', 'GIFT_CARD']


# payment attempt for an order; only a token and the last 4 digits are ever stored
class Payment(models.Model):
    class Status(models.TextChoices):
        AUTHORIZED = 'AUTHORIZED', 'Authorized'
        CAPTURED = 'CAPTURED', 'Captured'
        DECLINED = 'DECLINED', 'Declined'
        VOIDED = 'VOIDED', 'Voided'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    class MethodType(models.TextChoices):
        CREDIT_CARD = 'CREDIT_CARD', 'Credit card'
        DEBIT_CARD = 'DEBIT_CARD', 'Debit card'
        PAYPAL = 'PAYPAL', 'PayPal'
        GIFT_CARD = 'GIFT_CARD', 'Gift card'

    payment_id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey('orders.Order', on_delete=models.RESTRICT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method_type = models.CharField(max_length=20, choices=MethodType.choices)
    token = models.CharField(max_length=255)
    last4 = models.CharField(max_length=4, null=True, blank=True)
    card_brand = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    gateway_ref = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'
        indexes = [
            models.Index(fields=['order'], name='idx_payments_order'),
            models.Index(fields=['status', 'created_at'], name='idx_payments_status_created'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=0), name='payment_amount_nonneg'),
            models.CheckConstraint(
                condition=models.Q(status__in=_STATUS_VALUES),
                name='payment_status_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(method_type__in=_METHOD_VALUES),
                name='payment_method_type_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(last4__isnull=True) | models.Q(last4__regex=r'^[0-9]{4}$'),
                name='payment_last4_digits',
            ),
        ]

    def __str__(self):
        return f'Payment {self.payment_id} ({self.status})'
