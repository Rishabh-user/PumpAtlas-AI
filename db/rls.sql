-- =====================================================================
-- PumpAtlas AI - row level security
--
-- Tenant isolation is enforced in the database, not only in the API. The
-- application sets two GUCs per transaction (see backend/app/core/db.py):
--
--   app.tenant_id         the acting tenant's UUID ('' for platform staff)
--   app.is_platform_admin 'on' when the actor may cross tenant boundaries
--
-- Read rule : own tenant rows + shared master rows (tenant_id IS NULL)
-- Write rule: own tenant rows only; shared master is platform-admin territory
--
-- IMPORTANT: the application role must NOT have the BYPASSRLS attribute and
-- must not own these tables, otherwise policies are skipped. Create it as:
--   CREATE ROLE pumpatlas_app LOGIN PASSWORD '...' NOBYPASSRLS;
-- =====================================================================

CREATE OR REPLACE FUNCTION pumpatlas_current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.tenant_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION pumpatlas_is_platform_admin() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.is_platform_admin', true), 'off') = 'on';
$$;

-- ---------------------------------------------------------------------
-- Tables carrying a nullable tenant_id where NULL means "shared master"
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t text;
    shared_master_tables text[] := ARRAY[
        'vendors', 'vendor_contacts', 'pumps', 'pump_models',
        'technical_specs', 'commercial_specs', 'dimensional_specs',
        'delivery_specs', 'operational_specs', 'administrative_specs',
        'documents', 'sources', 'extracted_entities', 'ai_jobs',
        'search_index', 'field_provenance', 'tags'
    ];
BEGIN
    FOREACH t IN ARRAY shared_master_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);

        EXECUTE format('DROP POLICY IF EXISTS %I_tenant_read ON %I', t, t);
        EXECUTE format($f$
            CREATE POLICY %I_tenant_read ON %I FOR SELECT USING (
                pumpatlas_is_platform_admin()
                OR tenant_id = pumpatlas_current_tenant()
                OR tenant_id IS NULL
            )$f$, t, t);

        EXECUTE format('DROP POLICY IF EXISTS %I_tenant_write ON %I', t, t);
        EXECUTE format($f$
            CREATE POLICY %I_tenant_write ON %I FOR ALL USING (
                pumpatlas_is_platform_admin()
                OR tenant_id = pumpatlas_current_tenant()
            ) WITH CHECK (
                pumpatlas_is_platform_admin()
                OR tenant_id = pumpatlas_current_tenant()
            )$f$, t, t);
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------
-- Strictly tenant-private tables: no shared-master read-through
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t text;
    private_tables text[] := ARRAY[
        'import_batches', 'crawl_schedules', 'confidence_scores',
        'data_quality_flags', 'ai_suggestions', 'duplicate_candidates',
        'requirement_profiles', 'comparisons', 'comparison_items',
        'saved_searches', 'tagged_records', 'record_versions',
        'audit_logs', 'tenant_permissions', 'api_keys',
        -- A client's approved supplier list tells a competitor who they will buy from,
        -- and a registration identifier is theirs alone. Strictly private: no
        -- shared-master read-through, unlike `vendors` itself.
        'vendor_approvals', 'vendor_identifiers'
    ];
BEGIN
    FOREACH t IN ARRAY private_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I_tenant_isolation ON %I', t, t);
        EXECUTE format($f$
            CREATE POLICY %I_tenant_isolation ON %I FOR ALL USING (
                pumpatlas_is_platform_admin()
                OR tenant_id = pumpatlas_current_tenant()
            ) WITH CHECK (
                pumpatlas_is_platform_admin()
                OR tenant_id = pumpatlas_current_tenant()
            )$f$, t, t);
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------
-- users: a tenant sees only its own members; platform staff (tenant_id IS
-- NULL) are visible to platform admins only.
-- ---------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_tenant_isolation ON users;
CREATE POLICY users_tenant_isolation ON users FOR ALL USING (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
) WITH CHECK (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
);

-- ---------------------------------------------------------------------
-- tenants: a client user may read its own tenant row only.
-- ---------------------------------------------------------------------
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenants_self_read ON tenants;
CREATE POLICY tenants_self_read ON tenants FOR SELECT USING (
    pumpatlas_is_platform_admin() OR id = pumpatlas_current_tenant()
);
DROP POLICY IF EXISTS tenants_admin_write ON tenants;
CREATE POLICY tenants_admin_write ON tenants FOR ALL USING (
    pumpatlas_is_platform_admin()
) WITH CHECK (
    pumpatlas_is_platform_admin()
);

-- ---------------------------------------------------------------------
-- roles is global reference data: readable by everyone, writable by admins.
--
-- FORCE matters here as much as anywhere else. A table owner bypasses row level
-- security unless it is forced, and on a managed database (Render, RDS, Cloud SQL) the
-- role you are given usually *is* the owner. Without FORCE, any tenant could rewrite
-- the role definitions.
-- ---------------------------------------------------------------------
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS roles_read_all ON roles;
CREATE POLICY roles_read_all ON roles FOR SELECT USING (true);
DROP POLICY IF EXISTS roles_admin_write ON roles;
CREATE POLICY roles_admin_write ON roles FOR ALL USING (pumpatlas_is_platform_admin())
    WITH CHECK (pumpatlas_is_platform_admin());

-- user_roles is joined through users, which is already protected.
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_roles_via_user ON user_roles;
CREATE POLICY user_roles_via_user ON user_roles FOR ALL USING (
    pumpatlas_is_platform_admin()
    OR EXISTS (
        SELECT 1 FROM users u
         WHERE u.id = user_roles.user_id
           AND u.tenant_id = pumpatlas_current_tenant()
    )
) WITH CHECK (
    pumpatlas_is_platform_admin()
    OR EXISTS (
        SELECT 1 FROM users u
         WHERE u.id = user_roles.user_id
           AND u.tenant_id = pumpatlas_current_tenant()
    )
);
