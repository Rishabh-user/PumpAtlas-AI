-- Structure for the facts a client's own documents carry.
--
-- Apply as the schema OWNER, not as pumpatlas_app: the application role has no DDL
-- rights on purpose, so the running service cannot alter its own schema.
--
--   python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --file db/migrations/003_client_vendor_structure.sql
--
-- Idempotent: safe to run twice.
--
-- WHY
--
-- Three document types were imported into this platform: a signed approved suppliers
-- list, a project package list, and five SAP vendor-master exports. The import kept
-- every column - nothing was lost - but kept most of it inside `vendors.extra` as JSON,
-- because there was nowhere else for it to go. That is fine as a holding pen and wrong
-- as a destination: 333 approval statements and 1,404 sets of registration identifiers
-- cannot be queried, cannot be indexed, do not appear in the API, and do not show on the
-- vendor page.
--
-- What this adds is the structure those facts were always entitled to. It is deliberately
-- not "a column per spreadsheet heading": of the 59 columns in the SAP export, 17 are
-- empty on all 2,534 rows and several are the same value under a second heading. The
-- test applied to each was whether the platform can answer a question with it.

BEGIN;

-- ---------------------------------------------------------------- vendor identity
--
-- Columns the exports populate on nearly every row and this schema had nowhere to put.
-- `hq_city` and `hq_country` already existed; the street and the state did not, so an
-- address was arriving complete and being stored as a city.
ALTER TABLE vendors
    ADD COLUMN IF NOT EXISTS address_line VARCHAR(500),
    ADD COLUMN IF NOT EXISTS state_region VARCHAR(120),
    ADD COLUMN IF NOT EXISTS legal_entity_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS client_since DATE,
    ADD COLUMN IF NOT EXISTS is_purchasing_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS purchasing_block_note TEXT;

COMMENT ON COLUMN vendors.address_line IS
    'Street address as the source states it; city, state and country have their own columns.';
COMMENT ON COLUMN vendors.state_region IS
    'State, province or county. 100% populated in the client SAP exports, 145 distinct values.';
COMMENT ON COLUMN vendors.legal_entity_name IS
    'Registered name where it differs from the trading name. Previously only in extra.discovery.';
COMMENT ON COLUMN vendors.client_since IS
    'When this client first opened an account with the supplier (SAP "Vendor Cr. Date").';
COMMENT ON COLUMN vendors.is_purchasing_blocked IS
    'The client has barred purchasing from this supplier. A procurement fact, not a status we inferred.';

-- ------------------------------------------------------------- approvals per package
--
-- The central fact in a signed approved suppliers list: *this* engineering authority
-- approved *this* vendor for *this* equipment package, on *this* project. It was being
-- flattened into `product_families` (which loses the project and the authority) and
-- `extra.approved_packages` (which loses queryability).
--
-- One row per statement, so "who may supply sea water injection pumps on KG-DWN-98/2"
-- is a query rather than a JSON scan, and so an approval can expire on its own date
-- rather than the whole vendor being approved forever.
CREATE TABLE IF NOT EXISTS vendor_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    project VARCHAR(160) NOT NULL,
    package VARCHAR(300) NOT NULL,
    approved_country VARCHAR(160),
    status VARCHAR(32) NOT NULL DEFAULT 'approved',
    document_reference VARCHAR(300),
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    approved_on DATE,
    expires_on DATE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vendor_approval UNIQUE (vendor_id, project, package)
);

COMMENT ON TABLE vendor_approvals IS
    'One statement from a client document that a vendor may supply one package on one project.';
COMMENT ON COLUMN vendor_approvals.approved_country IS
    'Countries as the document writes them - "UK / Brazil / India" - kept verbatim; the
     document is the authority on what it said.';
COMMENT ON COLUMN vendor_approvals.document_reference IS
    'The document number, e.g. 20171-SPOG-14100-PM-LS-0002 D0, so an answer can cite it.';

CREATE INDEX IF NOT EXISTS ix_vendor_approvals_vendor ON vendor_approvals (vendor_id);
CREATE INDEX IF NOT EXISTS ix_vendor_approvals_project ON vendor_approvals (tenant_id, project);
CREATE INDEX IF NOT EXISTS ix_vendor_approvals_package ON vendor_approvals (package);

-- ------------------------------------------------------- registration identifiers
--
-- A scheme-keyed child table rather than a column per tax regime. The exports carry GST,
-- PAN, MSME, VAT and an SAP vendor number; a Norwegian or Brazilian list would carry
-- entirely different ones, and each would otherwise be another migration and another
-- mostly-empty column. `scheme` is text on purpose: a new identifier is a row.
--
-- This is also how a buyer finds a company they only have a tax number for.
CREATE TABLE IF NOT EXISTS vendor_identifiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    scheme VARCHAR(40) NOT NULL,
    value VARCHAR(120) NOT NULL,
    issued_country VARCHAR(2),
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    captured_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vendor_identifier UNIQUE (vendor_id, scheme, value)
);

COMMENT ON TABLE vendor_identifiers IS
    'Registration and tax identifiers: gst, pan, msme, vat, sap_vendor_no, duns.';
COMMENT ON COLUMN vendor_identifiers.scheme IS
    'Lowercase scheme name. Text rather than an enum so a new regime costs a row, not a migration.';

CREATE INDEX IF NOT EXISTS ix_vendor_identifiers_vendor ON vendor_identifiers (vendor_id);
CREATE INDEX IF NOT EXISTS ix_vendor_identifiers_lookup ON vendor_identifiers (scheme, value);

-- ----------------------------------------------------------------------- isolation
--
-- Both tables are **strictly tenant-private**, the same group as `import_batches` and
-- `audit_logs` in db/rls.sql - not the shared-master group that `vendors` belongs to.
-- The difference matters: a shared-master policy reads through `tenant_id IS NULL` rows
-- to every tenant, and an approved supplier list read by the wrong client is the exact
-- disclosure this data must never suffer. These rows always carry a tenant, and a NULL
-- one would be visible to nobody rather than everybody.
--
-- Written with the same helper functions the rest of the schema uses, so there is one
-- definition of "is this caller platform staff" rather than two that can drift.
ALTER TABLE vendor_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_approvals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS vendor_approvals_tenant_isolation ON vendor_approvals;
CREATE POLICY vendor_approvals_tenant_isolation ON vendor_approvals FOR ALL USING (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
) WITH CHECK (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
);

ALTER TABLE vendor_identifiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_identifiers FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS vendor_identifiers_tenant_isolation ON vendor_identifiers;
CREATE POLICY vendor_identifiers_tenant_isolation ON vendor_identifiers FOR ALL USING (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
) WITH CHECK (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
);

-- `app_role.sql` grants on ALL TABLES at setup time, which does not reach a table
-- created afterwards; its ALTER DEFAULT PRIVILEGES only covers tables created by the
-- role that ran it. Granted explicitly so the application can read what it just gained.
GRANT SELECT, INSERT, UPDATE, DELETE ON vendor_approvals TO pumpatlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON vendor_identifiers TO pumpatlas_app;

COMMIT;
