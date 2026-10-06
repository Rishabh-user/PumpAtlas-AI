-- =====================================================================
-- PumpAtlas AI - optional partitioning for audit_logs
--
-- audit_logs is the highest-volume table in the platform and is always read in time
-- order. Below a few million rows the plain table is fine. Past that, convert it to a
-- monthly range-partitioned table.
--
-- Run this BEFORE the table accumulates data you cannot afford to move, or plan a
-- maintenance window: converting an existing table requires copying it.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Convert. The primary key must include the partition key, so it becomes
--    (id, occurred_at) rather than (id) alone.
-- ---------------------------------------------------------------------
BEGIN;

ALTER TABLE audit_logs RENAME TO audit_logs_unpartitioned;

CREATE TABLE audit_logs (
    LIKE audit_logs_unpartitioned INCLUDING DEFAULTS INCLUDING COMMENTS
) PARTITION BY RANGE (occurred_at);

ALTER TABLE audit_logs ADD PRIMARY KEY (id, occurred_at);

CREATE INDEX ix_audit_logs_tenant_time ON audit_logs (tenant_id, occurred_at);
CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX ix_audit_logs_actor ON audit_logs (user_id, occurred_at);
CREATE INDEX ix_audit_logs_action ON audit_logs (action, occurred_at);
CREATE INDEX ix_audit_logs_request_id ON audit_logs (request_id);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_logs_tenant_isolation ON audit_logs FOR ALL USING (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
) WITH CHECK (
    pumpatlas_is_platform_admin() OR tenant_id = pumpatlas_current_tenant()
);

COMMIT;

-- ---------------------------------------------------------------------
-- 2. Create partitions. Call this for the current month and a few ahead.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_ensure_audit_partition(target date)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    start_date date := date_trunc('month', target)::date;
    end_date   date := (date_trunc('month', target) + interval '1 month')::date;
    part_name  text := format('audit_logs_%s', to_char(start_date, 'YYYY_MM'));
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = part_name) THEN
        RETURN format('%s already exists', part_name);
    END IF;
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF audit_logs FOR VALUES FROM (%L) TO (%L)',
        part_name, start_date, end_date
    );
    RETURN format('created %s', part_name);
END
$$;

-- Current month plus the next three, so inserts never hit a missing partition.
SELECT pumpatlas_ensure_audit_partition((current_date + (n || ' month')::interval)::date)
  FROM generate_series(0, 3) AS n;

-- ---------------------------------------------------------------------
-- 3. Move the historical rows across, then drop the old table once verified.
-- ---------------------------------------------------------------------
-- INSERT INTO audit_logs SELECT * FROM audit_logs_unpartitioned;
-- SELECT count(*) FROM audit_logs_unpartitioned;   -- compare before dropping
-- DROP TABLE audit_logs_unpartitioned;

-- ---------------------------------------------------------------------
-- 4. Retention. Detach rather than delete: a detached partition can be archived
--    to object storage and dropped later, which a DELETE cannot.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pumpatlas_detach_audit_partitions_before(cutoff date)
RETURNS SETOF text LANGUAGE plpgsql AS $$
DECLARE
    part record;
BEGIN
    FOR part IN
        SELECT c.relname
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
          JOIN pg_class parent ON parent.oid = i.inhparent
         WHERE parent.relname = 'audit_logs'
           AND c.relname < format('audit_logs_%s', to_char(cutoff, 'YYYY_MM'))
    LOOP
        EXECUTE format('ALTER TABLE audit_logs DETACH PARTITION %I', part.relname);
        RETURN NEXT format('detached %s', part.relname);
    END LOOP;
END
$$;
