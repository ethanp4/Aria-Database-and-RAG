from django.test import TestCase
from django.urls import reverse

from accounts.models import Customer
from .models import Category, InventoryMovement, Product


class DashboardTests(TestCase):
    def test_dashboard_displays_database_counts(self):
        Customer.objects.create(username='sample-customer', password_hash='hash')
        Product.objects.create(
            sku='SAMPLE-1',
            name='Sample product',
            unit_price='12.50',
        )

        response = self.client.get(reverse('products:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<p class="display-6 fw-semibold mb-0">1</p>',
            count=2,
            html=True,
        )
        self.assertContains(response, 'Sample product')


class ProductManagementTests(TestCase):
    def product_data(self, **overrides):
        data = {
            'sku': 'MUG-01',
            'name': 'Ceramic mug',
            'description': 'A sturdy mug.',
            'category': '',
            'unit_price': '12.50',
            'currency': 'CAD',
            'stock_quantity': '8',
            'reorder_level': '3',
            'is_active': 'on',
        }
        data.update(overrides)
        return data

    def test_create_product(self):
        response = self.client.post(
            reverse('products:product_create'),
            self.product_data(),
        )

        self.assertRedirects(response, reverse('products:dashboard'))
        self.assertTrue(Product.objects.filter(sku='MUG-01').exists())

    def test_edit_product(self):
        product = Product.objects.create(
            sku='MUG-01',
            name='Ceramic mug',
            unit_price='12.50',
        )

        response = self.client.post(
            reverse('products:product_edit', args=[product.product_id]),
            self.product_data(
                name='Updated mug',
                sku='MUG-02',
                stock_quantity='8',
                inventory_reason='RESTOCK',
            ),
        )

        self.assertRedirects(response, reverse('products:dashboard'))
        product.refresh_from_db()
        self.assertEqual(product.name, 'Updated mug')
        self.assertEqual(product.sku, 'MUG-02')

    def test_stock_change_creates_inventory_movement(self):
        product = Product.objects.create(
            sku='MUG-01',
            name='Ceramic mug',
            unit_price='12.50',
            stock_quantity=8,
        )

        response = self.client.post(
            reverse('products:product_edit', args=[product.product_id]),
            self.product_data(stock_quantity='13', inventory_reason='RESTOCK'),
        )

        self.assertRedirects(response, reverse('products:dashboard'))
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 13)
        movement = InventoryMovement.objects.get(product=product)
        self.assertEqual(movement.change_qty, 5)
        self.assertEqual(movement.reason, InventoryMovement.Reason.RESTOCK)

    def test_stock_change_requires_reason(self):
        product = Product.objects.create(
            sku='MUG-01',
            name='Ceramic mug',
            unit_price='12.50',
            stock_quantity=8,
        )

        response = self.client.post(
            reverse('products:product_edit', args=[product.product_id]),
            self.product_data(stock_quantity='13'),
        )

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 8)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_edit_without_stock_change_does_not_create_movement(self):
        product = Product.objects.create(
            sku='MUG-01',
            name='Ceramic mug',
            unit_price='12.50',
            stock_quantity=8,
        )

        response = self.client.post(
            reverse('products:product_edit', args=[product.product_id]),
            self.product_data(name='Updated mug'),
        )

        self.assertRedirects(response, reverse('products:dashboard'))
        self.assertFalse(InventoryMovement.objects.exists())


class CategoryManagementTests(TestCase):
    def test_category_creation_returns_to_product_form_with_category_selected(self):
        response = self.client.post(
            reverse('products:category_create'),
            {'name': 'Drinkware', 'description': 'Cups and bottles.'},
        )

        category = Category.objects.get(name='Drinkware')
        self.assertRedirects(
            response,
            f"{reverse('products:product_create')}?category={category.pk}",
        )
        product_response = self.client.get(response.url)
        self.assertContains(product_response, 'Drinkware')
        self.assertContains(
            product_response,
            f'<option value="{category.pk}" selected>Drinkware (0 items)</option>',
            html=True,
        )

    def test_duplicate_category_name_is_rejected(self):
        Category.objects.create(name='Drinkware')

        response = self.client.post(
            reverse('products:category_create'),
            {'name': 'Drinkware', 'description': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Category.objects.count(), 1)
        self.assertContains(response, 'already exists')
