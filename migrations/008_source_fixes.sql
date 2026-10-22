-- Values in other systems that disagree with the source we trust (e.g. Cin7 price tiers vs the price list).
-- Not conflicts: the rule already decides. This is a to-do list for whoever maintains that system.
CREATE TABLE ops.source_fix (
  sku_code text NOT NULL, field text NOT NULL, source text NOT NULL,
  source_value text NOT NULL, correct_value text NOT NULL, source_ref text, correct_ref text,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','fixed')),
  first_seen date NOT NULL DEFAULT current_date, last_seen date NOT NULL DEFAULT current_date,
  PRIMARY KEY (sku_code, field, source));
GRANT SELECT ON ops.source_fix TO msku_editor;
