INSERT INTO products (sku, name, description, category_id, unit_price, currency, stock_quantity, reorder_level, is_active, created_at, updated_at)
VALUES
    ('DIVE-MASK-001', 'AquaView Dive Mask', 'Tempered-glass mask with a soft silicone skirt.', 1, 59.99, 'CAD', 25, 8, true, NOW(), NOW()),
    ('DIVE-FIN-001', 'CurrentFlex Open-Heel Fins', 'Adjustable open-heel fins for recreational scuba diving.', 2, 129.99, 'CAD', 18, 6, true, NOW(), NOW()),
    ('DIVE-BCD-001', 'BuoyancyPro BCD', 'Adjustable buoyancy compensator with integrated weight pockets.', 3, 649.99, 'CAD', 7, 3, true, NOW(), NOW()),
    ('DIVE-REG-001', 'DeepFlow Regulator Set', 'Balanced first and second stages with alternate air source.', 4, 749.99, 'CAD', 6, 3, true, NOW(), NOW()),
    ('DIVE-WET-001', 'ThermoWave 3mm Wetsuit', 'Full-length neoprene wetsuit for temperate-water diving.', 5, 279.99, 'CAD', 12, 4, true, NOW(), NOW()),
    ('DIVE-COMP-001', 'DepthTrack Dive Computer', 'Wrist-mounted dive computer with depth and dive-time tracking.', 6, 399.99, 'CAD', 9, 3, true, NOW(), NOW()),
    ('SNORK-SET-001', 'Coastline Snorkel Set', 'Mask, snorkel, and fins for recreational snorkeling.', 1, 89.99, 'CAD', 20, 6, true, NOW(), NOW()),
    ('WATER-DRY-001', 'SealSafe Dry Bag 20L', 'Water-resistant roll-top bag for watersports essentials.', 7, 34.99, 'CAD', 30, 10, true, NOW(), NOW())
ON CONFLICT (sku) DO NOTHING;

INSERT INTO categories (name, description)
VALUES
    ('Masks & Snorkels', 'Dive masks and snorkels for underwater exploration.'),
    ('Fins', 'Swimming and diving fins for improved mobility.'),
    ('Buoyancy Compensators', 'BCDs for controlling buoyancy during dives.'),
    ('Regulators', 'Dive regulators for breathing underwater.'),
    ('Exposure Protection', 'Wetsuits and drysuits for thermal protection.'),
    ('Dive Computers', 'Dive computers for tracking depth and dive time.'),
    ('Watersports Accessories', 'Accessories for various watersports activities.')
ON CONFLICT (name) DO NOTHING;