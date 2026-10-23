-- MAP (minimum advertised price for B2B customers) is its own price tier, separate from the B2C MSRP.
ALTER TYPE core.price_tier ADD VALUE IF NOT EXISTS 'map' AFTER 'msrp';
