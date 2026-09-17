from django.contrib import admin

from .models import (
    AccountsPayable,
    AccountsReceivable,
    Address,
    Carrier,
    Customer,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    PolicyDocument,
    Product,
    Refund,
)

admin.site.register(Customer)
admin.site.register(Address)
admin.site.register(Product)
admin.site.register(Carrier)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(InventoryMovement)
admin.site.register(Payment)
admin.site.register(Refund)
admin.site.register(AccountsReceivable)
admin.site.register(AccountsPayable)
admin.site.register(PolicyDocument)
