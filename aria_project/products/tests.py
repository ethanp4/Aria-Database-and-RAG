from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command

from accounts.models import Account
from orders.models import Carrier
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


class DashboardPaginationTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Gear')
        for i in range(45):
            Product.objects.create(
                sku=f'P-{i:02d}', name=f'Product {i:02d}', unit_price='10.00', category=self.category,
            )
        for i in range(25):
            Category.objects.create(name=f'Category {i:02d}')
        self.log_in('admin')

    def log_in(self, account_type):
        account = Account.objects.create(
            username=f'dash-{account_type}', password_hash='hash', account_type=account_type,
        )
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

    def test_products_are_paginated_20_per_page(self):
        response = self.client.get(reverse('products:dashboard'))

        page_obj = response.context['product_pages']['page_obj']
        self.assertEqual(len(response.context['products']), 20)
        self.assertEqual(page_obj.paginator.num_pages, 3)
        self.assertEqual(response.context['product_count'], 45)
        self.assertContains(response, 'Product 00')
        self.assertNotContains(response, 'Product 20')

    def test_last_product_page_shows_remaining_products(self):
        response = self.client.get(reverse('products:dashboard'), {'products_page': 3})

        names = [p.name for p in response.context['products']]
        self.assertEqual(names, [f'Product {i}' for i in range(40, 45)])

    def test_tables_page_independently(self):
        response = self.client.get(
            reverse('products:dashboard'), {'products_page': 2, 'categories_page': 3},
        )

        self.assertEqual(response.context['product_pages']['page_obj'].number, 2)
        self.assertEqual(response.context['category_pages']['page_obj'].number, 3)
        # 26 categories in total (Gear + 25), so page 3 holds the last 6
        self.assertEqual(len(response.context['categories']), 6)
        self.assertEqual(response.context['category_count'], 26)

    def test_page_links_keep_other_tables_page(self):
        response = self.client.get(
            reverse('products:dashboard'), {'products_page': 2, 'categories_page': 3},
        )

        self.assertContains(response, 'href="?categories_page=3&amp;products_page=3#products-heading"')
        self.assertContains(response, 'href="?products_page=2&amp;categories_page=2#categories"')

    def test_invalid_or_out_of_range_page_falls_back(self):
        not_a_number = self.client.get(reverse('products:dashboard'), {'products_page': 'abc'})
        too_high = self.client.get(reverse('products:dashboard'), {'products_page': 999})

        self.assertEqual(not_a_number.context['product_pages']['page_obj'].number, 1)
        self.assertEqual(too_high.context['product_pages']['page_obj'].number, 3)

    def test_single_page_table_has_no_pager(self):
        response = self.client.get(reverse('products:dashboard'))

        self.assertNotContains(response, 'aria-label="Profile pages"')
        self.assertContains(response, 'aria-label="Product pages"')

    def test_paginated_dashboard_still_admin_only(self):
        for account_type in ('user', 'staff'):
            self.log_in(account_type)
            response = self.client.get(
                reverse('products:dashboard'), {'products_page': 2, 'products_sort': '-price'},
            )
            self.assertEqual(response.status_code, 403)

    def names(self, response, table='products'):
        return [obj.name for obj in response.context[table]]

    def test_products_sort_by_price_both_directions(self):
        Product.objects.filter(sku='P-07').update(unit_price='99.00')
        Product.objects.filter(sku='P-03').update(unit_price='1.00')

        cheapest = self.client.get(reverse('products:dashboard'), {'products_sort': 'price'})
        priciest = self.client.get(reverse('products:dashboard'), {'products_sort': '-price'})

        self.assertEqual(self.names(cheapest)[0], 'Product 03')
        self.assertEqual(self.names(priciest)[0], 'Product 07')

    def test_sort_is_applied_across_pages(self):
        first = self.client.get(reverse('products:dashboard'), {'products_sort': '-name'})
        last = self.client.get(
            reverse('products:dashboard'), {'products_sort': '-name', 'products_page': 3},
        )

        self.assertEqual(self.names(first)[0], 'Product 44')
        self.assertEqual(self.names(last), [f'Product {i:02d}' for i in range(4, -1, -1)])

    def test_unknown_sort_falls_back_to_default(self):
        response = self.client.get(
            reverse('products:dashboard'), {'products_sort': 'password_hash'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.names(response)[0], 'Product 00')

    def test_header_link_toggles_direction_and_resets_page(self):
        response = self.client.get(
            reverse('products:dashboard'),
            {'products_sort': 'price', 'products_page': 2, 'categories_page': 3},
        )

        price = response.context['product_pages']['sort_links']['price']
        stock = response.context['product_pages']['sort_links']['stock']
        self.assertEqual(price['direction'], 'asc')
        self.assertIn('products_sort=-price', price['url'])
        self.assertNotIn('products_page', price['url'])
        self.assertIn('categories_page=3', price['url'])
        self.assertIsNone(stock['direction'])
        self.assertContains(response, 'aria-sort="ascending"')

    def test_tables_sort_independently(self):
        response = self.client.get(
            reverse('products:dashboard'), {'products_sort': '-name', 'categories_sort': '-name'},
        )

        self.assertEqual(self.names(response)[0], 'Product 44')
        self.assertEqual(self.names(response, 'categories')[0], 'Gear')
        # page links for categories keep the products sort
        self.assertIn('products_sort=-name', response.context['category_pages']['query_string'])

    def test_categories_sort_by_product_count(self):
        response = self.client.get(reverse('products:dashboard'), {'categories_sort': '-products'})

        self.assertEqual(self.names(response, 'categories')[0], 'Gear')

    def test_movements_default_to_newest_first(self):
        product = Product.objects.get(sku='P-00')
        InventoryMovement.objects.create(product=product, change_qty=5, reason=InventoryMovement.Reason.RESTOCK)
        newest = InventoryMovement.objects.create(product=product, change_qty=-1, reason=InventoryMovement.Reason.ADJUSTMENT)

        response = self.client.get(reverse('products:dashboard'))

        self.assertEqual(response.context['inventory_movements'][0].pk, newest.pk)
        self.assertEqual(response.context['movement_pages']['sort_links']['date']['direction'], 'desc')


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
        call_command('sample_data', verbosity=0)

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

        call_command('sample_data', verbosity=0)

        self.assertEqual(Account.objects.count(), 10)
        self.assertEqual(Account.objects.filter(profile__isnull=False).count(), 10)
        self.assertEqual(Category.objects.count(), 6)
        self.assertEqual(Product.objects.count(), 200)


class SampleDataCarrierTests(TestCase):
    def test_sample_data_creates_carriers_idempotently(self):
        call_command('sample_data', verbosity=0)
        names = {'Canada Post', 'Purolator', 'UPS', 'FedEx'}
        self.assertEqual(set(Carrier.objects.values_list('name', flat=True)), names)
        for carrier in Carrier.objects.all():
            self.assertIn('{tracking_number}', carrier.tracking_url_template)
        call_command('sample_data', verbosity=0)
        self.assertEqual(Carrier.objects.count(), 4)


# records every SQL statement run on the default connection (the test client's
# request_started signal clears connection.queries, so CaptureQueriesContext sees nothing)
class RecordSQL:
    def __init__(self):
        self.statements = []

    def __call__(self, execute, sql, params, many, context):
        self.statements.append(sql)
        return execute(sql, params, many, context)

    def __enter__(self):
        self._wrapper = connection.execute_wrapper(self)
        self._wrapper.__enter__()
        return self

    def __exit__(self, *exc):
        return self._wrapper.__exit__(*exc)


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
                original_stock='0',
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
            self.product_data(stock_quantity='13', original_stock='8',
                              inventory_reason='RESTOCK'),
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
            self.product_data(stock_quantity='13', original_stock='8'),
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
            self.product_data(name='Updated mug', original_stock='8'),
        )

        self.assertRedirects(response, reverse('products:dashboard'))
        self.assertFalse(InventoryMovement.objects.exists())

    def make_mug(self, stock=8):
        return Product.objects.create(
            sku='MUG-01', name='Ceramic mug', unit_price='12.50', stock_quantity=stock)

    def test_edit_page_carries_stock_seen_when_rendered(self):
        product = self.make_mug(stock=8)

        response = self.client.get(
            reverse('products:product_edit', args=[product.product_id]))

        self.assertEqual(response.context['form']['original_stock'].value(), 8)
        self.assertContains(response, 'name="original_stock"')

    # admin opened the page at 10, then checkout sold 2: the stale form must not restore them
    def test_stale_original_stock_is_rejected_without_changes(self):
        product = self.make_mug(stock=8)

        response = self.client.post(
            reverse('products:product_edit', args=[product.product_id]),
            self.product_data(name='Renamed', stock_quantity='15', original_stock='10',
                              inventory_reason='RESTOCK'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Stock changed since you opened this page (now 8). Review and save again.')
        form = response.context['form']
        self.assertEqual(str(form['stock_quantity'].value()), '8')
        self.assertEqual(str(form['original_stock'].value()), '8')
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 8)
        self.assertEqual(product.name, 'Ceramic mug')
        self.assertFalse(InventoryMovement.objects.exists())

    def test_edit_without_original_stock_is_rejected(self):
        product = self.make_mug(stock=8)

        response = self.client.post(
            reverse('products:product_edit', args=[product.product_id]),
            self.product_data(stock_quantity='15', inventory_reason='RESTOCK'),
        )

        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 8)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_edit_locks_the_product_row_and_writes_movement(self):
        product = self.make_mug(stock=8)

        with RecordSQL() as queries:
            response = self.client.post(
                reverse('products:product_edit', args=[product.product_id]),
                self.product_data(stock_quantity='5', original_stock='8',
                                  inventory_reason='ADJUSTMENT'),
            )

        self.assertRedirects(response, reverse('products:dashboard'))
        self.assertTrue(any('FOR UPDATE' in sql and '"products"' in sql
                            for sql in queries.statements))
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)
        movement = InventoryMovement.objects.get(product=product)
        self.assertEqual(movement.change_qty, -3)
        self.assertEqual(movement.reason, InventoryMovement.Reason.ADJUSTMENT)

    def test_price_only_edit_leaves_stock_alone(self):
        product = self.make_mug(stock=8)

        with RecordSQL() as queries:
            response = self.client.post(
                reverse('products:product_edit', args=[product.product_id]),
                self.product_data(unit_price='14.00', original_stock='8'),
            )

        self.assertRedirects(response, reverse('products:dashboard'))
        updates = [sql for sql in queries.statements
                   if sql.startswith('UPDATE "products"')]
        self.assertEqual(len(updates), 1)
        self.assertNotIn('"stock_quantity"', updates[0])
        product.refresh_from_db()
        self.assertEqual(str(product.unit_price), '14.00')
        self.assertEqual(product.stock_quantity, 8)
        self.assertFalse(InventoryMovement.objects.exists())


class ProductStockConstraintTests(TestCase):
    def test_negative_stock_is_rejected_by_the_database(self):
        product = Product.objects.create(sku='MUG-01', name='Ceramic mug', unit_price='12.50')
        product.stock_quantity = -1
        with self.assertRaises(IntegrityError), transaction.atomic():
            product.save()


class ProductPermissionTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Fins')
        self.product = Product.objects.create(
            sku='FIN-01',
            name='Paddle fins',
            unit_price='99.00',
            stock_quantity=4,
        )
        self.admin_urls = [
            reverse('products:dashboard'),
            reverse('products:product_create'),
            reverse('products:product_edit', args=[self.product.product_id]),
            reverse('products:category_create'),
            reverse('products:category_edit', args=[self.category.category_id]),
        ]

    def log_in(self, account_type):
        account = Account.objects.create(
            username=f'{account_type}-account',
            password_hash='hash',
            account_type=account_type,
        )
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

    def post_data(self):
        return {
            'sku': 'HACK-01',
            'name': 'Hacked',
            'unit_price': '0.01',
            'currency': 'CAD',
            'stock_quantity': '999',
            'reorder_level': '1',
            'inventory_reason': 'ADJUSTMENT',
            'description': '',
        }

    def assert_nothing_changed(self):
        self.product.refresh_from_db()
        self.category.refresh_from_db()
        self.assertEqual(self.product.name, 'Paddle fins')
        self.assertEqual(self.product.stock_quantity, 4)
        self.assertEqual(self.category.name, 'Fins')
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Category.objects.count(), 1)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_anonymous_redirected_to_login_and_nothing_saved(self):
        for url in self.admin_urls:
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    reverse('accounts:login'),
                )
                self.assertRedirects(
                    self.client.post(url, self.post_data()),
                    reverse('accounts:login'),
                )
        self.assert_nothing_changed()

    def test_customer_gets_403_on_product_and_category_pages(self):
        self.log_in('user')
        for url in self.admin_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.post_data()).status_code, 403)
        self.assert_nothing_changed()

    def test_staff_gets_403_on_product_and_category_pages(self):
        self.log_in('staff')
        for url in self.admin_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.post_data()).status_code, 403)
        self.assert_nothing_changed()

    def test_browse_stays_public(self):
        self.assertEqual(self.client.get(reverse('products:browse')).status_code, 200)


class CategoryManagementTests(TestCase):
    def setUp(self):
        account = Account.objects.create(
            username='category-admin',
            password_hash='hash',
            account_type='admin',
        )
        session = self.client.session
        session['account_id'] = account.account_id
        session.save()

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
