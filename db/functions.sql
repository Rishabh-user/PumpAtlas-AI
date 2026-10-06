-- =====================================================================
-- PumpAtlas AI - functions and triggers
-- Apply after db/schema.sql
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Search vector maintenance
--    Weighting: A = identity (vendor, pump, model code)
--               B = classification (type, standard, service, certifications)
--               C = free text summary
--               D = everything else in the haystack
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_search_vector() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.search_vector :=
          setweight(to_tsvector('pumpatlas', coalesce(NEW.vendor_name, '')), 'A')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.pump_name, '')), 'A')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.model_code, '')), 'A')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.pump_type::text, '')), 'B')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.applicable_standard::text, '')), 'B')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.service_application, '')), 'B')
       || setweight(to_tsvector('pumpatlas',
              coalesce(array_to_string(NEW.certifications, ' '), '')), 'B')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.summary, '')), 'C')
       || setweight(to_tsvector('pumpatlas', coalesce(NEW.searchable_text, '')), 'D');
    NEW.indexed_at := now();
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_search_index_vector ON search_index;
CREATE TRIGGER trg_search_index_vector
    BEFORE INSERT OR UPDATE ON search_index
    FOR EACH ROW EXECUTE FUNCTION pumpatlas_search_vector();

-- ---------------------------------------------------------------------
-- 2. Spec versioning
--    A spec row is never updated in place. Inserting a new version for a
--    pump model automatically retires the previous current row.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_supersede_previous_spec() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.is_current THEN
        EXECUTE format(
            'UPDATE %I SET is_current = false, superseded_at = now()
              WHERE pump_model_id = $1 AND id <> $2 AND is_current',
            TG_TABLE_NAME
        ) USING NEW.pump_model_id, NEW.id;
    END IF;
    RETURN NEW;
END
$$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'technical_specs', 'commercial_specs', 'dimensional_specs',
        'delivery_specs', 'operational_specs', 'administrative_specs'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_supersede ON %I', t, t);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_supersede AFTER INSERT ON %I
               FOR EACH ROW EXECUTE FUNCTION pumpatlas_supersede_previous_spec()', t, t);
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------
-- 3. Field provenance: only one current row per (entity, field)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_supersede_provenance() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.is_current THEN
        UPDATE field_provenance
           SET is_current = false
         WHERE entity_type = NEW.entity_type
           AND entity_id   = NEW.entity_id
           AND field_name  = NEW.field_name
           AND id <> NEW.id
           AND is_current;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_field_provenance_supersede ON field_provenance;
CREATE TRIGGER trg_field_provenance_supersede
    AFTER INSERT ON field_provenance
    FOR EACH ROW EXECUTE FUNCTION pumpatlas_supersede_provenance();

-- ---------------------------------------------------------------------
-- 4. Vendor name normalisation - the deterministic half of dedupe
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_normalize_company_name(raw text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT trim(regexp_replace(
        regexp_replace(
            lower(unaccent(coalesce(raw, ''))),
            '\y(gmbh|ag|s\.?p\.?a|s\.?a\.?s|s\.?a|srl|s\.?r\.?l|bv|b\.v|nv|n\.v|ltd|limited|llc|inc|incorporated|corp|corporation|co|company|plc|pte|pty|kk|oy|ab|as|a/s|jsc|ooo|pjsc|holdings?|group|international|industries|manufacturing)\y',
            ' ', 'g'),
        '[^a-z0-9]+', ' ', 'g'));
$$;

-- ---------------------------------------------------------------------
-- 5. updated_at maintenance for tables the ORM does not touch directly
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;
