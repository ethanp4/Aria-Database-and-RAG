import re
from decimal import Decimal
from smtplib import SMTPRecipientsRefused
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import Account
from orders.emails import send_order_confirmation
from orders.links import guest_order_key, guest_order_url
from orders.models import Carrier, Order, OrderItem
from orders.tests.test_models import make_order, make_payment
from products.models import Product

MISS = "We couldn&#x27;t find an order with that number and email."


def make_account(username):
    return Account.objects.create(username=username, password_hash='x')


def add_item(order, sku='P1'):
    product = Product.objects.create(sku=sku, name=f'Mask {sku}', unit_price=Decimal('10.00'),
                                     stock_quantity=5)
    return OrderItem.objects.create(order=order, product=product, quantity=1,
                                    unit_price=Decimal('10.00'), line_total=Decimal('10.00'))


def confirm(order):
    p = make_payment(order)
    Order.objects.filter(pk=order.pk).update(status='CONFIRMED', confirmed_payment=p)
    order.refresh_from_db()
    return order


def login(client, account):
    session = client.session
    session['account_id'] = account.account_id
    session.save()


class CustomerOrderViewTests(TestCase):
    def setUp(self):
        self.alice = make_account('alice')
        self.bob = make_account('bob')

    def test_customer_cannot_view_other_customers_order(self):
        order = make_order(account=self.bob)
        login(self.client, self.alice)
        r = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertEqual(r.status_code, 404)

    def test_customer_cannot_view_guest_order_via_customer_detail_url(self):
        order = make_order()
        login(self.client, self.alice)
        r = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertEqual(r.status_code, 404)

    def test_anonymous_redirected_to_login(self):
        self.assertRedirects(self.client.get(reverse('orders:history')), reverse('accounts:login'))

    def test_customer_sees_own_order_detail(self):
        order = make_order(account=self.alice)
        add_item(order)
        login(self.client, self.alice)
        r = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertContains(r, 'Mask P1')
        self.assertContains(r, 'Standard')

    def test_history_lists_only_own_orders_paginated(self):
        mine = [make_order(account=self.alice) for _ in range(21)]
        theirs = make_order(account=self.bob)
        login(self.client, self.alice)
        r1 = self.client.get(reverse('orders:history'))
        self.assertEqual(len(r1.context['page_obj']), 20)
        self.assertEqual(r1.context['page_obj'][0].pk, mine[-1].pk)
        r2 = self.client.get(reverse('orders:history') + '?page=2')
        self.assertEqual(len(r2.context['page_obj']), 1)
        ids = [o.pk for o in list(r1.context['page_obj']) + list(r2.context['page_obj'])]
        self.assertNotIn(theirs.pk, ids)

    def test_shipped_order_shows_tracking_link(self):
        carrier = Carrier.objects.create(name='Parcelly',
                                         tracking_url_template='https://track.example.com/{tracking_number}')
        order = make_order(account=self.alice)
        confirm(order)
        Order.objects.filter(pk=order.pk).update(status='SHIPPED', carrier=carrier, tracking_number='TRK123')
        login(self.client, self.alice)
        r = self.client.get(reverse('orders:detail', args=[order.pk]))
        self.assertContains(r, 'https://track.example.com/TRK123')
        self.assertContains(r, 'Parcelly')

    def test_failed_order_page_never_says_confirmed(self):
        order = make_order(account=self.alice, status='PAYMENT_FAILED')
        login(self.client, self.alice)
        for url in (reverse('orders:detail', args=[order.pk]), reverse('orders:history')):
            r = self.client.get(url)
            self.assertNotContains(r, 'Confirmed')
            self.assertContains(r, 'Payment failed')


class GuestOrderViewTests(TestCase):
    def test_guest_link_shows_order(self):
        order = make_order()
        add_item(order)
        r = self.client.get(guest_order_url(order))
        self.assertContains(r, 'Mask P1')
        self.assertContains(r, 'Bookmark this page to check your order later.')
        self.assertEqual(r['Referrer-Policy'], 'no-referrer')

    def test_guest_link_wrong_key_or_account_order_404(self):
        order = make_order()
        bad = reverse('orders:guest_detail', args=[order.pk, 'f' * 40])
        self.assertEqual(self.client.get(bad).status_code, 404)
        acct_order = make_order(account=make_account('carol'))
        url = reverse('orders:guest_detail', args=[acct_order.pk, guest_order_key(acct_order)])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_lookup_redirects_to_guest_link_on_match_case_insensitive_email(self):
        order = make_order(contact_email='guest@example.com')
        r = self.client.post(reverse('orders:lookup'),
                             {'order_number': order.pk, 'email': 'GUEST@Example.com'})
        self.assertRedirects(r, guest_order_url(order))

    def test_lookup_wrong_email_same_message_as_missing_order(self):
        order = make_order(contact_email='guest@example.com')
        acct_order = make_order(account=make_account('dave'), contact_email='dave@example.com')
        bodies = []
        for data in ({'order_number': order.pk, 'email': 'other@example.com'},
                     {'order_number': 999999, 'email': 'guest@example.com'},
                     {'order_number': acct_order.pk, 'email': 'dave@example.com'}):
            r = self.client.post(reverse('orders:lookup'), data)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, MISS)
            body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', '', r.content.decode())
            body = re.sub(r'value="[^"]*"', 'value=""', body)
            bodies.append(body)
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[0], bodies[2])

    def test_lookup_get_renders_form(self):
        self.assertContains(self.client.get(reverse('orders:lookup')), 'Find my order')


class NoRiskScoreTests(TestCase):
    def test_customer_and_guest_pages_never_render_risk_score(self):
        acct = make_account('erin')
        mine = make_order(account=acct, risk_score=Decimal('87.50'))
        guest = make_order(risk_score=Decimal('87.50'))
        for o in (mine, guest):
            add_item(o, sku=f'R{o.pk}')
            confirm(o)
        login(self.client, acct)
        pages = [self.client.get(reverse('orders:history')),
                 self.client.get(reverse('orders:detail', args=[mine.pk])),
                 self.client.get(guest_order_url(guest))]
        send_order_confirmation(guest, 'http://testserver' + guest_order_url(guest))
        texts = [p.content.decode() for p in pages] + [mail.outbox[0].subject, mail.outbox[0].body]
        for t in texts:
            self.assertNotIn('87.5', t)
            self.assertNotIn('risk', t.lower())


class ConfirmationEmailTests(TestCase):
    def test_confirmation_email_contains_link_and_masked_card_only(self):
        order = make_order(contact_email='guest@example.com')
        add_item(order)
        confirm(order)
        link = 'http://testserver' + guest_order_url(order)
        send_order_confirmation(order, link)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['guest@example.com'])
        self.assertEqual(msg.from_email, 'orders@aria.example')
        self.assertIn(link, msg.body)
        self.assertIn('•••• 4242', msg.body)
        self.assertIn(str(order.pk), msg.body)
        self.assertIn('Mask P1', msg.body)
        self.assertIn('Standard', msg.body)
        self.assertNotIn('tok_test', msg.body)

    def test_mail_failure_logged_without_customer_email(self):
        order = make_order(contact_email='guest@example.com')
        exc = SMTPRecipientsRefused({'guest@example.com': (550, b'no')})
        with patch('orders.emails.send_mail', side_effect=exc):
            with self.assertLogs('orders.emails', level='ERROR') as logs:
                send_order_confirmation(order, 'http://testserver/x')
        output = '\n'.join(logs.output)
        self.assertIn(str(order.pk), output)
        self.assertNotIn('guest@example.com', output)

    def test_no_email_when_no_contact_email(self):
        order = make_order(account=make_account('frank'), contact_email=None)
        send_order_confirmation(order, 'http://testserver/x')
        self.assertEqual(len(mail.outbox), 0)
