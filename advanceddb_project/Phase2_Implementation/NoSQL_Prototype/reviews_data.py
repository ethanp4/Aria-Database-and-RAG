"""Deterministic synthetic product reviews for the Firestore "reviews" collection.

Reviews are built from the same simulation as the PostgreSQL seed (SQL_Scripts/generate_seed.py,
seed 2026), so every reviewer is a real seed customer, every product SKU exists in PostgreSQL,
and verified_purchase / order_id point at an actual delivered order. Run the module to print a
summary and write sample_documents.json:
    python reviews_data.py
"""
import importlib.util
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

N_REVIEWS = 60
HERE = Path(__file__).resolve().parent
SEED_SCRIPT = HERE.parent / 'SQL_Scripts' / 'generate_seed.py'


def _load_seed_simulation():
    spec = importlib.util.spec_from_file_location('generate_seed', SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate()                    # fills module.tables exactly as 03_seed.sql has them
    return module.tables


TAGS_BY_CATEGORY = {
    'Masks & Snorkels': ['fogging', 'fit', 'wide-view', 'travel', 'beginner'],
    'Regulators & Air': ['cold-water', 'breathing-effort', 'servicing', 'technical', 'travel'],
    'Buoyancy & Exposure': ['cold-water', 'warm-water', 'sizing', 'travel', 'durability'],
    'Fins & Boots': ['sizing', 'travel', 'shore-entry', 'beginner', 'power'],
    'Dive Computers & Instruments': ['nitrox', 'battery', 'display', 'technical', 'beginner'],
    'Safety & Surface Gear': ['visibility', 'compact', 'cold-water', 'shore-entry', 'value'],
}
DIVE_SITES = [
    ('Whytecliff Park, BC', 9), ('Porteau Cove, BC', 8), ('Tobermory, ON', 6), ('Bonne Bay, NL', 4),
    ('Key Largo, FL', 27), ('La Jolla, CA', 17), ('Honolulu, HI', 25), ('Brockville, ON', 12),
]
TITLES = {
    5: ['Exactly what I needed', 'Best purchase this season', 'Worth every dollar', 'Five stars, no notes'],
    4: ['Very good, small nitpick', 'Solid gear', 'Happy with it', 'Would buy again'],
    3: ['Does the job', 'Okay for the price', 'Mixed feelings', 'Average'],
    2: ['Disappointed', 'Not for cold water', 'Sizing runs off', 'Expected more'],
    1: ['Returned it', 'Did not work for me', 'Would not recommend', 'Broke on the second dive'],
}
OPENERS = {
    5: 'Used the {name} on {dives} dives so far and it has been excellent.',
    4: 'The {name} has worked well over {dives} dives.',
    3: 'After {dives} dives the {name} is fine but not special.',
    2: 'I wanted to like the {name}, but after {dives} dives it has let me down.',
    1: 'The {name} lasted {dives} dives before I gave up on it.',
}
DETAILS = {
    'fogging': 'Needed defog every time.', 'fit': 'Seals well on my face.', 'sizing': 'Order a size up.',
    'cold-water': 'Held up fine in single-digit water.', 'warm-water': 'Comfortable in tropical water.',
    'travel': 'Packs small for dive trips.', 'beginner': 'Easy for a new diver to figure out.',
    'technical': 'Plenty of settings for experienced divers.', 'battery': 'Battery easily lasts a trip.',
    'display': 'Display is readable at depth.', 'visibility': 'Easy for the boat to spot.',
    'compact': 'Clips neatly to my BCD.', 'servicing': 'Shop service was straightforward.',
    'breathing-effort': 'Breathes easily at depth.', 'durability': 'No wear after a season.',
    'shore-entry': 'Good on rocky shore entries.', 'power': 'Lots of thrust per kick.',
    'nitrox': 'Nitrox setup is simple.', 'value': 'Good value for the price.', 'wide-view': 'Huge field of view.',
}
STAFF_REPLIES = [
    'Thanks for the detailed review! We have passed your feedback on to the manufacturer.',
    'Sorry to hear this. Our returns team can help within 30 days of delivery; reply here or contact support.',
    'Glad it is working well for you. Remember to rinse it in fresh water after every dive.',
]
CUSTOMER_REPLIES = [
    'Same experience here, sizing up fixed it for me.',
    'Did you try it in colder water? Thinking of buying one.',
    'Agree, great for travel.',
]


def build_reviews():
    tables = _load_seed_simulation()
    rng = random.Random(2026)
    products = {p['product_id']: p for p in tables['products']}
    categories = {c['category_id']: c['name'] for c in tables['categories']}
    accounts = {a['account_id']: a for a in tables['accounts']}
    staff = [a for a in tables['accounts'] if a['account_type'] == 'staff']
    orders = {o['order_id']: o for o in tables['orders']}

    # candidate reviews: one per (customer, product) delivered to a registered customer
    purchases = []
    for item in tables['order_items']:
        order = orders[item['order_id']]
        if order['account_id'] and order['delivered_at']:
            purchases.append((order, products[item['product_id']]))
    picked = rng.sample(purchases, N_REVIEWS - 6)

    # a few reviews from customers without a matching purchase (verified_purchase = false)
    customers = [a for a in tables['accounts'] if a['account_type'] == 'user']
    for _ in range(6):
        picked.append((None, rng.choice(tables['products']), rng.choice(customers)))

    reviews = []
    for n, entry in enumerate(picked, 1):
        if len(entry) == 2:
            order, product = entry
            author = accounts[order['account_id']]
            created = order['delivered_at'] + timedelta(days=rng.randint(2, 40))
        else:
            order, product, author = entry
            created = datetime(2025, 11, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 320))
        created = min(created, datetime(2026, 9, 30, tzinfo=timezone.utc))
        category = categories[product['category_id']]
        rating = rng.choices([5, 4, 3, 2, 1], weights=[40, 30, 15, 9, 6])[0]
        tags = sorted(rng.sample(TAGS_BY_CATEGORY[category], rng.randint(1, 3)))
        dives = rng.randint(2, 40)

        sub = {'quality': max(1, min(5, rating + rng.choice([-1, 0, 0, 1]))),
               'value': max(1, min(5, rating + rng.choice([-1, 0, 0, 1])))}
        if category in ('Masks & Snorkels', 'Buoyancy & Exposure', 'Fins & Boots'):
            sub['fit'] = max(1, min(5, rating + rng.choice([-2, -1, 0, 0, 1])))   # only wearable gear
        if rng.random() < 0.5:
            sub['durability'] = max(1, min(5, rating + rng.choice([-1, 0, 0])))

        doc = {
            'product': {'sku': product['sku'], 'name': product['name'], 'category': category},
            'author': {'account_id': author['account_id'], 'username': author['username'],
                       'verified_purchase': order is not None},
            'order_id': order['order_id'] if order else None,
            'rating': rating,
            'ratings': sub,
            'title': rng.choice(TITLES[rating]),
            'body': ' '.join([OPENERS[rating].format(name=product['name'].lower(), dives=dives)]
                             + [DETAILS[t] for t in tags]),
            'tags': tags,
            'photos': [{'url': f'https://example.test/review-photos/rev-{n:04d}-{i}.jpg',
                        'caption': rng.choice(['On the boat', 'After the dive', 'Close-up', 'Out of the box'])}
                       for i in range(1, rng.choice([0, 0, 0, 1, 1, 2]) + 1)],
            'helpful_votes': rng.choices([0, 1, 2, 3, 5, 8, 13, 21], weights=[25, 20, 15, 12, 10, 8, 6, 4])[0],
            'status': 'hidden' if rating == 1 and rng.random() < 0.3 else 'published',
            'created_at': created,
        }
        # semi-structured extra: only some divers log where they used the gear
        if rng.random() < 0.45:
            site, temp = rng.choice(DIVE_SITES)
            doc['dive_context'] = {'site': site, 'water_temp_c': temp + rng.randint(-2, 2),
                                   'max_depth_m': rng.choice([6, 9, 12, 18, 24, 30])}

        replies = []
        for r in range(rng.choices([0, 1, 2, 3], weights=[40, 35, 18, 7])[0]):
            if r == 0 and (rating <= 3 or rng.random() < 0.3):
                author_role, who = 'staff', rng.choice(staff)['username']
                body = STAFF_REPLIES[1] if rating <= 2 else rng.choice(STAFF_REPLIES)
            else:
                author_role, who = 'customer', rng.choice(customers)['username']
                body = rng.choice(CUSTOMER_REPLIES)
            replies.append((f'reply-{r + 1}', {
                'author_role': author_role, 'author': who, 'body': body,
                'created_at': created + timedelta(days=rng.randint(1, 10) + r),
            }))
        reviews.append((f'rev-{n:04d}', doc, replies))
    return reviews


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value))


if __name__ == '__main__':
    reviews = build_reviews()
    n_replies = sum(len(r[2]) for r in reviews)
    verified = sum(r[1]['author']['verified_purchase'] for r in reviews)
    print(f'{len(reviews)} reviews, {n_replies} replies, {verified} verified purchases')
    sample = [{'id': rid, **doc, 'replies': [{'id': i, **d} for i, d in replies]}
              for rid, doc, replies in reviews if replies and doc.get('dive_context') and doc['photos']][:2]
    (HERE / 'sample_documents.json').write_text(json.dumps(sample, indent=2, default=_jsonable) + '\n',
                                                encoding='utf-8')
    print('wrote sample_documents.json')
