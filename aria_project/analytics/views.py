"""Admin analytics screens from the Figma prototype (read-only).

Every figure is a bounded, DB-side aggregate over existing tables (orders,
order_items, products); nothing is invented and nothing is written. Refund
figures are shown as unavailable until the refunds table exists.
No payment details are read here.
"""
from datetime import datetime, time, timedelta

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from accounts.models import ROLE_ADMIN
from accounts.permissions import role_required
from orders.models import Order, OrderItem
from products.models import Product

# orders whose payment succeeded and that still count as sales
# (REFUNDED is excluded so refunded money is not reported as revenue)
PAID_STATUSES = (Order.Status.CONFIRMED, Order.Status.SHIPPED, Order.Status.DELIVERED)
MONTHS = 12
DAYS = 30
TOP_PRODUCTS = 5
LOW_STOCK_LIMIT = 10


def _month_starts(this_month, count):
    months = [this_month]
    for _ in range(count - 1):
        months.append((months[-1] - timedelta(days=1)).replace(day=1))
    return list(reversed(months))


def _pct(value, peak):
    return round(float(value) / float(peak) * 100, 1) if peak else 0


def _line_points(values, peak):
    """SVG path on a 0-100 viewBox: x spread evenly, y from the top."""
    if not values:
        return '', []
    step = 100 / (len(values) - 1) if len(values) > 1 else 0
    points = [(round(i * step, 2), round(100 - _pct(v, peak), 2)) for i, v in enumerate(values)]
    path = 'M' + ' L'.join(f'{x} {y}' for x, y in points)
    return path, points


def build_analytics():
    now = timezone.localtime()
    today = now.date()
    this_month = today.replace(day=1)
    months = _month_starts(this_month, MONTHS)
    tz = timezone.get_current_timezone()
    window_start = timezone.make_aware(
        datetime.combine(months[0], time.min), tz)
    day_start_date = today - timedelta(days=DAYS - 1)
    day_start = timezone.make_aware(
        datetime.combine(day_start_date, time.min), tz)

    paid = Order.objects.filter(status__in=PAID_STATUSES)

    # 1 query: revenue + order count per month for the last 12 months (current month is MTD)
    by_month = {
        row['month'].date(): row
        for row in paid.filter(created_at__gte=window_start)
        .annotate(month=TruncMonth('created_at')).values('month')
        .annotate(revenue=Sum('total_amount'), orders=Count('pk')).order_by()
    }
    monthly = [{
        'month': m,
        'revenue': by_month.get(m, {}).get('revenue') or 0,
        'orders': by_month.get(m, {}).get('orders') or 0,
        'is_current': m == this_month,
    } for m in months]
    peak_revenue = max((m['revenue'] for m in monthly), default=0)
    for m in monthly:
        m['pct'] = _pct(m['revenue'], peak_revenue)
        m['is_peak'] = bool(peak_revenue) and m['revenue'] == peak_revenue
    peak_month = next((m for m in monthly if m['is_peak']), None)

    # 1 query: paid orders per day for the last 30 days
    by_day = {
        row['day']: row['orders']
        for row in paid.filter(created_at__gte=day_start)
        .annotate(day=TruncDate('created_at')).values('day')
        .annotate(orders=Count('pk')).order_by()
    }
    daily = [{'day': day_start_date + timedelta(days=i),
              'orders': by_day.get(day_start_date + timedelta(days=i), 0)} for i in range(DAYS)]
    peak_orders = max((d['orders'] for d in daily), default=0)
    peak_day = max(daily, key=lambda d: d['orders']) if peak_orders else None
    line_path, line_points = _line_points([d['orders'] for d in daily], peak_orders)

    # 1 query: every order status in the last 30 days (not only paid ones)
    status_labels = dict(Order.Status.choices)
    status_rows = (Order.objects.filter(created_at__gte=day_start)
                   .values('status').annotate(orders=Count('pk')).order_by('-orders', 'status'))
    by_status = [{'label': status_labels.get(r['status'], r['status']), 'orders': r['orders']}
                 for r in status_rows]
    peak_status = max((s['orders'] for s in by_status), default=0)
    for s in by_status:
        s['pct'] = _pct(s['orders'], peak_status)

    # 1 query: best sellers by units on paid orders in the last 30 days
    top_products = list(
        OrderItem.objects.filter(order__status__in=PAID_STATUSES, order__created_at__gte=day_start)
        .values('product_id', 'product__name', 'product__sku')
        .annotate(units=Sum('quantity'), revenue=Sum('line_total'))
        .order_by('-units', 'product__name')[:TOP_PRODUCTS]
    )
    peak_units = top_products[0]['units'] if top_products else 0
    for p in top_products:
        p['pct'] = _pct(p['units'], peak_units)

    # 1 query: active products at or below their reorder level
    low_stock = list(
        Product.objects.filter(is_active=True, stock_quantity__lte=F('reorder_level'))
        .order_by('stock_quantity', 'name')
        .values('product_id', 'name', 'sku', 'stock_quantity', 'reorder_level')[:LOW_STOCK_LIMIT]
    )

    current = monthly[-1]
    return {
        'generated_at': now,
        'this_month': this_month,
        'today': today,
        'kpi_revenue': current['revenue'],
        'kpi_orders': current['orders'],
        'monthly': monthly,
        'peak_month': peak_month,
        'daily': daily,
        'day_start': day_start_date,
        'daily_total': sum(d['orders'] for d in daily),
        'peak_orders': peak_orders,
        'peak_day': peak_day,
        'latest_day': daily[-1],
        'line_path': line_path,
        'line_points': line_points,
        'by_status': by_status,
        'top_products': top_products,
        'low_stock': low_stock,
        'low_stock_limit': LOW_STOCK_LIMIT,
        'days': DAYS,
    }


@role_required(ROLE_ADMIN)
@require_GET
def dashboard_view(request):
    return render(request, 'analytics/dashboard.html', build_analytics())


# the same figures as an accessible table (Figma: "Accessible analytics data")
@role_required(ROLE_ADMIN)
@require_GET
def data_view(request):
    return render(request, 'analytics/data.html', build_analytics())
