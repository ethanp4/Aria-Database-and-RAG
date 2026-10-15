from django.db import models

# account_type values: customer, staff, admin
ROLE_CUSTOMER = 'user'
ROLE_STAFF = 'staff'
ROLE_ADMIN = 'admin'
ROLES = (ROLE_CUSTOMER, ROLE_STAFF, ROLE_ADMIN)

#accounts cant be updated
class Account(models.Model):
    account_id = models.BigAutoField(primary_key=True)
    username = models.CharField(max_length=100, unique=True)
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    account_type = models.CharField(max_length=50, default=ROLE_CUSTOMER)

    class Meta:
        db_table = 'accounts'
        constraints = [
            models.UniqueConstraint(fields=['username'], name='unique_username'),
            models.CheckConstraint(condition=models.Q(account_type__in=list(ROLES)), name='valid_account_type'),
        ]

    def __str__(self):
        return self.username

#this stores profile information separately from the login
class Profile(models.Model):
    profile_id = models.BigAutoField(primary_key=True)
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name='profile')
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'profiles'

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

#shipping/billing addresses, always looked up through the owning account
class Address(models.Model):
    class AddressType(models.TextChoices):
        SHIPPING = 'SHIPPING', 'Shipping'
        BILLING = 'BILLING', 'Billing'

    class Country(models.TextChoices):
        CANADA = 'CA', 'Canada'
        UNITED_STATES = 'US', 'United States'

    address_id = models.BigAutoField(primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='addresses')
    address_type = models.CharField(max_length=10, choices=AddressType.choices)
    line1 = models.CharField('Address line 1', max_length=255)
    line2 = models.CharField('Address line 2', max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    region = models.CharField('Province / state', max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=2, choices=Country.choices)
    is_default = models.BooleanField('Default address', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'addresses'
        indexes = [
            models.Index(fields=['account', 'address_type'], name='idx_addresses_account_type'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(address_type__in=['SHIPPING', 'BILLING']), name='address_type_valid'),
            models.CheckConstraint(condition=models.Q(country__in=['CA', 'US']), name='address_country_valid'),
            models.UniqueConstraint(
                fields=['account', 'address_type'],
                condition=models.Q(is_default=True),
                name='one_default_address_per_type',
            ),
        ]

    def __str__(self):
        return f"{self.line1}, {self.city}, {self.region} {self.postal_code}"