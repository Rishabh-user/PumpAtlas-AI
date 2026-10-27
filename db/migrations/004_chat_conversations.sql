-- Chat history, moved out of the browser's localStorage and into the platform.
--
-- Apply as the schema OWNER, not as pumpatlas_app (no DDL rights, on purpose):
--
--   python scripts/apply_schema.py --url "postgresql://OWNER:PASSWORD@HOST/DB?sslmode=require" --file db/migrations/004_chat_conversations.sql
--
-- Idempotent: safe to run twice.
--
-- A conversation is a transcript, not evidence. These tables are never read by search,
-- scoring or the capture pipeline; the only route from an answer to a stored fact is
-- still discovery, with a verbatim quote per field.
--
-- Tenant-private (RLS), and additionally private to the user who asked: the API only
-- ever returns a user's own threads, even to a colleague in the same tenant.

BEGIN;

CREATE TABLE IF NOT EXISTS chat_conversations (
    user_id UUID NOT NULL,
    title VARCHAR(120) NOT NULL,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    tenant_id UUID,
    CONSTRAINT pk_chat_conversations PRIMARY KEY (id),
    CONSTRAINT fk_chat_conversations_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_chat_conversations_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_turns (
    conversation_id UUID NOT NULL,
    position INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer JSONB,
    failed TEXT,
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    tenant_id UUID,
    CONSTRAINT pk_chat_turns PRIMARY KEY (id),
    CONSTRAINT uq_chat_turns_conversation_id_position UNIQUE (conversation_id, position),
    CONSTRAINT fk_chat_turns_conversation_id FOREIGN KEY (conversation_id) REFERENCES chat_conversations (id) ON DELETE CASCADE,
    CONSTRAINT fk_chat_turns_tenant_id FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

COMMENT ON COLUMN chat_turns.answer IS 'The answer exactly as /chat/ask returned it, citations included';
COMMENT ON COLUMN chat_turns.failed IS 'Set when the question failed, so a reopened thread says so';

CREATE INDEX IF NOT EXISTS ix_chat_conversations_tenant_id ON chat_conversations (tenant_id);
CREATE INDEX IF NOT EXISTS ix_chat_conversations_user_updated ON chat_conversations (user_id, updated_at);
CREATE INDEX IF NOT EXISTS ix_chat_turns_conversation_id ON chat_turns (conversation_id);
CREATE INDEX IF NOT EXISTS ix_chat_turns_tenant_id ON chat_turns (tenant_id);

-- Strictly tenant-private, same policy as the other private tables in db/rls.sql.
ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_conversations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chat_conversations_tenant_isolation ON chat_conversations;
CREATE POLICY chat_conversations_tenant_isolation ON chat_conversations FOR ALL USING (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
) WITH CHECK (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
);

ALTER TABLE chat_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_turns FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chat_turns_tenant_isolation ON chat_turns;
CREATE POLICY chat_turns_tenant_isolation ON chat_turns FOR ALL USING (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
) WITH CHECK (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON chat_conversations TO pumpatlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON chat_turns TO pumpatlas_app;

COMMIT;
