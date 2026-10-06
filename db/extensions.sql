-- =====================================================================
-- PumpAtlas AI - required PostgreSQL extensions
-- Run first, as a superuser or a role with CREATE privilege on the database.
-- =====================================================================

-- gen_random_uuid() for primary keys
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- trigram similarity: fuzzy vendor/model matching and duplicate detection
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- accent-insensitive full-text search (Sulzer / Sulzér, Hidrostal / Hidrostál)
CREATE EXTENSION IF NOT EXISTS unaccent;

-- GIN over scalar columns, so one index can cover tsvector + btree predicates
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- =====================================================================
-- Search configuration: English stemming with accents folded away.
-- Used by every to_tsvector() call in the platform so indexing and querying
-- always agree.
-- =====================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'pumpatlas') THEN
        CREATE TEXT SEARCH CONFIGURATION pumpatlas ( COPY = english );
        ALTER TEXT SEARCH CONFIGURATION pumpatlas
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, english_stem;
    END IF;
END
$$;
