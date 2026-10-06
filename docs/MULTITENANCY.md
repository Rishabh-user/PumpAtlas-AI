# Multi-tenancy and access control

## Isolation is enforced twice, on purpose

**1. In the database.** Every tenant-scoped table has row level security enabled and
forced. Policies compare `tenant_id` against `app.tenant_id`, a GUC set for the life of
each transaction:

```sql
CREATE POLICY vendors_tenant_read ON vendors FOR SELECT USING (
    pumpatlas_is_platform_admin()
    OR tenant_id = pumpatlas_current_tenant()
    OR tenant_id IS NULL           -- shared master data
);
```

**2. In the application.** Repository helpers filter on the resolved tenant as well.

Belt and braces is the right call here. A query that forgets its tenant predicate is the
classic multi-tenant data leak, and it is a mistake a busy engineer will eventually make.
With RLS forced, that mistake returns fewer rows instead of another client's pricing.

`app/core/db.py` sets both GUCs; the request dependency in `app/core/deps.py` calls it on
every request, and `tenant_session()` does the same for every Celery task.

> **Deployment requirement:** the application role must not own these tables and must not
> have `BYPASSRLS`, or the policies are skipped. `db/app_role.sql` creates a suitable
> role, and the Compose stack applies it on first start.
>
> This is the single easiest way to think you have tenant isolation and not have it. A
> PostgreSQL **superuser bypasses RLS entirely**, even with `FORCE ROW LEVEL SECURITY` -
> and the bootstrap role created by the Postgres image *is* a superuser. Connect the
> application as `pumpatlas_app`, never as `pumpatlas`.

### The GUC has to survive a commit

`set_config('app.tenant_id', ..., true)` is **transaction-local**. That is deliberate:
with a connection pool, a session-level setting would leak into whichever request picked
up the connection next. But it also means a `commit()` discards it, so a handler that
creates a row, commits, then reads it back - the ordinary create-then-return pattern -
would run its second query with no tenant at all and be refused by its own policies.

`app/core/db.py` therefore re-applies the setting on every new transaction of the session,
through SQLAlchemy's `after_begin` event. The setting stays transaction-scoped, and it
survives commits.

## Shared master data

`tenant_id IS NULL` marks vendor and pump records curated by Targeticon.

* **Read** - any tenant with `can_use_shared_master`.
* **Write** - platform administrators only. The write policy has no `IS NULL` branch, so
  a tenant physically cannot modify shared data.
* **Contribute** - a tenant with `can_contribute_shared_master` can have its records
  promoted into the shared set by a platform admin.

This is what lets a new client start with a usable vendor base instead of an empty
database, without exposing anyone's commercial terms.

## Strictly private tables

Comparisons, requirement profiles, saved searches, import batches, quality flags,
duplicate candidates, scorecards, record versions, audit logs and API keys have no
shared-master read-through. They are a client's working papers.

## Platform staff

`users.tenant_id IS NULL` together with `is_platform_admin = true` identifies Targeticon
staff. They may narrow themselves to one tenant by passing `X-Tenant-Id`, which:

* sets the RLS GUC to that tenant **and drops the platform-admin bypass for that
  request**, so they see exactly what the client sees - no more;
* leaves their RBAC permissions intact, so they can still act as an administrator within
  that tenant;
* is recorded in the audit log against that tenant, so support access is visible to the
  client.

Dropping the bypass matters. Keeping it on would short-circuit every policy to true, and a
support engineer who believed they were looking at one client would in fact be looking at
all of them. To work across tenants, omit the header.

A non-admin passing a mismatched `X-Tenant-Id` gets 403.

## The six roles

| Role | Reads | Writes | Approves |
| --- | --- | --- | --- |
| **Admin** | everything in the tenant | everything | everything |
| **Research analyst** | everything except audit | vendors, pumps, all specs, ingestion, AI review | AI review |
| **Procurement** | everything except audit | commercial and delivery specs, comparisons | commercial specs |
| **Engineering** | everything except audit and admin specs | technical, dimensional and operational specs, comparisons | technical specs, AI review |
| **Vendor manager** | everything except audit | vendors, operational and administrative specs | vendor qualification |
| **Client user** | technical, dimensional, delivery and operational data; search; comparisons | nothing | nothing |

Two separations are deliberate, and tested in `tests/test_api_surface.py`:

* **A client user cannot read `commercial_spec`.** A client-company viewer sees the
  engineering picture, not what the operator negotiated.
* **Engineering cannot write commercial specs, and procurement cannot write technical
  specs.** Neither discipline can quietly move the other's numbers to change a ranking.

The matrix lives in one place, `app/core/rbac.py`, and is copied onto the `roles` rows at
seed time so the UI can render permissions without duplicating the logic.

## API keys

Machine credentials are scoped with explicit `resource:action` pairs rather than roles.
Only a bcrypt hash is stored; the plaintext is shown once at creation. A key is bound to
one tenant and can never be a platform admin.

## Audit trail

`audit_logs` is append-only and records logins, failed logins, every mutation with its
diff, exports, permission changes, tenant changes, merges, and every applied or rejected
AI suggestion - with the request id, IP address and route. `record_versions` holds the
full row snapshot beside it, so "what did it look like then" and "who changed it" are both
answerable.

## Quotas

Per-tenant limits live on the `tenants` row: `max_users`, `max_ai_jobs_per_day`,
`max_storage_mb`, `data_retention_days`. Seat limits are enforced at user creation, and
`GET /tenants/{id}` reports live usage against each one.
