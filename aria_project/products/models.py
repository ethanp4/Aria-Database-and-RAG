from django.db import models

class Category(models.Model):
    category_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'categories'

    def __str__(self):
        return self.name

class Product(models.Model):
    product_id = models.BigAutoField(primary_key=True)
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='CAD')
    stock_quantity = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=10)
    is_active = models.BooleanField(default=True)
    #when inserting with raw sql u need to use now() for the next 2 columns
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        indexes = [
            models.Index(fields=['sku'], name='idx_products_sku'),
            models.Index(fields=['category'], name='idx_products_category'),
            models.Index(fields=['name'], name='idx_products_name'),
            models.Index(fields=['is_active'], name='idx_products_active', condition=models.Q(is_active=True)),
        ]

    def __str__(self):
        return self.name


class InventoryMovement(models.Model):
    class Reason(models.TextChoices):
        SALE = 'SALE', 'Sale'
        RESTOCK = 'RESTOCK', 'Restock'
        REFUND = 'REFUND', 'Refund'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'

    movement_id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.RESTRICT,
        related_name='inventory_movements',
    )
    change_qty = models.IntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inventory_movements'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reason__in=['SALE', 'RESTOCK', 'REFUND', 'ADJUSTMENT']),
                name='inv_mov_reason_valid',
            ),
        ]

    def __str__(self):
        return f'{self.product}: {self.change_qty:+} ({self.get_reason_display()})'