from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Account, Profile
from products.models import Category, Product


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

SAMPLE_ACCOUNTS = (
    ('reef_ranger', 'Avery', 'Morgan', 'avery.morgan@example.test', '555-0101'),
    ('coral_current', 'Jordan', 'Lee', 'jordan.lee@example.test', '555-0102'),
    ('blue_depths', 'Taylor', 'Kim', 'taylor.kim@example.test', '555-0103'),
    ('kelp_explorer', 'Riley', 'Patel', 'riley.patel@example.test', '555-0104'),
    ('tideline_trek', 'Casey', 'Nguyen', 'casey.nguyen@example.test', '555-0105'),
    ('nautical_nora', 'Nora', 'Bennett', 'nora.bennett@example.test', '555-0106'),
    ('scuba_sam', 'Sam', 'Rivera', 'sam.rivera@example.test', '555-0107'),
    ('ocean_orbit', 'Jamie', 'Wilson', 'jamie.wilson@example.test', '555-0108'),
    ('deep_blue_dev', 'Alex', 'Chen', 'alex.chen@example.test', '555-0109'),
    ('dive_admin', 'Morgan', 'Reed', 'morgan.reed@example.test', '555-0110'),
)


class Command(BaseCommand):
    help = 'Create repeatable sample accounts, profiles, categories, and dive products.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            default='aaaa',
            help='Password assigned to newly created sample accounts (development only).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        password_hash = make_password(options['password'])
        created_accounts = 0
        created_profiles = 0

        for index, (username, first_name, last_name, email, phone) in enumerate(SAMPLE_ACCOUNTS):
            account, was_created = Account.objects.get_or_create(
                username=username,
                defaults={
                    'password_hash': password_hash,
                    'account_type': 'admin' if index == len(SAMPLE_ACCOUNTS) - 1 else 'user',
                },
            )
            created_accounts += was_created
            _, profile_created = Profile.objects.get_or_create(
                account=account,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'phone': phone,
                },
            )
            created_profiles += profile_created

        categories = {}
        created_categories = 0
        for name, description in CATEGORIES.items():
            categories[name], was_created = Category.objects.get_or_create(
                name=name,
                defaults={'description': description},
            )
            created_categories += was_created

        product_data = list(PRODUCTS)
        for family_code, name, category_name, description, base_price in PRODUCT_FAMILIES:
            for variant_index, (variant_name, variant_description) in enumerate(
                PRODUCT_VARIANTS,
                1,
            ):
                price = Decimal(base_price) * (
                    Decimal('1') + Decimal(variant_index - 1) / 40
                )
                price = price.quantize(Decimal('0.01'))
                product_data.append((
                    f'GEN-{family_code}-{variant_index:02d}',
                    f'{variant_name} {name}',
                    category_name,
                    f'{description} {variant_description}',
                    str(price),
                    4 + (variant_index % 17),
                ))

        created_products = 0
        for sku, name, category_name, description, price, stock in product_data:
            _, was_created = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    'name': name,
                    'description': description,
                    'category': categories[category_name],
                    'unit_price': Decimal(price),
                    'currency': 'CAD',
                    'stock_quantity': stock,
                    'reorder_level': 5,
                },
            )
            created_products += was_created

        self.stdout.write(self.style.SUCCESS(
            'Sample data ready: '
            f'{created_accounts} accounts, {created_profiles} profiles, '
            f'{created_categories} categories, {created_products} products created.'
        ))
        self.stdout.write(
            'New sample accounts use the password provided with --password '
            '(default: aaaa). These credentials are for development only.'
        )
