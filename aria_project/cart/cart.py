from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from products.models import Product

MAX_QUANTITY = 99
SESSION_KEY = 'cart'
CENT = Decimal('0.01')


@dataclass
class CartLine:
    product: Product
    quantity: int
    line_total: Decimal


# session cart: {str(product_id): quantity}
class Cart:
    def __init__(self, request):
        self.request = request
        self.dropped = []
        self._lines = None

    # session data is untrusted: keep only digit keys with int quantities >= 1, clamped to 99
    @property
    def _data(self):
        raw = self.request.session.get(SESSION_KEY, {})
        if not isinstance(raw, dict):
            return {}
        clean = {}
        for key, qty in raw.items():
            if (
                isinstance(key, str) and key.isascii() and key.isdigit()
                and isinstance(qty, int) and not isinstance(qty, bool) and qty >= 1
            ):
                clean[key] = min(qty, MAX_QUANTITY)
        return clean

    def _save(self, data):
        self.request.session[SESSION_KEY] = data
        self.request.session.modified = True
        self._lines = None

    def add(self, product_id, qty):
        data = dict(self._data)
        key = str(product_id)
        data[key] = min(data.get(key, 0) + qty, MAX_QUANTITY)
        self._save(data)

    def set(self, product_id, qty):
        if qty <= 0:
            return self.remove(product_id)
        data = dict(self._data)
        data[str(product_id)] = min(qty, MAX_QUANTITY)
        self._save(data)

    def remove(self, product_id):
        data = dict(self._data)
        data.pop(str(product_id), None)
        self._save(data)

    # one query; unknown or inactive products are pruned from the session
    def lines(self):
        if self._lines is not None:
            return self._lines
        data = self._data
        ids = [int(k) for k in data]
        found = {
            p.pk: p
            for p in Product.objects.filter(pk__in=ids)
        }
        lines = []
        kept = {}
        for key, qty in data.items():
            product = found.get(int(key))
            if product is None:
                continue
            if not product.is_active:
                self.dropped.append(product.name)
                continue
            kept[key] = qty
            total = (product.unit_price * qty).quantize(CENT, ROUND_HALF_UP)
            lines.append(CartLine(product, qty, total))
        if kept != data:
            self._save(kept)
        lines.sort(key=lambda line: line.product.name)
        self._lines = lines
        return lines

    def subtotal(self):
        return sum((line.line_total for line in self.lines()), Decimal('0.00'))

    # item count for the navbar; no query
    def count(self):
        return sum(self._data.values())

    def clear(self):
        self.request.session.pop(SESSION_KEY, None)
        self.request.session.modified = True
        self._lines = None
