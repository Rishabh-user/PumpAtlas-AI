-- Where a vendor contact came from.
--
-- Apply as the schema OWNER, not as pumpatlas_app: the application role has no DDL
-- rights on purpose, so the running service cannot alter its own schema.
--
--   python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --file db/migrations/002_vendor_contact_provenance.sql
--
-- or paste it into the provider's SQL console. Idempotent: safe to run twice.
--
-- `vendor_contacts` had no column naming a source, so a phone number written there by
-- the crawler would be a value in a procurement file with nothing behind it - the one
-- thing this platform promises never to hold. That is why contact details found on a
-- page were offered for a person to accept rather than recorded automatically.
--
-- These three columns remove the reason for that. `source_id` is the captured page the
-- detail was read from, `captured_at` is when, and `origin` says whether a person or the
-- pipeline put it there - the same distinction `field_provenance.value_origin` draws for
-- every other stored value.
--
-- Nullable throughout: contacts entered by hand before this migration have no source,
-- and inventing one for them would be worse than leaving it empty.

BEGIN;

ALTER TABLE vendor_contacts
    ADD COLUMN IF NOT EXISTS source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS origin VARCHAR(24);

COMMENT ON COLUMN vendor_contacts.source_id IS
    'The captured page this detail was read from. Null for contacts entered by hand.';
COMMENT ON COLUMN vendor_contacts.captured_at IS
    'When the page carrying this detail was captured.';
COMMENT ON COLUMN vendor_contacts.origin IS
    'manual | ai_extraction - who put the value here, mirroring field_provenance.';

-- Finding a vendor's auto-recorded contacts, and finding every contact taken from one
-- page when that page turns out to be wrong.
CREATE INDEX IF NOT EXISTS ix_vendor_contacts_source
    ON vendor_contacts (source_id)
    WHERE source_id IS NOT NULL;

COMMIT;
