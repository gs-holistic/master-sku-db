-- Every change records who, when, and the row before/after.
-- The actor comes from the session setting msku.actor (set by the importer / app), else current_user.
CREATE TABLE ops.audit_log (
  id          bigserial PRIMARY KEY,
  table_name  text        NOT NULL,
  row_pk      text        NOT NULL,
  action      text        NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')),
  actor       text        NOT NULL,
  at          timestamptz NOT NULL DEFAULT now(),
  before      jsonb,
  after       jsonb
);
CREATE INDEX ON ops.audit_log (table_name, row_pk);

CREATE FUNCTION ops.audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pk text; actor text := coalesce(nullif(current_setting('msku.actor', true), ''), current_user);
BEGIN
  IF TG_OP = 'DELETE' THEN pk := to_jsonb(OLD)->>TG_ARGV[0]; ELSE pk := to_jsonb(NEW)->>TG_ARGV[0]; END IF;
  IF TG_OP = 'UPDATE' AND to_jsonb(OLD) = to_jsonb(NEW) THEN RETURN NEW; END IF;
  INSERT INTO ops.audit_log (table_name, row_pk, action, actor, before, after)
  VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, pk, TG_OP, actor,
          CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
          CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
  RETURN coalesce(NEW, OLD);
END $$;

-- updated_at / version only move when the row really changes, so re-running an import changes nothing.
CREATE FUNCTION ops.touch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF (to_jsonb(NEW) - 'updated_at' - 'version') = (to_jsonb(OLD) - 'updated_at' - 'version') THEN
      NEW.updated_at := OLD.updated_at; NEW.version := OLD.version; RETURN NEW;
    END IF;
    NEW.version := OLD.version + 1;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- Attach both triggers to a table: SELECT ops.track('core.sku', 'id');
CREATE FUNCTION ops.track(tbl regclass, pk_col text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('CREATE TRIGGER touch BEFORE INSERT OR UPDATE ON %s FOR EACH ROW EXECUTE FUNCTION ops.touch()', tbl);
  EXECUTE format('CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION ops.audit(%L)', tbl, pk_col);
END $$;
