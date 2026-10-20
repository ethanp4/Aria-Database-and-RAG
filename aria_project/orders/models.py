from django.db import models
from django.db.models import Q

from orders.pricing import SHIPPING_METHODS

_STATUS_VALUES = ['PENDING_PAYMENT', 'PAYMENT_FAILED', 'OUT_OF_STOCK', 'CONFIRMED',
                  'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED']
_COUNTRY_NAMES = {'CA': 'Canada', 'US': 'United States'}


def _address_lines(line1, line2, city, region, postal_code, country):
    lines = [line1]
    if line2:
        lines.append(line2)
    lines.append(f'{city}, {region} {postal_code}')
    lines.append(_COUNTRY_NAMES.get(country, country))
    return lines


class Carrier(models.Model):
    carrier_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    tracking_url_template = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        db_table = 'carriers'

    def __str__(self):
        return self.name


# account is null for guest orders; address fields are copies taken at checkout
class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = 'PENDING_PAYMENT', 'Processing'
        PAYMENT_FAILED = 'PAYMENT_FAILED', 'Payment failed'
        OUT_OF_STOCK = 'OUT_OF_STOCK', 'Out of stock'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        SHIPPED = 'SHIPPED', 'Shipped'
        DELIVERED = 'DELIVERED', 'Delivered'
        CANCELLED = 'CANCELLED', 'Cancelled'
        REFUNDED = 'REFUNDED', 'Refunded'

    order_id = models.BigAutoField(primary_key=True)
    account = models.ForeignKey(
        'accounts.Account', on_delete=models.RESTRICT, null=True, blank=True, related_name='orders',
    )
    carrier = models.ForeignKey(Carrier, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    tracking_number = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)

    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(max_length=254, null=True, blank=True)

    ship_line1 = models.CharField(max_length=255)
    ship_line2 = models.CharField(max_length=255, blank=True, null=True)
    ship_city = models.CharField(max_length=100)
    ship_region = models.CharField(max_length=100)
    ship_postal_code = models.CharField(max_length=20)
    ship_country = models.CharField(max_length=2)
    bill_line1 = models.CharField(max_length=255)
    bill_line2 = models.CharField(max_length=255, blank=True, null=True)
    bill_city = models.CharField(max_length=100)
    bill_region = models.CharField(max_length=100)
    bill_postal_code = models.CharField(max_length=20)
    bill_country = models.CharField(max_length=2)

    shipping_method = models.CharField(max_length=10)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    checkout_token = models.UUIDField(unique=True)
    confirmed_payment = models.OneToOneField(
        'payments.Payment', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    # staff/admin only; never render on customer pages
    risk_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'orders'
        indexes = [
            models.Index(fields=['account', '-created_at'], name='idx_orders_account_created'),
            models.Index(fields=['status', '-created_at'], name='idx_orders_status_created'),
            models.Index(fields=['created_at'], name='idx_orders_created'),
            models.Index(fields=['tracking_number'], name='idx_orders_tracking'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=_STATUS_VALUES), name='order_status_valid',
            ),
            models.CheckConstraint(
                condition=Q(shipping_method__in=list(SHIPPING_METHODS)),
                name='order_shipping_method_valid',
            ),
            models.CheckConstraint(
                condition=~Q(status__in=['CONFIRMED', 'SHIPPED', 'DELIVERED', 'REFUNDED'])
                | Q(confirmed_payment__isnull=False),
                name='order_confirmed_requires_payment',
            ),
            models.CheckConstraint(
                condition=Q(account__isnull=False)
                | (Q(contact_email__isnull=False) & ~Q(contact_email='')),
                name='order_has_owner',
            ),
            models.CheckConstraint(condition=Q(ship_country__in=['CA', 'US']), name='order_ship_country_valid'),
            models.CheckConstraint(condition=Q(bill_country__in=['CA', 'US']), name='order_bill_country_valid'),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0) & Q(shipping_cost__gte=0)
                & Q(tax_amount__gte=0) & Q(total_amount__gte=0),
                name='order_money_nonneg',
            ),
        ]

    def __str__(self):
        return f'Order {self.order_id} ({self.status})'

    def ship_address_lines(self):
        return _address_lines(self.ship_line1, self.ship_line2, self.ship_city,
                              self.ship_region, self.ship_postal_code, self.ship_country)

    def bill_address_lines(self):
        return _address_lines(self.bill_line1, self.bill_line2, self.bill_city,
                              self.bill_region, self.bill_postal_code, self.bill_country)


# price is copied from the product at order time
class OrderItem(models.Model):
    order_item_id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.RESTRICT, related_name='order_items')
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'order_items'
        indexes = [
            models.Index(fields=['product'], name='idx_order_items_product'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='order_item_quantity_positive'),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0) & Q(line_total__gte=0), name='order_item_money_nonneg',
            ),
        ]

    def __str__(self):
        return f'{self.quantity} x {self.product_id} on order {self.order_id}'
