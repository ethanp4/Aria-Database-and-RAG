from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command

from accounts.models import Account
from .models import Category, InventoryMovement, Product


class DashboardTests(TestCase):
    def test_dashboard_displays_database_counts(self):
        account = Account.objects.create(
            username='sample-customer',
            password_hash='hash',
            account_type='admin',
        )
        Product.objects.create(
            sku='SAMPLE-1',
            name='Sample product',
            unit_price='12.50',
        )
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

        response = self.client.get(reverse('products:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['account_count'], 1)
        self.assertEqual(response.context['product_count'], 1)
        self.assertContains(response, 'Sample product')


class BrowseViewTests(TestCase):
    def setUp(self):
        self.drinkware = Category.objects.create(name='Drinkware')
        self.stationery = Category.objects.create(name='Stationery')
        Product.objects.create(
            sku='MUG-01',
            name='Ceramic mug',
            description='A reusable coffee cup.',
            category=self.drinkware,
            unit_price='12.50',
            stock_quantity=5,
        )
        Product.objects.create(
            sku='NOTE-01',
            name='Notebook',
            description='A lined paper notebook.',
            category=self.stationery,
            unit_price='5.00',
            stock_quantity=0,
        )
        Product.objects.create(
            sku='MUG-02',
            name='Travel mug',
            description='An insulated travel cup.',
            category=self.drinkware,
            unit_price='25.00',
            stock_quantity=4,
            is_active=False,
        )

    def test_browse_search_and_filters_narrow_active_products(self):
        response = self.client.get(reverse('products:browse'), {
            'q': 'mug',
            'category': self.drinkware.pk,
            'min_price': '10',
            'max_price': '20',
            'in_stock': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result_count'], 1)
        self.assertQuerySetEqual(
            response.context['products'],
            ['Ceramic mug'],
            transform=lambda product: product.name,
        )

    def test_browse_excludes_inactive_products_and_shows_empty_result(self):
        response = self.client.get(reverse('products:browse'), {'q': 'Travel mug'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result_count'], 0)
        self.assertContains(response, 'No products found')

    def test_browse_rejects_minimum_price_above_maximum(self):
        response = self.client.get(reverse('products:browse'), {
            'min_price': '20',
            'max_price': '10',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Maximum price must be at least the minimum price.')

    def test_browse_paginates_and_preserves_filters_and_page_size(self):
        for index in range(25):
            Product.objects.create(
                sku=f'PAGE-{index:02d}',
                name=f'Page product {index:02d}',
                category=self.drinkware,
                unit_price='10.00',
                stock_quantity=1,
            )

        response = self.client.get(reverse('products:browse'), {
            'category': self.drinkware.pk,
            'per_page': '20',
        })

        self.assertEqual(response.context['result_count'], 26)
        self.assertEqual(len(response.context['products']), 20)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertContains(response, f'category={self.drinkware.pk}&amp;per_page=20&amp;page=2')

        second_page = self.client.get(reverse('products:browse'), {
            'category': self.drinkware.pk,
            'per_page': '20',
            'page': '2',
        })

        self.assertEqual(len(second_page.context['products']), 6)
        self.assertEqual(second_page.context['page_obj'].number, 2)

    def test_browse_supports_50_and_100_results_per_page(self):
        for index in range(105):
            Product.objects.create(
                sku=f'BULK-{index:03d}',
                name=f'Bulk product {index:03d}',
                category=self.drinkware,
                unit_price='10.00',
                stock_quantity=1,
            )

        for page_size, expected_count in [('50', 50), ('100', 100)]:
            with self.subTest(page_size=page_size):
                response = self.client.get(
                    reverse('products:browse'),
                    {'per_page': page_size},
                )
                self.assertEqual(len(response.context['products']), expected_count)

    def test_browse_defaults_to_20_results_per_page(self):
        response = self.client.get(reverse('products:browse'))

        self.assertEqual(response.context['filter_form']['per_page'].value(), '20')


class SampleDataCommandTests(TestCase):
    def test_seed_command_creates_requested_sample_data_idempotently(self):
        call_command('seed_sample_data', verbosity=0)

        self.assertEqual(Account.objects.count(), 10)
        self.assertEqual(Account.objects.filter(profile__isnull=False).count(), 10)
        self.assertEqual(Category.objects.count(), 6)
        self.assertEqual(Product.objects.count(), 200)
        self.assertEqual(
            Product.objects.filter(category__isnull=False).count(),
            200,
        )
        self.assertEqual(
            Account.objects.filter(account_type='admin').count(),
            1,
        )

        call_command('seed_sample_data', verbosity=0)

        self.assertEqual(Account.objects.count(), 10)
        self.assertEqual(Account.objects.filter(profile__isnull=False).count(), 10)
        self.assertEqual(Category.objects.count(), 6)
        self.assertEqual(Product.objects.count(), 200)


class ProductManagementTests(TestCase):
    def setUp(self):
        account = Account.objects.create(
            username='product-admin',
            password_hash='hash',
            account_type='admin',
        )
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

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
