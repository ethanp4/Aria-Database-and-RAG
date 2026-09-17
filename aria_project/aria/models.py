from django.db import models


class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    password_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customers"
        indexes = [
            models.Index(fields=["last_name"], name="idx_customers_last_name"),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Address(models.Model):
    SHIPPING = "SHIPPING"
    BILLING = "BILLING"
    ADDRESS_TYPE_CHOICES = [(SHIPPING, "Shipping"), (BILLING, "Billing")]

    CA = "CA"
    US = "US"
    COUNTRY_CHOICES = [(CA, "Canada"), (US, "United States")]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    address_type = models.CharField(max_length=10, choices=ADDRESS_TYPE_CHOICES)
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=2, choices=COUNTRY_CHOICES)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "addresses"
        indexes = [
            models.Index(fields=["customer", "address_type"], name="idx_addresses_customer_type"),
        ]

    def __str__(self):
        return f"{self.line1}, {self.city}"


class Product(models.Model):
    CAD = "CAD"
    USD = "USD"
    CURRENCY_CHOICES = [(CAD, "CAD"), (USD, "USD")]

    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default=CAD)
    stock_quantity = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=10)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        indexes = [
            models.Index(fields=["is_active"], name="idx_products_active"),
        ]

    def __str__(self):
        return self.name


class Carrier(models.Model):
    name = models.CharField(max_length=100, unique=True)
    tracking_url_template = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "carriers"

    def __str__(self):
        return self.name


class Order(models.Model):
    PENDING = "PENDING"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    STATUS_CHOICES = [
        (PENDING, "Pending"), (PAID, "Paid"), (PROCESSING, "Processing"),
        (SHIPPED, "Shipped"), (DELIVERED, "Delivered"),
        (CANCELLED, "Cancelled"), (REFUNDED, "Refunded"),
    ]
    CAD = "CAD"
    USD = "USD"
    CURRENCY_CHOICES = [(CAD, "CAD"), (USD, "USD")]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    shipping_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name="ship_orders")
    billing_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name="bill_orders")
    carrier = models.ForeignKey(Carrier, on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    tracking_number = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    order_date = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders"
        indexes = [
            models.Index(fields=["customer", "-order_date"], name="idx_orders_customer_date"),
        ]

    def __str__(self):
        return f"Order #{self.pk}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "order_items"

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"


class InventoryMovement(models.Model):
    SALE = "SALE"
    RESTOCK = "RESTOCK"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    REASON_CHOICES = [
        (SALE, "Sale"), (RESTOCK, "Restock"), (REFUND, "Refund"), (ADJUSTMENT, "Adjustment"),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    change_qty = models.IntegerField()
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    reference_order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "inventory_movements"


class Payment(models.Model):
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    PAYPAL = "PAYPAL"
    GIFT_CARD = "GIFT_CARD"
    METHOD_CHOICES = [
        (CREDIT_CARD, "Credit Card"), (DEBIT_CARD, "Debit Card"),
        (PAYPAL, "PayPal"), (GIFT_CARD, "Gift Card"),
    ]
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REFUNDED = "REFUNDED"
    STATUS_CHOICES = [
        (PENDING, "Pending"), (APPROVED, "Approved"), (DECLINED, "Declined"), (REFUNDED, "Refunded"),
    ]
    CAD = "CAD"
    USD = "USD"
    CURRENCY_CHOICES = [(CAD, "CAD"), (USD, "USD")]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    transaction_ref = models.CharField(max_length=100, blank=True, null=True)
    processed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "payments"


class Refund(models.Model):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    COMPLETED = "COMPLETED"
    STATUS_CHOICES = [
        (REQUESTED, "Requested"), (APPROVED, "Approved"), (DENIED, "Denied"), (COMPLETED, "Completed"),
    ]
    CAD = "CAD"
    USD = "USD"
    CURRENCY_CHOICES = [(CAD, "CAD"), (USD, "USD")]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="refunds")
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    reason = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=REQUESTED, db_index=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "refunds"


class AccountsReceivable(models.Model):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"
    STATUS_CHOICES = [
        (OPEN, "Open"), (PAID, "Paid"), (OVERDUE, "Overdue"), (WRITTEN_OFF, "Written Off"),
    ]
    CAD = "CAD"
    USD = "USD"
    CURRENCY_CHOICES = [(CAD, "CAD"), (USD, "USD")]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="receivables")
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_receivable"
        verbose_name_plural = "Accounts Receivable"
        indexes = [
            models.Index(fields=["due_date"], name="idx_ar_due_date"),
        ]


class AccountsPayable(models.Model):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    STATUS_CHOICES = [(OPEN, "Open"), (PAID, "Paid"), (OVERDUE, "Overdue")]
    CAD = "CAD"
    USD = "USD"
    CURRENCY_CHOICES = [(CAD, "CAD"), (USD, "USD")]

    carrier = models.ForeignKey(Carrier, on_delete=models.SET_NULL, null=True, blank=True, related_name="payables")
    vendor_name = models.CharField(max_length=255)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_payable"
        verbose_name_plural = "Accounts Payable"
        indexes = [
            models.Index(fields=["due_date"], name="idx_ap_due_date"),
        ]


class PolicyDocument(models.Model):
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    file_path = models.CharField(max_length=500)
    version = models.CharField(max_length=20, default="1.0")
    last_updated = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "policy_documents"

    def __str__(self):
        return self.title

