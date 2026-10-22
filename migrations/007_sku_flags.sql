-- Review flags from the last import (e.g. "Not in Master SKU list"). Informational, not master data.
ALTER TABLE core.sku ADD COLUMN review_flags text[] NOT NULL DEFAULT '{}';
