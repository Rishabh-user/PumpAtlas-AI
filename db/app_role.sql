-- =====================================================================
-- PumpAtlas AI - the application database role
--
-- Row level security is bypassed entirely by superusers and by any role with
-- BYPASSRLS. The bootstrap role that creates the schema is a superuser, so the
-- application must NOT use it - otherwise every tenant policy is silently inert and
-- the isolation you think you have does not exist.
--
-- This creates a dedicated NOBYPASSRLS role for the application and the workers.
-- Migrations keep running as the owner; the app connects as pumpatlas_app.
-- =====================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pumpatlas_app') THEN
        -- Change this password outside local development.
        CREATE ROLE pumpatlas_app LOGIN PASSWORD 'pumpatlas_app' NOBYPASSRLS;
    END IF;
END
$$;

-- PUBLIC usually holds CONNECT by default, but a hardened database revokes it.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO pumpatlas_app', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO pumpatlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pumpatlas_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pumpatlas_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO pumpatlas_app;

-- Tables created later (a migration, for instance) are covered automatically.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pumpatlas_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO pumpatlas_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO pumpatlas_app;
