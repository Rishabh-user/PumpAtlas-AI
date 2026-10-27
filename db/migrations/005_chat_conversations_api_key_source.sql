-- Chat history: record which tenant asked, including questions put by an API key.
--
-- Apply as the schema OWNER, after 004:
--
--   python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --file db/migrations/005_chat_conversations_api_key_source.sql
--
-- Idempotent: safe to run twice.
--
-- A question another application asks /chat/ask with an API key has no person behind it,
-- so the thread belongs to the key's tenant instead: user_id becomes nullable, and the
-- key (and its name, which outlives the key) is recorded. `source` tells the two kinds
-- apart. Tenant isolation is unchanged - the RLS policies from 004 already key on tenant_id.

BEGIN;

ALTER TABLE chat_conversations ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS api_key_id UUID;
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'app';
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS source_label VARCHAR(160);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_chat_conversations_api_key_id'
    ) THEN
        ALTER TABLE chat_conversations
            ADD CONSTRAINT fk_chat_conversations_api_key_id
            FOREIGN KEY (api_key_id) REFERENCES api_keys (id) ON DELETE SET NULL;
    END IF;
END
$$;

COMMENT ON COLUMN chat_conversations.source IS 'app | api_key';
COMMENT ON COLUMN chat_conversations.source_label IS 'The API key''s name, kept so a thread outlives its key';

CREATE INDEX IF NOT EXISTS ix_chat_conversations_tenant_updated
    ON chat_conversations (tenant_id, updated_at);

COMMIT;
