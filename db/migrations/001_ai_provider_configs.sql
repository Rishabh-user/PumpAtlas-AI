-- AI provider settings, moved out of .env and into the platform.
--
-- Apply as the schema OWNER, not as pumpatlas_app: the application role has no DDL
-- rights on purpose, so the running service cannot alter its own schema.
--
--   python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --file db/migrations/001_ai_provider_configs.sql
--
-- or paste it into the provider's SQL console. Idempotent: safe to run twice.
--
-- The table holds Fernet ciphertext in encrypted_api_key, keyed off SECRET_KEY, which
-- stays in the environment. Rotating SECRET_KEY makes every stored key unreadable and
-- they have to be re-entered - correct, and better than failing quietly mid-run.

BEGIN;

CREATE TABLE IF NOT EXISTS ai_provider_configs (
    label VARCHAR(120) NOT NULL,
    provider VARCHAR(40) NOT NULL,
    role VARCHAR(20) NOT NULL,
    model VARCHAR(120),
    encrypted_api_key TEXT NOT NULL,
    key_hint VARCHAR(24),
    base_url VARCHAR(255),
    timeout_seconds INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    last_check_ok BOOLEAN,
    last_check_detail TEXT,
    created_by_user_id UUID,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_ai_provider_configs PRIMARY KEY (id),
    CONSTRAINT uq_ai_provider_configs_label_role UNIQUE (label, role)
);

-- At most one active configuration per role. Enforced here rather than in Python:
-- "two active search providers" is not a state the platform can be in, because the
-- runner would have to pick one arbitrarily and the screen would show something untrue.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_provider_configs_one_active_per_role
    ON ai_provider_configs (role) WHERE is_active;

-- Deliberately NOT tenant scoped and NOT row-level secured. Which model reads a
-- datasheet is one operational choice for the whole installation; the API restricts it
-- to platform administrators instead.
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_provider_configs TO pumpatlas_app;

COMMIT;
