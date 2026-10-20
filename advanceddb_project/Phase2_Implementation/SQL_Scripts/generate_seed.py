"""Generate 03_seed.sql: deterministic synthetic data for the aria_phase2 database.

Usage (any Python 3.10+, standard library only):
    python generate_seed.py            # writes 03_seed.sql next to this file
    python generate_seed.py --check    # regenerate in memory and confirm 03_seed.sql is identical

Everything is driven by one random.Random(SEED) and a fixed clock (AS_OF), so the same
seed always produces a byte-identical file. All people, emails, phones, addresses,
card tokens and suppliers are invented. Emails use the reserved example.test domain and
phone numbers use the fictional 555-01xx range.

The simulation walks one year of orders in time order so the data obeys the schema's rules:
  * stock never goes negative; every stock change has an inventory_movements row and
    products.stock_quantity equals the sum of its movements
  * an order is CONFIRMED/SHIPPED/DELIVERED/REFUNDED only with a captured payment
  * totals add up (subtotal + shipping + tax), line_total = quantity * unit_price
  * refunds never exceed the order total and there is at most one open refund per order
  * payments store a fake token and last 4 digits only, never a card number
"""
import argparse
import random
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SEED = 2026
AS_OF = datetime(2026, 10, 1, tzinfo=timezone.utc)      # "today" for the dataset
START = datetime(2025, 10, 1, tzinfo=timezone.utc)      # first order
CATALOGUE_DATE = datetime(2025, 9, 1, tzinfo=timezone.utc)

N_CUSTOMERS = 200
N_ORDERS = 480
GUEST_SHARE = 0.10
OUTPUT = Path(__file__).with_name('03_seed.sql')

CENTS = Decimal('0.01')
rng = random.Random(SEED)


def money(value):
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def fake_uuid():
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def fake_hex(n):
    return ''.join(rng.choice('0123456789abcdef') for _ in range(n))


def between(start, end):
    """Random moment in [start, end)."""
    span = (end - start).total_seconds()
    return start + timedelta(seconds=int(rng.random() * span))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
# Same catalogue as aria_project/products/management/commands/sample_data.py
CATEGORIES = {
    'Masks & Snorkels': 'Masks, snorkels, and accessories for clear underwater vision.',
    'Regulators & Air': 'Breathing regulators, gauges, and cylinder accessories.',
    'Buoyancy & Exposure': 'Buoyancy compensators and thermal protection.',
    'Fins & Boots': 'Fins, boots, and gear for efficient movement in the water.',
    'Dive Computers & Instruments': 'Computers and instruments for dive planning and monitoring.',
    'Safety & Surface Gear': 'Surface signaling, cutting tools, and diver safety equipment.',
}

PRODUCTS = (
    ('MASK-001', 'Low-volume dive mask', 'Masks & Snorkels', 'Low-volume tempered-glass mask with a soft silicone skirt.', '74.95', 18),
    ('MASK-002', 'Wide-view dive mask', 'Masks & Snorkels', 'Wide-angle lens design for an expanded field of view.', '89.50', 11),
    ('MASK-003', 'Frameless travel mask', 'Masks & Snorkels', 'Lightweight frameless mask that packs easily for travel.', '99.00', 7),
    ('SNORK-001', 'Flexible-top snorkel', 'Masks & Snorkels', 'Flexible snorkel with a comfortable silicone mouthpiece.', '34.95', 22),
    ('MASK-004', 'Prescription-ready mask', 'Masks & Snorkels', 'Durable mask designed to accept compatible prescription lenses.', '119.00', 5),
    ('REG-001', 'Balanced diaphragm first stage', 'Regulators & Air', 'Environmentally sealed first stage for cold-water diving.', '429.00', 6),
    ('REG-002', 'Adjustable second stage', 'Regulators & Air', 'Compact second stage with user-adjustable breathing resistance.', '289.95', 9),
    ('REG-003', 'Alternate air source', 'Regulators & Air', 'High-visibility alternate second stage for buddy breathing.', '159.00', 13),
    ('GAUGE-001', 'Compact pressure gauge', 'Regulators & Air', 'Easy-to-read analog submersible pressure gauge.', '109.50', 8),
    ('HOSE-001', 'Braided regulator hose', 'Regulators & Air', 'Flexible high-pressure hose for compatible dive regulators.', '64.95', 15),
    ('BCD-001', 'Back-inflate buoyancy compensator', 'Buoyancy & Exposure', 'Streamlined back-inflate BCD with integrated weight pockets.', '649.00', 4),
    ('BCD-002', 'Travel buoyancy compensator', 'Buoyancy & Exposure', 'Lightweight travel BCD with fold-flat construction.', '529.00', 6),
    ('SUIT-001', '3 mm full wetsuit', 'Buoyancy & Exposure', 'Stretch neoprene full suit for warm-water diving.', '279.95', 10),
    ('SUIT-002', '5 mm hooded wetsuit', 'Buoyancy & Exposure', 'Thermal full suit with an integrated hood for cooler water.', '459.00', 3),
    ('GLOVE-001', 'Neoprene dive gloves', 'Buoyancy & Exposure', 'Textured neoprene gloves for warmth and grip.', '59.95', 16),
    ('FIN-001', 'Open-heel paddle fins', 'Fins & Boots', 'Responsive paddle fins for travel and recreational diving.', '189.00', 12),
    ('FIN-002', 'Split-blade open-heel fins', 'Fins & Boots', 'Efficient split-blade fins with adjustable spring straps.', '219.95', 8),
    ('FIN-003', 'Full-foot snorkeling fins', 'Fins & Boots', 'Comfortable full-foot fins for snorkeling and warm-water use.', '99.00', 14),
    ('BOOT-001', '5 mm neoprene dive boots', 'Fins & Boots', 'Reinforced-sole boots for shore entries and cold water.', '89.95', 9),
    ('FIN-004', 'Compact travel fins', 'Fins & Boots', 'Short-blade fins that fit easily into a travel bag.', '129.00', 5),
    ('COMP-001', 'Wrist dive computer', 'Dive Computers & Instruments', 'Nitrox-capable wrist computer with a clear high-contrast display.', '389.00', 7),
    ('COMP-002', 'Air-integrated dive computer', 'Dive Computers & Instruments', 'Wireless air integration with customizable dive alarms.', '849.00', 2),
    ('COMP-003', 'Console dive computer', 'Dive Computers & Instruments', 'Rugged console computer with compass and pressure gauge.', '579.00', 4),
    ('COMP-004', 'Wrist compass', 'Dive Computers & Instruments', 'Luminous underwater compass with a rotating bezel.', '119.95', 10),
    ('COMP-005', 'Depth and timing gauge', 'Dive Computers & Instruments', 'Simple analog depth gauge and elapsed-time instrument.', '149.00', 6),
    ('SMB-001', 'Surface marker buoy', 'Safety & Surface Gear', 'Bright delayed surface marker buoy with an oral inflator.', '79.95', 20),
    ('REEL-001', 'Finger spool with line', 'Safety & Surface Gear', 'Compact line spool for deploying a surface marker buoy.', '39.00', 17),
    ('CUT-001', 'Stainless dive knife', 'Safety & Surface Gear', 'Corrosion-resistant line-cutting knife with a secure sheath.', '69.95', 8),
    ('WHISTLE-001', 'Waterproof signal whistle', 'Safety & Surface Gear', 'Compact high-volume whistle for surface signaling.', '12.50', 30),
    ('LIGHT-001', 'Rechargeable dive torch', 'Safety & Surface Gear', 'Rechargeable primary light with multiple brightness settings.', '159.00', 5),
)

PRODUCT_FAMILIES = (
    ('MASK', 'Low-volume dive mask', 'Masks & Snorkels', 'Tempered-glass lens with a soft silicone skirt.', '74.95'),
    ('SNORK', 'Purge snorkel', 'Masks & Snorkels', 'Comfortable mouthpiece and a streamlined purge valve.', '39.95'),
    ('REG1', 'Balanced regulator first stage', 'Regulators & Air', 'Reliable first stage for recreational and technical diving.', '429.00'),
    ('REG2', 'Adjustable regulator second stage', 'Regulators & Air', 'Smooth breathing performance with adjustable resistance.', '289.95'),
    ('BCD', 'Back-inflate buoyancy compensator', 'Buoyancy & Exposure', 'Stable buoyancy control with integrated weight pockets.', '649.00'),
    ('WET', 'Full-length neoprene wetsuit', 'Buoyancy & Exposure', 'Flexible thermal protection for scuba and watersports.', '279.95'),
    ('HOOD', 'Neoprene dive hood', 'Buoyancy & Exposure', 'Thermal hood with a comfortable face seal.', '69.95'),
    ('GLOVE', 'Neoprene dive gloves', 'Buoyancy & Exposure', 'Textured palms for warmth and grip underwater.', '59.95'),
    ('FIN', 'Open-heel paddle fins', 'Fins & Boots', 'Powerful blade with an adjustable foot pocket.', '189.00'),
    ('BOOT', 'Neoprene dive boots', 'Fins & Boots', 'Reinforced sole for shore entries and rocky surfaces.', '89.95'),
    ('COMP', 'Wrist dive computer', 'Dive Computers & Instruments', 'Clear display with air and nitrox dive modes.', '389.00'),
    ('AICOMP', 'Air-integrated dive computer', 'Dive Computers & Instruments', 'Wireless tank-pressure monitoring and dive alarms.', '849.00'),
    ('COMPASS', 'Underwater compass', 'Dive Computers & Instruments', 'Luminous dial and rotating bezel for navigation.', '119.95'),
    ('SMB', 'Surface marker buoy', 'Safety & Surface Gear', 'High-visibility buoy for signaling your position.', '79.95'),
    ('REEL', 'Dive reel with line', 'Safety & Surface Gear', 'Corrosion-resistant reel for marker buoy deployment.', '69.95'),
    ('CUTTER', 'Dive line cutter', 'Safety & Surface Gear', 'Compact corrosion-resistant cutter with a secure sheath.', '49.95'),
    ('LIGHT', 'Rechargeable dive torch', 'Safety & Surface Gear', 'Sealed underwater light with adjustable brightness.', '159.00'),
)

PRODUCT_VARIANTS = (
    ('Recreational', 'Designed for everyday recreational dives.'),
    ('Travel', 'A portable design for dive trips and travel.'),
    ('Professional', 'Durable construction for frequent use.'),
    ('Cold-water', 'Configured for demanding cold-water conditions.'),
    ('Warm-water', 'A streamlined option for warm-water diving.'),
    ('Compact', 'Space-saving design that is easy to pack.'),
    ('Expedition', 'Built for extended dive trips and exploration.'),
    ('Lightweight', 'Lightweight construction for comfortable carrying.'),
    ('Technical', 'Feature-rich equipment for experienced divers.'),
    ('Deluxe', 'Enhanced materials and comfort-focused details.'),
)

FIRST_NAMES = (
    'Avery', 'Jordan', 'Taylor', 'Riley', 'Casey', 'Nora', 'Sam', 'Jamie', 'Alex', 'Morgan',
    'Quinn', 'Rowan', 'Emery', 'Harper', 'Skyler', 'Reese', 'Logan', 'Parker', 'Hayden', 'Drew',
    'Kai', 'Sage', 'Marin', 'Ocean', 'Brook', 'Lake', 'Coral', 'Finley', 'Jules', 'Robin',
    'Mira', 'Theo', 'Iris', 'Elio', 'Wren', 'Arlo', 'Lena', 'Omar', 'Priya', 'Mateo',
    'Yuki', 'Ines', 'Noah', 'Zara', 'Felix', 'Ada', 'Hugo', 'Leila', 'Ravi', 'Sofia',
)
LAST_NAMES = (
    'Morgan', 'Lee', 'Kim', 'Patel', 'Nguyen', 'Bennett', 'Rivera', 'Wilson', 'Chen', 'Reed',
    'Tremblay', 'Gagnon', 'Roy', 'Cote', 'Bouchard', 'Gauthier', 'Martin', 'Smith', 'Brown', 'Singh',
    'Campbell', 'Anderson', 'MacDonald', 'Taylor', 'Fraser', 'Stewart', 'Wong', 'Li', 'Garcia', 'Lopez',
    'Okafor', 'Haddad', 'Novak', 'Kowalski', 'Silva', 'Costa', 'Sato', 'Tanaka', 'Ahmed', 'Khan',
)
STREETS = (
    'Harbour', 'Seaside', 'Kelp', 'Coral', 'Tide', 'Marina', 'Lighthouse', 'Anchor', 'Driftwood',
    'Gull', 'Saltwater', 'Reef', 'Bayview', 'Cove', 'Shoreline', 'Pier', 'Current', 'Lagoon',
)
STREET_TYPES = ('St', 'Ave', 'Rd', 'Way', 'Dr', 'Cres', 'Blvd')

# (city, region, country, postal prefix, weight) -- coastal/dive towns weighted higher
CITIES = (
    ('Vancouver', 'BC', 'CA', 'V6B', 10), ('Victoria', 'BC', 'CA', 'V8W', 6), ('Nanaimo', 'BC', 'CA', 'V9R', 4),
    ('Calgary', 'AB', 'CA', 'T2P', 5), ('Edmonton', 'AB', 'CA', 'T5J', 4), ('Saskatoon', 'SK', 'CA', 'S7K', 2),
    ('Winnipeg', 'MB', 'CA', 'R3C', 2), ('Toronto', 'ON', 'CA', 'M5V', 9), ('Ottawa', 'ON', 'CA', 'K1P', 4),
    ('Kingston', 'ON', 'CA', 'K7L', 3), ('Montreal', 'QC', 'CA', 'H3B', 6), ('Quebec City', 'QC', 'CA', 'G1R', 2),
    ('Halifax', 'NS', 'CA', 'B3J', 5), ("St. John's", 'NL', 'CA', 'A1C', 2), ('Charlottetown', 'PE', 'CA', 'C1A', 1),
    ('Moncton', 'NB', 'CA', 'E1C', 1), ('Whitehorse', 'YT', 'CA', 'Y1A', 1),
    ('Seattle', 'WA', 'US', '981', 4), ('Portland', 'OR', 'US', '972', 2), ('San Diego', 'CA', 'US', '921', 3),
    ('Monterey', 'CA', 'US', '939', 2), ('Miami', 'FL', 'US', '331', 3), ('Key Largo', 'FL', 'US', '330', 2),
    ('Austin', 'TX', 'US', '787', 1), ('New York', 'NY', 'US', '100', 2), ('Boston', 'MA', 'US', '021', 1),
    ('Denver', 'CO', 'US', '802', 1), ('Honolulu', 'HI', 'US', '968', 2),
)

# Placeholder tax rates, matching the app's temporary table (orders/pricing.py).
# Canada taxes goods and shipping; the US entries tax goods only.
TAX_RATES = {
    ('CA', 'AB'): '5', ('CA', 'BC'): '12', ('CA', 'MB'): '12', ('CA', 'NB'): '15', ('CA', 'NL'): '15',
    ('CA', 'NS'): '14', ('CA', 'ON'): '13', ('CA', 'PE'): '15', ('CA', 'QC'): '14.975', ('CA', 'SK'): '11',
    ('CA', 'YT'): '5',
    ('US', 'WA'): '6.5', ('US', 'OR'): '0', ('US', 'CA'): '7.25', ('US', 'FL'): '6', ('US', 'TX'): '6.25',
    ('US', 'NY'): '4', ('US', 'MA'): '6.25', ('US', 'CO'): '2.9', ('US', 'HI'): '4',
}

# code: (price, free shipping threshold)
SHIPPING = {'STANDARD': ('12.00', '150.00'), 'EXPRESS': ('20.00', None), 'PRIORITY': ('35.00', None)}

CARRIERS = (
    ('Canada Post', 'https://www.canadapost-postescanada.ca/track?pin={tracking_number}'),
    ('Purolator', 'https://www.purolator.com/en/shipping/tracker?pin={tracking_number}'),
    ('UPS', 'https://www.ups.com/track?tracknum={tracking_number}'),
    ('FedEx', 'https://www.fedex.com/fedextrack/?trknbr={tracking_number}'),
)
CARRIER_BASE_DAYS = {1: 5, 2: 3, 3: 3, 4: 3}

SUPPLIERS = (
    ('Blue Reef Supply Co.', 'CA', 30), ('Kelp Coast Distributors', 'CA', 30), ('Deep Current Optics', 'US', 45),
    ('Northern Tide Neoprene', 'CA', 30), ('Pacific Rim Dive Wholesale', 'CA', 45), ('Salt & Bubble Imports', 'US', 30),
    ('Abyss Instruments Ltd.', 'CA', 60), ('Harbourline Marine Goods', 'CA', 15), ('Coral Gate Trading', 'US', 30),
    ('Seafloor Regulators Inc.', 'US', 45), ('Lighthouse Safety Gear', 'CA', 30), ('Driftwood Outdoor Supply', 'CA', 30),
    ('Atlantic Fin Works', 'CA', 30), ('Gulfstream Dive Imports', 'US', 60), ('Polar Water Thermal', 'CA', 45),
    ('Lagoon Light Systems', 'US', 30), ('Saltwater Signal Co.', 'CA', 15), ('Benthic Gauge Works', 'US', 45),
    ('Westcoast Wetsuit Mfg.', 'CA', 30), ('Island Snorkel Supply', 'US', 30), ('Anchor Point Hardware', 'CA', 30),
    ('Riptide Footwear', 'US', 30), ('Clearwater Lens Labs', 'CA', 45), ('Shoreline Logistics Packaging', 'CA', 15),
    ('Mariner Tool & Blade', 'US', 30),
)
# Which suppliers stock which category (indexes into SUPPLIERS, 1-based ids)
CATEGORY_SUPPLIERS = {
    'Masks & Snorkels': (3, 20, 23, 1),
    'Regulators & Air': (10, 18, 5, 14),
    'Buoyancy & Exposure': (4, 15, 19, 2),
    'Fins & Boots': (13, 22, 6, 9),
    'Dive Computers & Instruments': (7, 18, 14, 5),
    'Safety & Surface Gear': (11, 16, 17, 25, 12),
}

REFUND_REASONS = (
    ('Wrong size', 0.30, True), ('Changed my mind', 0.20, True), ('Item arrived damaged', 0.15, False),
    ('Not as described', 0.15, True), ('Arrived too late for my trip', 0.12, True), ('Ordered twice by mistake', 0.08, True),
)

POLICY_DOCUMENTS = (
    ('Shipping Rates and Free Shipping', 'Shipping', 'shipping-rates', '1.2'),
    ('Delivery Times by Carrier', 'Shipping', 'delivery-times', '1.0'),
    ('Shipping to the United States', 'Shipping', 'us-shipping', '1.1'),
    ('Lost or Delayed Packages', 'Shipping', 'lost-packages', '1.0'),
    ('Return Window and Conditions', 'Returns & Refunds', 'return-window', '2.0'),
    ('How Refunds Are Processed', 'Returns & Refunds', 'refund-processing', '1.3'),
    ('Damaged or Defective Items', 'Returns & Refunds', 'damaged-items', '1.0'),
    ('Final Sale Items', 'Returns & Refunds', 'final-sale', '1.0'),
    ('Accepted Payment Methods', 'Payments', 'payment-methods', '1.1'),
    ('Payment Declines and Holds', 'Payments', 'payment-declines', '1.0'),
    ('Sales Tax', 'Payments', 'sales-tax', '1.0'),
    ('Order Status Explained', 'Orders', 'order-status', '1.2'),
    ('Changing or Cancelling an Order', 'Orders', 'cancel-order', '1.0'),
    ('Guest Checkout and Order Lookup', 'Orders', 'guest-orders', '1.0'),
    ('Regulator Servicing Intervals', 'Products & Safety', 'regulator-servicing', '1.0'),
    ('Dive Computer Battery and Care', 'Products & Safety', 'computer-care', '1.0'),
    ('Privacy Policy', 'Privacy', 'privacy', '3.0'),
    ('Data Retention', 'Privacy', 'data-retention', '1.0'),
    ('Managing Your Account', 'Account', 'account', '1.1'),
    ('Manufacturer Warranty Claims', 'Warranty', 'warranty', '1.0'),
)
# older versions kept for history (inactive)
POLICY_OLD_VERSIONS = (('return-window', '1.0'), ('privacy', '2.0'))

# Seasonality: relative order volume by month (diving peaks before summer and winter trips)
MONTH_WEIGHTS = {10: 6, 11: 8, 12: 11, 1: 7, 2: 7, 3: 8, 4: 9, 5: 11, 6: 13, 7: 12, 8: 10, 9: 7}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
tables = defaultdict(list)          # table name -> list of row dicts (insertion order kept)


def build_catalogue():
    for i, (name, description) in enumerate(CATEGORIES.items(), 1):
        tables['categories'].append({'category_id': i, 'name': name, 'description': description})
    category_ids = {name: i for i, name in enumerate(CATEGORIES, 1)}

    rows = [(sku, name, cat, desc, Decimal(price), stock) for sku, name, cat, desc, price, stock in PRODUCTS]
    for code, name, cat, desc, base in PRODUCT_FAMILIES:
        for v, (variant, vdesc) in enumerate(PRODUCT_VARIANTS, 1):
            price = money(Decimal(base) * (1 + Decimal(v - 1) / 40))
            rows.append((f'GEN-{code}-{v:02d}', f'{variant} {name}', cat, f'{desc} {vdesc}', price, 4 + (v % 17)))

    products = []
    for pid, (sku, name, cat, desc, price, stock) in enumerate(rows, 1):
        suppliers = CATEGORY_SUPPLIERS[cat]
        products.append({
            'product_id': pid, 'sku': sku, 'name': name, 'description': desc,
            'category_id': category_ids[cat], 'unit_price': price, 'currency': 'CAD',
            'opening_stock': stock, 'reorder_level': 5 if price < 300 else 3,
            'is_active': pid % 41 != 0,              # a few discontinued products
            'supplier_id': suppliers[pid % len(suppliers)],
            # popularity drives how often a product is ordered (cheap accessories sell more)
            'weight': (3.0 if price < 100 else 1.6 if price < 300 else 0.8) * rng.uniform(0.4, 1.6),
        })
    return products


def build_carriers_and_suppliers():
    for i, (name, template) in enumerate(CARRIERS, 1):
        tables['carriers'].append({'carrier_id': i, 'name': name, 'tracking_url_template': template})
    for i, (name, country, terms) in enumerate(SUPPLIERS, 1):
        slug = ''.join(ch for ch in name.lower() if ch.isalnum())[:20]
        tables['suppliers'].append({
            'supplier_id': i, 'name': name, 'contact_email': f'orders@{slug}.example.test',
            'phone': f'555-01{i:02d}', 'country': country, 'payment_terms_days': terms,
            'is_active': i != 24, 'created_at': CATALOGUE_DATE - timedelta(days=rng.randint(30, 700)),
        })


def postal_code(country, prefix):
    if country == 'CA':
        letters = 'ABCEGHJKLMNPRSTVWXYZ'
        return f'{prefix} {rng.randint(1, 9)}{rng.choice(letters)}{rng.randint(0, 9)}'
    return f'{prefix}{rng.randint(0, 99):02d}'


def random_address():
    city, region, country, prefix, _ = rng.choices(CITIES, weights=[c[4] for c in CITIES])[0]
    line2 = f'Unit {rng.randint(1, 40) * 100 + rng.randint(1, 20)}' if rng.random() < 0.3 else None
    return {
        'line1': f'{rng.randint(10, 9999)} {rng.choice(STREETS)} {rng.choice(STREET_TYPES)}',
        'line2': line2, 'city': city, 'region': region,
        'postal_code': postal_code(country, prefix), 'country': country,
    }


def build_people():
    accounts, customers = [], []
    used_usernames = set()

    def add_account(account_type, created_at, first, last, username=None):
        account_id = len(accounts) + 1
        base = username or f'{first}.{last}'.lower().replace("'", '')
        name = base
        n = 1
        while name in used_usernames:
            n += 1
            name = f'{base}{n}'
        used_usernames.add(name)
        account = {
            'account_id': account_id, 'username': name,
            # "!" prefix = Django's marker for an unusable password: nobody can log in as seed data
            'password_hash': '!' + fake_hex(40),
            'account_type': account_type, 'created_at': created_at,
        }
        accounts.append(account)
        tables['profiles'].append({
            'profile_id': account_id, 'account_id': account_id, 'first_name': first, 'last_name': last,
            'phone': f'{rng.choice(("604", "250", "403", "416", "902", "514"))}-555-01{rng.randint(0, 99):02d}',
            'email': f'{name}@example.test', 'created_at': created_at,
            'updated_at': created_at + timedelta(days=rng.randint(0, 60)),
        })
        return account

    # customers: most signed up before the order year, some during it
    for _ in range(N_CUSTOMERS):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        if rng.random() < 0.7:
            created = between(datetime(2023, 6, 1, tzinfo=timezone.utc), START)
        else:
            created = between(START, AS_OF - timedelta(days=20))
        account = add_account('user', created, first, last)
        customers.append({
            'account': account, 'name': f'{first} {last}',
            # loyalty: a few customers order often, many order once or never
            'weight': rng.paretovariate(1.6),
        })

    staff_created = datetime(2023, 3, 1, tzinfo=timezone.utc)
    staff = [add_account('staff', staff_created + timedelta(days=30 * i), rng.choice(FIRST_NAMES),
                         rng.choice(LAST_NAMES), username=f'staff{i + 1:02d}') for i in range(8)]
    admins = [add_account('admin', staff_created, rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES),
                          username=f'admin{i + 1:02d}') for i in range(2)]
    tables['accounts'] = accounts

    # addresses: every customer has a default shipping address; about half also save a
    # separate billing address; some keep an extra (non-default) shipping address
    for c in customers:
        account_id = c['account']['account_id']
        created = c['account']['created_at']
        ship = dict(random_address(), address_type='SHIPPING', is_default=True)
        c['shipping'] = ship
        c['billing'] = ship
        entries = [ship]
        if rng.random() < 0.5:
            bill = dict(random_address() if rng.random() < 0.3 else ship, address_type='BILLING', is_default=True)
            c['billing'] = bill
            entries.append(bill)
        if rng.random() < 0.25:
            entries.append(dict(random_address(), address_type='SHIPPING', is_default=False))
        for entry in entries:
            tables['addresses'].append(dict(
                entry, address_id=len(tables['addresses']) + 1, account_id=account_id,
                created_at=created + timedelta(minutes=rng.randint(5, 600))))
    return customers, staff, admins


def order_times():
    """N_ORDERS timestamps across the year, following MONTH_WEIGHTS, sorted."""
    days = []
    d = START.date()
    while d < AS_OF.date():
        days.append(d)
        d += timedelta(days=1)
    weights = [MONTH_WEIGHTS[day.month] * (1.3 if day.weekday() >= 5 else 1.0) for day in days]
    picked = rng.choices(days, weights=weights, k=N_ORDERS)
    times = [datetime(p.year, p.month, p.day, tzinfo=timezone.utc)
             + timedelta(hours=rng.randint(13, 23), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
             for p in picked]
    return sorted(times)


def tracking_number(carrier_id):
    if carrier_id == 1:
        return ''.join(str(rng.randint(0, 9)) for _ in range(16))
    if carrier_id == 2:
        return ''.join(str(rng.randint(0, 9)) for _ in range(12))
    if carrier_id == 3:
        return '1Z' + ''.join(rng.choice('0123456789ABCDEFGHJKLMNPRSTUVWXYZ') for _ in range(16))
    return ''.join(str(rng.randint(0, 9)) for _ in range(12))


def payment_method():
    method = rng.choices(('CREDIT_CARD', 'DEBIT_CARD', 'PAYPAL', 'GIFT_CARD'), weights=(65, 15, 15, 5))[0]
    if method == 'CREDIT_CARD':
        brand = rng.choices(('Visa', 'Mastercard', 'Amex'), weights=(55, 35, 10))[0]
        return method, brand, f'{rng.randint(0, 9999):04d}'
    if method == 'DEBIT_CARD':
        return method, rng.choice(('Visa Debit', 'Mastercard Debit')), f'{rng.randint(0, 9999):04d}'
    return method, '', None


class Inventory:
    """Running stock per product; every change becomes an inventory_movements row."""

    def __init__(self, products):
        self.products = {p['product_id']: p for p in products}
        self.stock = {}
        self.last_change = {}
        self.restocks = []          # (product_id, qty, when, kind) for supplier invoices
        for p in products:
            self.move(p['product_id'], p['opening_stock'], 'RESTOCK', CATALOGUE_DATE + timedelta(hours=p['product_id']))

    def move(self, product_id, qty, reason, when, order_id=None):
        # Sales are applied in time order and every movement applied so far is dated at or
        # before the current order, so the running stock in time order never dips below zero.
        # Refund returns are added after the order loop; they only add stock, so dating them
        # earlier than later sales can't make any running total negative.
        new_stock = self.stock.get(product_id, 0) + qty
        assert new_stock >= 0, (product_id, qty)
        self.stock[product_id] = new_stock
        self.last_change[product_id] = max(when, self.last_change.get(product_id, when))
        tables['inventory_movements'].append({
            'movement_id': len(tables['inventory_movements']) + 1, 'product_id': product_id,
            'change_qty': qty, 'reason': reason, 'reference_order_id': order_id, 'created_at': when,
        })
        return when

    def restock(self, product_id, when, kind):
        product = self.products[product_id]
        qty = product['reorder_level'] * 3 + rng.randint(4, 12)
        when = self.move(product_id, qty, 'RESTOCK', when)
        self.restocks.append((product_id, qty, when, kind))

    def monthly_replenishment(self, when):
        # month-end stock count: a few corrections for damaged or miscounted items
        for pid in rng.sample(sorted(self.products), 4):
            delta = rng.choice((-2, -1, -1, 1)) if self.stock[pid] >= 2 else 1
            self.move(pid, delta, 'ADJUSTMENT', when - timedelta(hours=8))
        for pid, product in self.products.items():
            if product['is_active'] and self.stock[pid] <= product['reorder_level'] and rng.random() < 0.6:
                self.restock(pid, when, 'monthly')


def price_order(lines, ship_country, ship_region, method):
    subtotal = sum((l['line_total'] for l in lines), Decimal('0'))
    price, free_over = SHIPPING[method]
    shipping = Decimal('0.00') if free_over and subtotal >= Decimal(free_over) else Decimal(price)
    rate = Decimal(TAX_RATES[(ship_country, ship_region)]) / 100
    taxable = subtotal + (shipping if ship_country == 'CA' else 0)
    tax = money(taxable * rate)
    return money(subtotal), money(shipping), tax, money(subtotal + shipping + tax)


def build_orders(products, customers, inventory):
    active = [p for p in products if p['is_active']]
    times = order_times()
    month_marks = []
    m = date(START.year, START.month, 1)
    while datetime(m.year, m.month, 1, tzinfo=timezone.utc) < AS_OF:
        month_marks.append(datetime(m.year, m.month, 1, 6, tzinfo=timezone.utc))
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    next_mark = 0
    guest_seq = 0
    orders = []

    for created in times:
        while next_mark < len(month_marks) and month_marks[next_mark] <= created:
            if next_mark > 0:
                inventory.monthly_replenishment(month_marks[next_mark])
            next_mark += 1

        order_id = len(orders) + 1
        eligible = [c for c in customers if c['account']['created_at'] < created]
        if rng.random() < GUEST_SHARE or not eligible:
            guest_seq += 1
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            account, name = None, f'{first} {last}'
            email = f'guest{guest_seq:04d}@example.test'
            ship = random_address()
            bill = ship if rng.random() < 0.8 else random_address()
            account_age_days = 0
        else:
            c = rng.choices(eligible, weights=[e['weight'] for e in eligible])[0]
            account, name, email = c['account'], c['name'], None
            ship, bill = c['shipping'], c['billing']
            account_age_days = (created - account['created_at']).days

        n_lines = rng.choices((1, 2, 3, 4), weights=(35, 35, 20, 10))[0]
        picked = []
        while len(picked) < n_lines:
            p = rng.choices(active, weights=[a['weight'] for a in active])[0]
            if p not in picked:
                picked.append(p)
        lines = []
        for p in picked:
            qty = rng.choices((1, 2, 3), weights=(75, 20, 5))[0] if p['unit_price'] < 300 else 1
            lines.append({'product': p, 'quantity': qty, 'unit_price': p['unit_price'],
                          'line_total': money(p['unit_price'] * qty)})

        method = rng.choices(('STANDARD', 'EXPRESS', 'PRIORITY'), weights=(70, 22, 8))[0]
        subtotal, shipping, tax, total = price_order(lines, ship['country'], ship['region'], method)

        risk = Decimal(5) + Decimal(rng.randint(0, 10))
        if account is None:
            risk += 15
        if total > 800:
            risk += 15
        if account is not None and account_age_days < 30:
            risk += 20
        if ship['country'] != bill['country']:
            risk += 15
        risk = min(risk, Decimal(100))

        order = {
            'order_id': order_id, 'account_id': account['account_id'] if account else None,
            'status': 'PENDING_PAYMENT', 'contact_name': name, 'contact_email': email,
            'ship_line1': ship['line1'], 'ship_line2': ship['line2'], 'ship_city': ship['city'],
            'ship_region': ship['region'], 'ship_postal_code': ship['postal_code'], 'ship_country': ship['country'],
            'bill_line1': bill['line1'], 'bill_line2': bill['line2'], 'bill_city': bill['city'],
            'bill_region': bill['region'], 'bill_postal_code': bill['postal_code'], 'bill_country': bill['country'],
            'shipping_method': method, 'subtotal': subtotal, 'shipping_cost': shipping, 'tax_amount': tax,
            'total_amount': total, 'checkout_token': fake_uuid(), 'confirmed_payment_id': None,
            'risk_score': risk.quantize(CENTS), 'carrier_id': None, 'tracking_number': None,
            'created_at': created, 'updated_at': created, 'confirmed_at': None,
            'shipped_at': None, 'delivered_at': None,
        }
        orders.append(order)
        for line in lines:
            tables['order_items'].append({
                'order_item_id': len(tables['order_items']) + 1, 'order_id': order_id,
                'product_id': line['product']['product_id'], 'quantity': line['quantity'],
                'unit_price': line['unit_price'], 'line_total': line['line_total'],
            })
        order['_lines'] = lines

        # --- payment outcome -------------------------------------------------
        age = AS_OF - created
        if age < timedelta(days=1) and rng.random() < 0.5:
            continue                                   # still processing: no payment row yet
        pay_method, brand, last4 = payment_method()
        payment = {
            'payment_id': len(tables['payments']) + 1, 'order_id': order_id, 'amount': total,
            'method_type': pay_method, 'token': f'tok_fake_{fake_hex(24)}', 'last4': last4,
            'card_brand': brand, 'status': 'CAPTURED', 'gateway_ref': f'fake_ch_{fake_hex(16)}',
            'created_at': created + timedelta(seconds=rng.randint(3, 40)),
        }
        tables['payments'].append(payment)
        roll = rng.random()
        if roll < 0.05:
            payment.update(status='DECLINED', gateway_ref=None)
            order.update(status='PAYMENT_FAILED', updated_at=payment['created_at'])
            continue
        if roll < 0.08:
            payment['status'] = 'VOIDED'                 # customer cancelled before capture
            order.update(status='CANCELLED', updated_at=payment['created_at'] + timedelta(minutes=rng.randint(5, 90)))
            continue

        # stock check inside the "transaction": restock on demand or fail as out of stock
        short = [l for l in lines if inventory.stock[l['product']['product_id']] < l['quantity']]
        if short:
            if rng.random() < 0.6:
                payment['status'] = 'VOIDED'
                order.update(status='OUT_OF_STOCK', updated_at=payment['created_at'] + timedelta(seconds=2))
                continue
            for l in short:
                pid = l['product']['product_id']
                while inventory.stock[pid] < l['quantity']:
                    inventory.restock(pid, created - timedelta(hours=rng.randint(2, 48)), 'urgent')

        confirmed = payment['created_at'] + timedelta(seconds=rng.randint(1, 5))
        for l in lines:
            inventory.move(l['product']['product_id'], -l['quantity'], 'SALE', confirmed, order_id)
        order.update(status='CONFIRMED', confirmed_payment_id=payment['payment_id'],
                     confirmed_at=confirmed, updated_at=confirmed)

        # --- fulfilment ------------------------------------------------------
        shipped = confirmed + timedelta(hours=rng.randint(6, 72))
        if shipped >= AS_OF:
            continue
        if ship['country'] == 'CA':
            carrier_id = rng.choices((1, 2, 3, 4), weights=(45, 25, 15, 15))[0]
        else:
            carrier_id = rng.choice((3, 4))
        transit = CARRIER_BASE_DAYS[carrier_id] - {'STANDARD': 0, 'EXPRESS': 1, 'PRIORITY': 2}[method]
        transit = max(1, transit) + (2 if ship['country'] == 'US' else 0) + rng.choices((0, 1, 2, 4), weights=(50, 30, 15, 5))[0]
        delivered = shipped + timedelta(days=transit, hours=rng.randint(0, 8))
        order.update(status='SHIPPED', carrier_id=carrier_id, tracking_number=tracking_number(carrier_id),
                     shipped_at=shipped, updated_at=shipped)
        if delivered < AS_OF:
            order.update(status='DELIVERED', delivered_at=delivered, updated_at=delivered)

    # final replenishment marks after the last order
    while next_mark < len(month_marks):
        if next_mark > 0:
            inventory.monthly_replenishment(month_marks[next_mark])
        next_mark += 1
    return orders


def build_refunds(orders, customers, staff, admins, inventory):
    delivered = [o for o in orders if o['status'] == 'DELIVERED']
    payments = {p['payment_id']: p for p in tables['payments']}
    prior_refunds = defaultdict(int)
    reasons, reason_weights = [r[0] for r in REFUND_REASONS], [r[1] for r in REFUND_REASONS]
    restockable = {r[0]: r[2] for r in REFUND_REASONS}

    def add_refund(order, requested, amount, reason, lines_back):
        resolved = requested + timedelta(hours=rng.randint(6, 140))
        payment = payments[order['confirmed_payment_id']]
        ratio = amount / order['total_amount']
        risk = Decimal(5) + Decimal(30) * ratio + Decimal(12) * prior_refunds[order['account_id']]
        if order['account_id'] is None:
            risk += 10
        if order['total_amount'] > 800:
            risk += 10
        refund = {
            'refund_id': len(tables['refunds']) + 1, 'order_id': order['order_id'],
            'payment_id': payment['payment_id'], 'amount': amount, 'reason': reason,
            'status': 'REQUESTED', 'idempotency_key': fake_uuid(), 'requested_by': order['account_id'],
            'resolved_by': None, 'risk_score': min(risk, Decimal(100)).quantize(CENTS),
            'requested_at': requested, 'resolved_at': None,
        }
        if order['account_id']:
            prior_refunds[order['account_id']] += 1
        # the staff queue is a few days behind: recent requests are often still open
        backlog = requested > AS_OF - timedelta(days=12) and rng.random() < 0.6
        if resolved < AS_OF and not backlog:
            denied = rng.random() < (0.45 if refund['risk_score'] > 40 else 0.18)
            approved_only = not denied and resolved > AS_OF - timedelta(days=5)
            refund.update(status='DENIED' if denied else 'APPROVED' if approved_only else 'COMPLETED',
                          resolved_by=rng.choice(staff)['account_id'], resolved_at=resolved)
        tables['refunds'].append(refund)
        if refund['status'] == 'COMPLETED':
            if restockable[reason]:
                for line in lines_back:
                    inventory.move(line['product']['product_id'], line['quantity'], 'REFUND',
                                   resolved, order['order_id'])
            if amount == order['total_amount']:
                order.update(status='REFUNDED', updated_at=resolved)
                payment['status'] = 'REFUNDED'
        return refund

    for order in delivered:
        if rng.random() >= 0.30:
            continue
        requested = order['delivered_at'] + timedelta(days=rng.randint(1, 25), hours=rng.randint(0, 12))
        if requested >= AS_OF:
            continue
        reason = rng.choices(reasons, weights=reason_weights)[0]
        lines = order['_lines']
        if len(lines) == 1 or rng.random() < 0.35:
            amount, lines_back = order['total_amount'], lines          # full refund
        else:
            line = rng.choice(lines)
            amount, lines_back = line['line_total'], [line]           # one line returned
        first = add_refund(order, requested, amount, reason, lines_back)
        # a customer whose first request was denied sometimes asks again later
        if first['status'] == 'DENIED' and rng.random() < 0.35:
            again = first['resolved_at'] + timedelta(days=rng.randint(1, 6))
            if again < AS_OF:
                add_refund(order, again, amount, 'Not as described', lines_back)

    # duplicate attempts the database blocked (double clicks, retries, over-refunds)
    for refund in tables['refunds']:
        if rng.random() >= 0.14:
            continue
        kind = rng.choices(('SAME_KEY', 'OPEN_REFUND_EXISTS', 'EXCEEDS_ORDER_TOTAL'), weights=(60, 30, 10))[0]
        when = refund['requested_at'] + timedelta(seconds=rng.randint(1, 600))
        reviewed = when + timedelta(days=rng.randint(1, 10))
        reviewer = rng.choice(admins)['account_id'] if reviewed < AS_OF - timedelta(days=3) else None
        tables['duplicate_refund_attempts'].append({
            'attempt_id': len(tables['duplicate_refund_attempts']) + 1, 'order_id': refund['order_id'],
            'idempotency_key': refund['idempotency_key'] if kind == 'SAME_KEY' else fake_uuid(),
            'existing_refund_id': refund['refund_id'], 'attempt_reason': kind, 'created_at': when,
            'reviewed_by': reviewer, 'reviewed_at': reviewed if reviewer else None,
        })


def build_receivables():
    """One receivable per captured payment: the processor settles to Aria two days later."""
    for p in tables['payments']:
        if p['status'] not in ('CAPTURED', 'REFUNDED'):
            continue
        due = (p['created_at'] + timedelta(days=2)).date()
        settled = None
        if datetime(due.year, due.month, due.day, tzinfo=timezone.utc) < AS_OF:
            if rng.random() < 0.01:
                status = 'OVERDUE'
            else:
                status = 'PAID'
                settled = datetime(due.year, due.month, due.day, tzinfo=timezone.utc) + timedelta(hours=rng.randint(1, 30))
        else:
            status = 'OPEN'
        tables['accounts_receivable'].append({
            'ar_id': len(tables['accounts_receivable']) + 1, 'order_id': p['order_id'],
            'payment_id': p['payment_id'], 'amount_due': p['amount'], 'due_date': due,
            'status': status, 'settled_at': settled, 'created_at': p['created_at'],
        })


def payable_status(invoice_day, due):
    due_dt = datetime(due.year, due.month, due.day, tzinfo=timezone.utc)
    inv_dt = datetime(invoice_day.year, invoice_day.month, invoice_day.day, tzinfo=timezone.utc)
    if due_dt < AS_OF:
        if due_dt > AS_OF - timedelta(days=45) and rng.random() < 0.12:
            return 'OVERDUE', None
        return 'PAID', max(inv_dt + timedelta(days=1), due_dt - timedelta(days=rng.randint(0, 10)))
    if rng.random() < 0.25 and inv_dt + timedelta(days=2) < AS_OF:
        return 'PAID', inv_dt + timedelta(days=rng.randint(1, max(1, (AS_OF - inv_dt).days - 1)))
    return 'OPEN', None


def build_payables(products, orders, inventory):
    product_by_id = {p['product_id']: p for p in products}
    suppliers = {s['supplier_id']: s for s in tables['suppliers']}
    invoice_seq = defaultdict(int)

    def add(supplier_id, carrier_id, description, amount, invoice_day, terms):
        key = ('S', supplier_id) if supplier_id else ('C', carrier_id)
        invoice_seq[key] += 1
        prefix = f'SUP{supplier_id:02d}' if supplier_id else f'CAR{carrier_id}'
        due = invoice_day + timedelta(days=terms)
        status, paid_at = payable_status(invoice_day, due)
        tables['accounts_payable'].append({
            'ap_id': len(tables['accounts_payable']) + 1, 'supplier_id': supplier_id, 'carrier_id': carrier_id,
            'invoice_number': f'{prefix}-{invoice_day:%y%m}-{invoice_seq[key]:03d}', 'description': description,
            'amount_due': money(amount), 'invoice_date': invoice_day, 'due_date': due, 'status': status,
            'paid_at': paid_at,
            'created_at': datetime(invoice_day.year, invoice_day.month, invoice_day.day, 9, tzinfo=timezone.utc),
        })

    # supplier invoices: monthly replenishment grouped per supplier per month, urgent restocks billed alone
    monthly = defaultdict(list)
    for pid, qty, when, kind in inventory.restocks:
        product = product_by_id[pid]
        cost = product['unit_price'] * qty * Decimal('0.55')         # wholesale cost
        if kind == 'monthly':
            monthly[(product['supplier_id'], when.date())].append(cost)
        else:
            sid = product['supplier_id']
            add(sid, None, f'Urgent restock: {qty} x {product["sku"]}', cost, when.date(),
                suppliers[sid]['payment_terms_days'])
    for (sid, day), costs in sorted(monthly.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        add(sid, None, f'Monthly replenishment ({len(costs)} SKUs)', sum(costs), day,
            suppliers[sid]['payment_terms_days'])

    # carrier invoices: monthly, about 85% of the shipping we charged plus a base fee
    shipped = defaultdict(list)
    for o in orders:
        if o['shipped_at']:
            shipped[(o['carrier_id'], o['shipped_at'].year, o['shipped_at'].month)].append(o)
    for (cid, y, m), group in sorted(shipped.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])):
        invoice_day = date(y + (m == 12), m % 12 + 1, 1)
        if datetime(invoice_day.year, invoice_day.month, invoice_day.day, tzinfo=timezone.utc) >= AS_OF:
            continue
        charged = sum((o['shipping_cost'] for o in group), Decimal('0'))
        amount = Decimal('50') + charged * Decimal('0.85') + Decimal(len(group)) * Decimal('4.50')
        add(None, cid, f'{len(group)} shipments, {y}-{m:02d}', amount, invoice_day, 30)


def build_policy_documents():
    doc_id = 0
    for title, category, slug, version in POLICY_DOCUMENTS:
        for old_slug, old_version in POLICY_OLD_VERSIONS:
            if old_slug == slug:
                doc_id += 1
                tables['policy_documents'].append({
                    'document_id': doc_id, 'title': title, 'category': category,
                    'file_path': f'policies/{slug}.md', 'version': old_version, 'is_active': False,
                    'last_updated': datetime(2025, 3, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 120)),
                })
        doc_id += 1
        tables['policy_documents'].append({
            'document_id': doc_id, 'title': title, 'category': category,
            'file_path': f'policies/{slug}.md', 'version': version, 'is_active': True,
            'last_updated': datetime(2025, 8, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 400)),
        })


def finish_products(products, inventory):
    for p in products:
        pid = p['product_id']
        tables['products'].append({
            'product_id': pid, 'sku': p['sku'], 'name': p['name'], 'description': p['description'],
            'category_id': p['category_id'], 'unit_price': p['unit_price'], 'currency': p['currency'],
            'stock_quantity': inventory.stock[pid], 'reorder_level': p['reorder_level'],
            'is_active': p['is_active'], 'created_at': CATALOGUE_DATE,
            'updated_at': inventory.last_change[pid],
        })


# ---------------------------------------------------------------------------
# SQL output
# ---------------------------------------------------------------------------
COLUMNS = {
    'accounts': ('account_id', 'username', 'password_hash', 'account_type', 'created_at'),
    'profiles': ('profile_id', 'account_id', 'first_name', 'last_name', 'phone', 'email', 'created_at', 'updated_at'),
    'addresses': ('address_id', 'account_id', 'address_type', 'line1', 'line2', 'city', 'region', 'postal_code',
                  'country', 'is_default', 'created_at'),
    'categories': ('category_id', 'name', 'description'),
    'products': ('product_id', 'sku', 'name', 'description', 'category_id', 'unit_price', 'currency',
                 'stock_quantity', 'reorder_level', 'is_active', 'created_at', 'updated_at'),
    'carriers': ('carrier_id', 'name', 'tracking_url_template'),
    'suppliers': ('supplier_id', 'name', 'contact_email', 'phone', 'country', 'payment_terms_days', 'is_active',
                  'created_at'),
    'orders': ('order_id', 'account_id', 'status', 'contact_name', 'contact_email', 'ship_line1', 'ship_line2',
               'ship_city', 'ship_region', 'ship_postal_code', 'ship_country', 'bill_line1', 'bill_line2',
               'bill_city', 'bill_region', 'bill_postal_code', 'bill_country', 'shipping_method', 'subtotal',
               'shipping_cost', 'tax_amount', 'total_amount', 'checkout_token', 'confirmed_payment_id',
               'risk_score', 'carrier_id', 'tracking_number', 'created_at', 'updated_at', 'confirmed_at',
               'shipped_at', 'delivered_at'),
    'payments': ('payment_id', 'order_id', 'amount', 'method_type', 'token', 'last4', 'card_brand', 'status',
                 'gateway_ref', 'created_at'),
    'order_items': ('order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'line_total'),
    'inventory_movements': ('movement_id', 'product_id', 'change_qty', 'reason', 'reference_order_id', 'created_at'),
    'refunds': ('refund_id', 'order_id', 'payment_id', 'amount', 'reason', 'status', 'idempotency_key',
                'requested_by', 'resolved_by', 'risk_score', 'requested_at', 'resolved_at'),
    'duplicate_refund_attempts': ('attempt_id', 'order_id', 'idempotency_key', 'existing_refund_id',
                                  'attempt_reason', 'created_at', 'reviewed_by', 'reviewed_at'),
    'accounts_receivable': ('ar_id', 'order_id', 'payment_id', 'amount_due', 'due_date', 'status', 'settled_at',
                            'created_at'),
    'accounts_payable': ('ap_id', 'supplier_id', 'carrier_id', 'invoice_number', 'description', 'amount_due',
                         'invoice_date', 'due_date', 'status', 'paid_at', 'created_at'),
    'policy_documents': ('document_id', 'title', 'category', 'file_path', 'version', 'is_active', 'last_updated'),
}
# parents before children (orders <-> payments is a cycle; the deferred FK is checked at COMMIT)
INSERT_ORDER = ('accounts', 'profiles', 'addresses', 'categories', 'products', 'carriers', 'suppliers', 'orders',
                'payments', 'order_items', 'inventory_movements', 'refunds', 'duplicate_refund_attempts',
                'accounts_receivable', 'accounts_payable', 'policy_documents')
ID_COLUMNS = {t: c[0] for t, c in COLUMNS.items()}


def sql_value(v):
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S}+00'"
    if isinstance(v, (date, uuid.UUID)):
        return f"'{v}'"
    return "'" + str(v).replace("'", "''") + "'"


def render():
    out = [
        '-- Aria Phase 2: synthetic seed data. GENERATED by generate_seed.py; do not edit by hand.',
        f'-- Seed {SEED}, data as of {AS_OF:%Y-%m-%d}. All names, emails, phones, addresses and payment',
        '-- tokens are invented. Emails use example.test; phones use the fictional 555-01xx range;',
        '-- seed accounts have unusable password hashes, so nobody can log in as them.',
        '-- Run while connected to aria_phase2, after 01_tables.sql and 02_indexes.sql.',
        '--',
        '-- Row counts:',
    ]
    out += [f'--   {t:<27} {len(tables[t]):>5}' for t in INSERT_ORDER]
    out += ['', 'BEGIN;', '',
            '-- orders.confirmed_payment_id references payments, which reference orders.',
            '-- That FK is DEFERRABLE INITIALLY DEFERRED, so it is checked once at COMMIT.', '']
    for table in INSERT_ORDER:
        cols = COLUMNS[table]
        rows = tables[table]
        for start in range(0, len(rows), 100):
            out.append(f'INSERT INTO {table} ({", ".join(cols)}) VALUES')
            chunk = rows[start:start + 100]
            out.append(',\n'.join('    (' + ', '.join(sql_value(r[c]) for c in cols) + ')' for r in chunk) + ';')
            out.append('')
    out.append('-- identity columns continue after the explicit ids used above')
    out.append('DO $$')
    out.append('BEGIN')
    for table in INSERT_ORDER:
        col = ID_COLUMNS[table]
        out.append(f"    PERFORM setval(pg_get_serial_sequence('{table}', '{col}'), (SELECT max({col}) FROM {table}));")
    out += ['END $$;', '', 'COMMIT;', '']
    return '\n'.join(out)


def generate():
    products = build_catalogue()
    build_carriers_and_suppliers()
    customers, staff, admins = build_people()
    inventory = Inventory(products)
    orders = build_orders(products, customers, inventory)
    build_refunds(orders, customers, staff, admins, inventory)
    finish_products(products, inventory)
    tables['orders'] = orders
    build_receivables()
    build_payables(products, orders, inventory)
    build_policy_documents()
    return render()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='fail if 03_seed.sql is out of date')
    args = parser.parse_args()
    sql = generate()
    if args.check:
        current = OUTPUT.read_text(encoding='utf-8') if OUTPUT.exists() else ''
        if current != sql:
            raise SystemExit('03_seed.sql differs from the generator output; rerun generate_seed.py')
        print('03_seed.sql is up to date.')
        return
    OUTPUT.write_text(sql, encoding='utf-8', newline='\n')
    for table in INSERT_ORDER:
        print(f'{table:<27} {len(tables[table]):>5}')
    print(f'wrote {OUTPUT}')


if __name__ == '__main__':
    main()
