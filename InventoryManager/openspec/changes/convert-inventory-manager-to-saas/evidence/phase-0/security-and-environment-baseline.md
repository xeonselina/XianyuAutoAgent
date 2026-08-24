# Security and Environment Baseline

## Context and handling rules

- Captured: 2026-08-21 (Asia/Shanghai)
- Branch: `saas-main`
- Base commit: `53193b6724693132be13cd084101e9cd62142c63`
- Scope: repository, Git object history, local configuration shape, local logs,
  migration graph, and local test environment
- Production access: not performed
- External provider access: not performed

All line references in this document are relative to the base commit unless a
section explicitly says that it refers to an untracked local file. This document
contains only key names, file locations, counts, classifications, and required
actions. It intentionally contains no credential value, credential fingerprint,
host address, customer value, or reconstructible secret fragment.

Production snapshots and rotation receipts must be stored in an access-controlled
evidence location outside Git. Only their run identifiers, timestamps, checksums,
and pass/fail conclusions may be linked from this change.

Project sequencing is intentionally kept in `migration-checklist.md`. This
baseline records facts, risks, and follow-up work; an unfinished row here is not
a blanket prohibition on unrelated safe implementation.

## Executive status

| Task | Local status | Remaining work |
| --- | --- | --- |
| 0.2 schema, data, grants, and configuration baseline | Alembic graph/ORM/config sources inventoried; a separate redacted probe verified the configured private DB schema shape, matching Alembic head, zero relationship/orphan findings, and broad runtime grants | **Incomplete**: target production identity and the restricted schema dump, exact count/amount/distribution results, complete accounts/grants, artifact checksum, and restricted evidence URI are still required |
| 0.10 credential/exposure disposition | Multiple current and historical exposure paths confirmed; D61 temporarily accepts exactly the existing legacy DB/SF/Kuaimai classes for at most 30 days per explicit review and never past first rehearsal | **Incomplete**: the current-state inventory, stop on new/reintroduced use, unsafe-image promotion prohibition, and later-task mapping are unfinished; final app-key retirement/no-authority proof belongs to tasks 4.3, 4.9-4.10, 8.10, 12.10, and 13.11 |
| 0.11 external prerequisites | Repository capability and test coverage inventoried | **Incomplete**: the implementation-independent readiness package for Tencent Cloud, SF, monitoring, NAS, and offline key custody has not been collected; active-smoke evidence is intentionally deferred until the capabilities exist |

None of tasks 0.2, 0.10, or 0.11 may be checked on the basis of this local
inventory alone.

## Current repository containment status and remaining risks

### Review scope

- Reviewed: 2026-08-21 21:27 CST
- HEAD: `53193b6724693132be13cd084101e9cd62142c63`
- State: shared, uncommitted working tree after repository-side containment edits
- Method: exact comparison against the ignored active `.env`, assignment-shape
  inspection, Git object scan, log scan, file-mode inspection, and static review
  of Compose, Docker, backup, provider logging, and Flask blueprint registration

The original findings below remain the incident baseline at the base commit. This
section distinguishes mitigations now present in the working tree from actions
that still require external state changes, destructive cleanup, deployment, or
production evidence.

### Completed in the current working tree

The following repository-side containment is verified locally:

1. **Active-to-tracked exact matches are zero.** A scanner loaded sensitive
   values from the ignored active `.env`, compared them with every file returned
   by `git ls-files`, and emitted only key names and locations. The current
   tracked working tree produced zero exact matches. The key selection included
   secrets, passwords, tokens, database URLs/DSNs, provider application IDs/keys,
   SF partner/checkword keys, Kuaimai printer identifiers, and access keys.
2. **Tracked templates are value-free for sensitive assignments.** The review
   found 33 sensitive assignments set to empty across `.env.example`,
   `.env.docker`, and `env.production`: 19, 5, and 9 assignments respectively.
   Production Compose requires database/root credentials, `DATABASE_URL`, and
   `SECRET_KEY` through environment references instead of literal defaults.
3. **Database credential fallbacks are narrowed.** Current production and Docker
   database configuration reads environment values without a credential-bearing
   URI fallback. Development/test-only constants remain isolated to their named
   configuration classes. This item does not claim application-key retirement:
   the current worktree also loads `API_KEY` from the environment. That accepting
   path makes this worktree unsafe to promote and must be stopped from new use
   and recorded in Phase 0; removal and no-authority proof remain later tasks.
4. **The Docker build context excludes known sensitive artifacts.** Current
   `.dockerignore:19-21,35-49` excludes `.env`, `.env.*`, `env.production`, logs,
   `PROJECT_EXPLORATION.md`, `scripts/exported_data.sql`, `simple_backup.sh`,
   backup/dump extensions, and private-key file extensions. `Dockerfile:104`
   still uses `COPY . .`, so retention and automated checking of these exclusion
   rules remain mandatory.
5. **Backup passwords are absent from command arguments.** `simple_backup.sh:7`
   sets `umask 077`; `simple_backup.sh:9` requires the password from an external
   environment source; `simple_backup.sh:17-33` writes it to a temporary MySQL
   defaults file, removes that file through an exit trap, and invokes `mysqldump`
   with `--defaults-extra-file`. It unsets the password variable afterward. No
   `MYSQL_PWD`, `-p<value>`, or `--password` invocation remains in the reviewed
   backup path.
6. **Direct provider credential logging is removed.** Kuaimai initialization now
   logs only whether a default printer is configured, not its identifier or
   application credentials. Xianyu signing/request logs use parameter-field or
   endpoint-path summaries rather than signed URLs, complete request bodies, or
   secrets. SF request/response logs use service, request, HTTP-status, and result-
   code summaries rather than the request URL, complete response body, or
   authentication material.
7. **Provider test routes are disabled in production by registration policy.**
   `app/__init__.py:73-77` registers `sf_test_api` only while testing, or while
   debug mode and the explicit development opt-in are both enabled. Production
   and Docker configuration do not register those routes by default. A regression
   test constructs a production-like configuration with the opt-in set and proves
   that no `/api/sf-test` route is registered.
8. **Compose database/cache ports are loopback-bound.** Current
   `docker-compose.yml:17,36` binds MySQL and Redis to `127.0.0.1`; current
   `docker-compose.test.yml:10` binds test MySQL to `127.0.0.1`. Health checks and
   the reviewed deployment wait path no longer place a password in the process
   argument list.
9. **Local sensitive-file modes are narrowed.** The ignored active `.env`, three
   current local log files, and `scripts/exported_data.sql` are mode `0600`.
   `start.sh:36` enforces mode `0600` on `.env`, and the backup `umask` protects
   newly created temporary configuration and dump artifacts.
10. **Future accidental tracking is reduced.** Current `.gitignore` covers
    `.env`, `.env.docker`, `env.production`, logs, and
    `scripts/exported_data.sql`. Existing tracked files remain tracked until an
    explicit index/history action is taken; ignore rules alone do not remove
    them.

No shell xtrace enablement was found in the reviewed shell scripts. No current
tracked private-key marker was found. Credential-bearing URIs still present in
legacy examples, tests, and helper scripts were classified as placeholder or
weak test literals and none exactly matched an active `.env` value; these remain
a hardening item and are not production secret evidence.

### Remaining risks and deferred release work

The following are not completed by the repository-side edits:

1. **The current worktree can reactivate the retired API-key path.**
   `config.py` loads `API_KEY`, `app/__init__.py` unconditionally registers
   `/external-api`, and its verifier accepts a matching `X-API-Key`. Supplying
   the exposed legacy value therefore restores authority instead of freezing new
   use. This worktree must not be promoted as a containment image; later Core
   implementation must remove the config, route, verifier, examples, and restore
   path and prove the old header is always unauthorized.
2. **D61 is approved but not yet supported by complete compensating evidence.**
   The project owner knowingly accepts the existing legacy database, default-
   tenant SF, and Kuaimai authority only through the current maximum-30-day
   review window and never past first rehearsal. Independent DB negative probes,
   complete grants, SF/Kuaimai restriction and anomaly/cost/quota receipts,
   external artifact scans, non-reuse proof and scheduled final rotation remain
   missing; any trigger or missed review immediately ends the exception. All
   other still-authoritative provider/database credentials still require normal
   rotation/revocation. The approved Core disposition for legacy
   `API_KEY`/`SECRET_KEY` is instead irreversible retirement: stop new use,
   remove every verifier/configuration/recovery path, replace Gantt signing with
   its purpose-separated platform-root-derived domain, and prove old values and
   artifacts have no authority during later release validation before any SaaS
   production traffic. Phase 0 must map those outcomes to later tasks rather
   than pretending that the not-yet-implemented Core already proves them.
3. **Active values remain in Git history and the current base commit.** The full-
   history exact-match scan still finds active key classes in historical/current
   blobs for `PROJECT_EXPLORATION.md`, `env.local`, `env.production`, `Makefile`,
   SF service source, and previously tracked access/application logs. The SF
   service source has six matching historical blob versions; the other reported
   path/key classes have one or two matching blob versions. No value or
   fingerprint was emitted. Current working-tree sanitization does not make old
   commits, remotes, forks, clones, release archives, or caches safe.
4. **Existing local logs still contain active values.** Restricting permissions
   to `0600` contains access but does not sanitize content. Exact matching still
   reports 35 occurrences: 17 in `logs/access.log`, 16 in
   `logs/inventory_service.log`, and 2 in `logs/inventory_service.log.1`. Affected
   key classes are Kuaimai application ID/secret/printer identifier, SF partner
   identifier, and Xianyu application key. Secure retention, quarantine, or
   destruction requires an approved incident decision.
5. **The production-data SQL artifact remains tracked.** Although
   `scripts/exported_data.sql` is mode `0600`, ignored for future additions, and
   excluded from new Docker contexts, it remains in the Git index and history.
   Its customer/fulfilment data must be moved to approved restricted storage,
   verified there, removed from the tracked tree, and included in the history and
   remote-cache exposure assessment.
6. **Existing images and distribution caches are unverified.** Build-context
   exclusions protect only future builds from the current tree. Existing local
   images, registry tags/layers, CI caches, release bundles, NAS copies, and
   deployment hosts still require inventory, scanning, clean replacement
   digests, and approved quarantine/deletion.
7. **Production network exposure is unverified.** Loopback Compose bindings do
   not prove the deployed CVM state. Tencent Cloud security groups, host firewall,
   Docker publish state, MySQL/Redis bind settings, and independent external
   probes must demonstrate that public database/cache connections fail. Public
   MySQL 3306 verification remains specifically outstanding.
8. **The containment edits are not yet a deployed control.** They exist only in
   the shared uncommitted working tree at the reviewed HEAD. Review, tests,
   durable version control, clean image rebuild, deployment, and runtime
   verification are still required before the production exposure changes.

### Remaining non-P0 hardening and evidence

- Legacy documentation, Windows/bootstrap helpers, tests, and data utilities
  still contain credential-shaped placeholder or weak literal database URIs.
  They do not exactly match active values, but they must be made unmistakably
  non-production or removed before final release.
- Development/test SF diagnostic logging and responses now use field names,
  configuration booleans, and opaque rental IDs rather than complete order,
  sender, customer, or tracking payloads.
- SF SDK error paths still log exception details and stack traces. They no longer
  log direct authentication inputs or complete provider responses, but structured
  exception-path redaction tests must still prove that exception strings cannot
  reintroduce signed URLs, request bodies, customer data, or credentials. Current
  tests cover successful-path SF/Kuaimai log redaction and fail-closed runtime
  configuration.
- Production schema/data/grant evidence from task 0.2 and the Phase 0 external-
  readiness evidence from task 0.11 remain outstanding as specified below. The
  active-smoke evidence for implemented endpoints, NAS, monitoring, and root-key
  custody remains later stage 11, task 12.13, and task 13.1 work.
- `configured-database-readonly-probe.md` supplements this original local-only
  snapshot. It records no secret/data values and does not independently prove
  that the configured private endpoint is production.

### Current sequencing decision

The current repository-side stopgap materially reduces new leakage and unsafe
local exposure, and D61 supplies a bounded decision for three legacy classes.
Task 0.10 is still unfinished because the current-state exposure inventory,
stop on new/reintroduced use, explicit no-promotion record for the unsafe
worktree/image, and later-task mapping for every unresolved item are not yet
complete. Rotation, application-key no-authority proof, session invalidation,
history/log/data cleanup, clean replacement images, deployment, and independent
network verification remain real later work; their absence is not rewritten as
safety. Tasks 0.2 and 0.11 also remain unfinished. Safe implementation may
continue, but this worktree/image must not be promoted and live external actions
still require their own controlled run.

## 0.2 Schema, Alembic, data, grants, and configuration baseline

### Migration and schema sources

Local facts:

- `migrations/versions/` contains 28 revision files and 28 matching
  `revision`/`down_revision` declarations.
- The graph has one current head: `20260807_damage_notes`.
- Historical branch points at `cb739080dde2` and `fdaa742857fe` are merged into
  the single head.
- Flask SQLAlchemy metadata registers 11 current tables.
- `init.sql:8-52` creates only three legacy tables and is not a representation of
  the current application schema.
- The canonical root revision
  `migrations/versions/bff12792e76a_initial_migration.py:21-33` creates
  `rental_accessories` and alters/references pre-existing `devices` and `rentals`;
  it is therefore a legacy bootstrap overlay rather than a self-contained empty-
  schema bootstrap. Task 0.2 records that fact. Empty Core schema reconstruction
  and ORM/head drift validation belong to later implementation tasks 1.9 and 5.8.
- `init.sql:70` grants the legacy application account all privileges on its
  database from a wildcard host. This is incompatible with the SaaS least-
  privilege account model.
- `app/models/rental_accessory.py:1-17` declares a deprecated model that is not
  imported by `app/models/__init__.py:5-14`; the migration chain removes that
  legacy table. Snapshot tooling must use the actual database plus the Alembic
  graph, not every model file found on disk.
- `migrations_backup/` contains three scripts outside the canonical Alembic
  version graph. They must be retained as historical material but must not be
  treated as deployable heads.

Current ORM metadata table set:

1. `audit_logs`
2. `device_models`
3. `devices`
4. `inspection_check_item`
5. `inspection_record`
6. `rental_relay_bindings`
7. `rental_relay_cases`
8. `rental_statistics`
9. `rentals`
10. `xianyu_order_alerts`
11. `xianyu_order_sync_state`

The original repository-only pass classified the configured application database
target without printing or connecting to it. The later bounded probe recorded in
`configured-database-readonly-probe.md` connected read-only to that private target
without independently proving it is production. The MySQL service observed on the
workstation listens on loopback only and contains no applicable InventoryManager
business schema, so it is not production evidence.

### Required production snapshot package

The production snapshot must be collected with a dedicated read-only login path.
No password, DSN, host, or login-path configuration file may be committed. The
package must include:

1. Base Git commit and deployed image digest.
2. Server version, relevant SQL modes, timezone, isolation level, character set,
   collation, and lower-case-table setting.
3. `alembic_version` contents and a schema-only dump including tables, indexes,
   foreign keys, triggers, routines, and events.
4. Exact row counts for every business table, not only `information_schema`
   estimates.
5. Critical amount totals and state distributions, including
   `rentals.order_amount`, `rental_statistics.total_rent/total_value`,
   `device_models.device_value`, and `xianyu_order_alerts.pay_amount` in their
   stored units.
6. Relationship and orphan checks listed below.
7. Database account inventory and `SHOW GRANTS` output collected by a DBA.
8. Provider configuration source classification by key name only.
9. Capture timestamp, collector identity, server identifier stored outside Git,
   artifact checksum, and restricted evidence URI.

Example shell shape; placeholders must be resolved only in the operator's secure
session:

```bash
export SAAS_SNAPSHOT_DB='<database-name-from-secure-inventory>'

mysqldump \
  --login-path=saas_baseline_readonly \
  --single-transaction \
  --no-data \
  --routines \
  --triggers \
  --events \
  "$SAAS_SNAPSHOT_DB" \
  > '<restricted-evidence-path>/schema.sql'

shasum -a 256 '<restricted-evidence-path>/schema.sql'
```

The export destination must not be inside the repository or Docker build context.

Task 0.2 is complete when these facts are captured reproducibly and every nonzero
or unsafe result has an owner and downstream disposition. It does not require the
broad runtime account to be replaced, MariaDB-to-MySQL 8 compatibility to be
proved, `utf8mb4` conversion or legacy-row correction to be executed, or external
network containment probes to pass. Those actions remain ordinary later work in
tasks 1.5, 0.11, 12.4, 12.6, 12.7, 12.9, 12.16, and 13.1 as applicable.

### Production read-only SQL checklist

Environment and migration identity:

```sql
SELECT VERSION();
SELECT @@transaction_isolation, @@sql_mode, @@time_zone, @@system_time_zone;
SELECT @@character_set_server, @@collation_server, @@lower_case_table_names;
SELECT version_num FROM alembic_version;
```

Exact table counts:

```sql
SELECT 'audit_logs' AS table_name, COUNT(*) AS row_count FROM audit_logs
UNION ALL SELECT 'device_models', COUNT(*) FROM device_models
UNION ALL SELECT 'devices', COUNT(*) FROM devices
UNION ALL SELECT 'inspection_check_item', COUNT(*) FROM inspection_check_item
UNION ALL SELECT 'inspection_record', COUNT(*) FROM inspection_record
UNION ALL SELECT 'rental_relay_bindings', COUNT(*) FROM rental_relay_bindings
UNION ALL SELECT 'rental_relay_cases', COUNT(*) FROM rental_relay_cases
UNION ALL SELECT 'rental_statistics', COUNT(*) FROM rental_statistics
UNION ALL SELECT 'rentals', COUNT(*) FROM rentals
UNION ALL SELECT 'xianyu_order_alerts', COUNT(*) FROM xianyu_order_alerts
UNION ALL SELECT 'xianyu_order_sync_state', COUNT(*) FROM xianyu_order_sync_state;
```

Amounts and state distributions:

```sql
SELECT
  COUNT(*) AS rental_count,
  COUNT(order_amount) AS amount_count,
  COALESCE(SUM(order_amount), 0) AS amount_total,
  MIN(order_amount) AS amount_min,
  MAX(order_amount) AS amount_max
FROM rentals;

SELECT
  COUNT(*) AS statistics_count,
  COALESCE(SUM(total_rent), 0) AS total_rent_sum,
  COALESCE(SUM(total_value), 0) AS total_value_sum
FROM rental_statistics;

SELECT
  COUNT(*) AS device_model_count,
  COUNT(device_value) AS device_value_count,
  COALESCE(SUM(device_value), 0) AS device_value_sum,
  MIN(device_value) AS device_value_min,
  MAX(device_value) AS device_value_max
FROM device_models;

SELECT
  COUNT(*) AS xianyu_alert_count,
  COUNT(pay_amount) AS pay_amount_count,
  COALESCE(SUM(pay_amount), 0) AS pay_amount_sum,
  MIN(pay_amount) AS pay_amount_min,
  MAX(pay_amount) AS pay_amount_max
FROM xianyu_order_alerts;

SELECT status, COUNT(*) AS row_count
FROM rentals
GROUP BY status
ORDER BY status;

SELECT express_type_id, COUNT(*) AS row_count
FROM rentals
GROUP BY express_type_id
ORDER BY express_type_id;

SELECT COUNT(*) AS invalid_express_type_count
FROM rentals
WHERE express_type_id IS NULL OR express_type_id NOT IN (1, 2, 263);

SELECT
  SUM(parent_rental_id IS NULL) AS primary_rentals,
  SUM(parent_rental_id IS NOT NULL) AS accessory_rentals
FROM rentals;
```

Uniqueness and relationship checks:

```sql
SELECT xianyu_order_no, COUNT(*) AS duplicate_count
FROM rentals
WHERE xianyu_order_no IS NOT NULL AND xianyu_order_no <> ''
GROUP BY xianyu_order_no
HAVING COUNT(*) > 1;

SELECT COUNT(*) AS orphan_device_model_count
FROM devices d
LEFT JOIN device_models m ON m.id = d.model_id
WHERE d.model_id IS NOT NULL AND m.id IS NULL;

SELECT COUNT(*) AS orphan_parent_model_count
FROM device_models child
LEFT JOIN device_models parent ON parent.id = child.parent_model_id
WHERE child.parent_model_id IS NOT NULL AND parent.id IS NULL;

SELECT COUNT(*) AS orphan_rental_device_count
FROM rentals r
LEFT JOIN devices d ON d.id = r.device_id
WHERE d.id IS NULL;

SELECT COUNT(*) AS orphan_parent_rental_count
FROM rentals child
LEFT JOIN rentals parent ON parent.id = child.parent_rental_id
WHERE child.parent_rental_id IS NOT NULL AND parent.id IS NULL;

SELECT COUNT(*) AS self_parent_rental_count
FROM rentals
WHERE parent_rental_id = id;

SELECT COUNT(*) AS orphan_audit_device_count
FROM audit_logs a
LEFT JOIN devices d ON d.id = a.device_id
WHERE a.device_id IS NOT NULL AND d.id IS NULL;

SELECT COUNT(*) AS orphan_audit_rental_count
FROM audit_logs a
LEFT JOIN rentals r ON r.id = a.rental_id
WHERE a.rental_id IS NOT NULL AND r.id IS NULL;

SELECT COUNT(*) AS orphan_inspection_rental_count
FROM inspection_record i
LEFT JOIN rentals r ON r.id = i.rental_id
WHERE r.id IS NULL;

SELECT COUNT(*) AS orphan_inspection_device_count
FROM inspection_record i
LEFT JOIN devices d ON d.id = i.device_id
WHERE d.id IS NULL;

SELECT COUNT(*) AS orphan_inspection_item_count
FROM inspection_check_item item
LEFT JOIN inspection_record record ON record.id = item.inspection_record_id
WHERE record.id IS NULL;

SELECT COUNT(*) AS invalid_relay_binding_count
FROM rental_relay_bindings binding
LEFT JOIN rentals predecessor ON predecessor.id = binding.predecessor_rental_id
LEFT JOIN rentals successor ON successor.id = binding.successor_rental_id
WHERE predecessor.id IS NULL
   OR successor.id IS NULL
   OR binding.predecessor_rental_id = binding.successor_rental_id;

SELECT COUNT(*) AS invalid_relay_case_count
FROM rental_relay_cases relay_case
LEFT JOIN rentals predecessor ON predecessor.id = relay_case.predecessor_rental_id
LEFT JOIN rentals successor ON successor.id = relay_case.successor_rental_id
WHERE predecessor.id IS NULL
   OR successor.id IS NULL
   OR relay_case.predecessor_rental_id = relay_case.successor_rental_id;
```

If a query fails because a table or column differs from the expected shape, that
failure is evidence of schema drift and must be resolved before migration. Query
results must remain outside Git.

### Account and grant checklist

The DBA must capture, without password hashes or authentication strings:

```sql
SELECT USER(), CURRENT_USER();
SHOW GRANTS FOR CURRENT_USER;
SHOW VARIABLES LIKE 'bind_address';
SHOW VARIABLES LIKE 'port';
SHOW VARIABLES LIKE 'skip_networking';
SHOW VARIABLES LIKE 'require_secure_transport';
```

The DBA-owned account inventory must classify each account by purpose, host
scope, authentication plugin, lock state, password-expiry state, global grants,
schema grants, grant option, and last-use evidence. The stored report must omit
credential hashes and authentication material.

For task 0.2, broad, global, wildcard-host, or otherwise unsafe grants are captured
findings rather than a requirement to complete remediation immediately. The report
must give each finding an owner and downstream disposition; actual least-privilege
replacement remains tasks 1.5 and 12.9 work.

Required classifications are:

- current application runtime account;
- migration/provisioning account;
- backup account;
- monitoring account;
- human DBA accounts;
- obsolete or unknown accounts;
- wildcard-host accounts;
- accounts with global or grant-option privileges.

### Configuration source map

| Surface | Repository evidence | Baseline conclusion |
| --- | --- | --- |
| dotenv loading | `app/__init__.py:12-16` | The application loads the repository-local `.env` outside its test guard |
| database selection | `config.py:9-22`, `config.py:110-117` | Environment selection has embedded fallback paths and does not implement control/tenant routing |
| application secret | `config.py:29` | Environment lookup includes a fallback and must become fail-closed |
| SF | `app/services/shipping/sf_express_service.py:24-35`, `app/services/shipping/sf_tracking_service.py:26-28` | Process-global provider configuration |
| Kuaimai | `app/services/printing/kuaimai_service.py:31-37` | Process-global provider configuration and direct credential logging |
| Xianyu | `app/services/xianyu_order_service.py:27-44` | Process-global provider configuration |
| legacy OCR | `ocr_functions.py:47-51` | Legacy global provider configuration; OCR is outside SaaS Core |
| Docker environment | `docker-compose.yml:57-68` | Partial, legacy provider mapping with credential-bearing defaults/references |
| example template | `.env.example:7-124` | Legacy keys only; no SaaS control DB, root-key, Tencent SMS, or custody model |
| production template | `env.production:8-127` | Contains literal credential-shaped entries and declarative flags without supporting runtime capabilities |

Known template/runtime drift:

- `.env.example:29` uses `SF_CHECKPHONENO`, while
  `app/services/shipping/sf_express_service.py:31` uses `SF_SENDER_PHONE`.
- `.env.example:21-22`, `.env.docker:23-24`, `env.production:18-19`, and
  `ocr_functions.py:47-51` use the `ALIYUN_` key family, while
  `docker-compose.yml:64-66` uses the `ALIBABA_CLOUD_` family.
- The production template does not define the current SF, Kuaimai, or Xianyu key
  set used by the runtime services.
- No runtime key set exists for Tencent SMS, the SaaS control database, the
  platform root-key file, NAS pull receipts, or external probe channels.

## 0.10 Credential, history, image, and port findings

### Confirmed current-to-tracked matches

An in-memory exact-value comparison was performed between sensitive keys in the
ignored local `.env` and tracked repository content. The scanner emitted only key
names and locations. It confirmed these matches:

| Key name | Tracked location |
| --- | --- |
| `SECRET_KEY` | `PROJECT_EXPLORATION.md:901` |
| `API_KEY` | `PROJECT_EXPLORATION.md:902` |
| `DATABASE_URL` | `env.production:17` |
| `SF_PARTNER_ID` | `app/services/shipping/sf_express_service.py:324` |
| `KUAIMAI_APP_ID` | `PROJECT_EXPLORATION.md:893` |
| `KUAIMAI_APP_SECRET` | `PROJECT_EXPLORATION.md:894` |
| `KUAIMAI_PRINTER_SN` | `PROJECT_EXPLORATION.md:895` |

These values must be treated as exposed. Deleting a current line is not a
substitute for revocation or rotation while an accepting path remains. For the
two legacy application keys that Core contract-deletes, verified removal of all
accepting and recovery paths is the approved retirement control; merely blanking
their environment assignments is not.

### Confirmed Git-history exposure classes

A `git cat-file --batch` scan compared the same active local values with all Git
blob objects without printing values or fingerprints. It confirmed:

- historical `env.local` blobs contain active `SECRET_KEY` and `API_KEY` values;
- historical `Makefile` blobs contain an active `SF_CHECKWORD` value;
- multiple historical SF service source blobs contain an active
  `SF_PARTNER_ID` value;
- previously tracked `logs/access.log` and `logs/inventory_service.log` blobs
  contain an active `SF_PARTNER_ID` value;
- current tracked `env.production` and `PROJECT_EXPLORATION.md` blobs contain the
  current matches listed above.

The Git exposure window begins no later than the first introduction of these
historical files. Rotation of any credential that remains authoritative must
precede an optional history rewrite; contract-deleted `API_KEY`/`SECRET_KEY`
instead require proof that no verifier, session, signed artifact, restore path,
or compatibility route accepts them. Remote forks, clones, CI caches, release
archives, and provider audit logs must be included in the exposure assessment.

### Local log exposure

The ignored local log set contains three files and 35 exact-match occurrences of
active provider identifiers or credentials:

| Local file | Evidence |
| --- | --- |
| `logs/access.log` | Kuaimai key matches at lines 64226-64229; SF identifier matches at 11 lines; Xianyu key matches at 2 lines |
| `logs/inventory_service.log` | Kuaimai key matches at lines 5805-5808; SF identifier matches at 9 lines; Xianyu key matches at 3 lines |
| `logs/inventory_service.log.1` | SF identifier matches at 2 lines |

Primary direct sink:

- `app/services/printing/kuaimai_service.py:35-37` logs `KUAIMAI_APP_ID`,
  `KUAIMAI_APP_SECRET`, and `KUAIMAI_PRINTER_SN` values.

Additional review-required sinks include:

- `app/routes/sf_test_api.py:149` logs complete mock/order data;
- `app/services/shipping/sf_express_service.py:134,192,385` logs order or
  provider URL context;
- `app/utils/sf/sf_sdk_wrapper.py:78-81,174,181,313-316` logs provider request
  or response context;
- `app/services/xianyu_order_service.py:131-158,171,188,392` logs request paths
  or request data.

Current file modes are also unsafe for credential-bearing material:

- `.env`, `.env.docker`, and `env.production`: `0644`;
- all three local logs: `0644`;
- `scripts/exported_data.sql`: `0644`.

### Tracked production-data artifact

`scripts/exported_data.sql` is tracked and currently has:

- 103,170 bytes;
- 455 lines;
- 243 `INSERT` statements;
- rows for device models, devices, rentals, and rental statistics;
- rental columns covering customer name, customer phone, destination, and
  outbound/inbound tracking numbers.

No row value was printed during this audit. The artifact must be handled as a
production-data exposure unless an authorized data owner proves that every row
is synthetic. It must not remain in Git or an image build context.

### Image-build exposure

- `Dockerfile:104` uses `COPY . .`.
- `.dockerignore:19` excludes `.env` but does not exclude `.env.docker` or
  `env.production`.
- `.dockerignore` does not exclude `scripts/exported_data.sql`,
  `PROJECT_EXPLORATION.md`, or `simple_backup.sh`.
- Therefore the listed tracked configuration, data, and backup artifacts enter
  the build context and may exist in current or historical image layers.

Existing local/registry images were not inspected because no approved image
digest or registry evidence was provided. Image scanning and cache invalidation
remain required.

### Credential-bearing command paths

| Location | Risk class |
| --- | --- |
| `docker-compose.yml:10,13,23-25` | weak credential defaults/references and database health-check command arguments |
| `docker-compose.test.yml:5,8,20` | fixed test credentials and health-check command argument |
| `deploy.sh:127` | database password in a process argument |
| `simple_backup.sh:4,12` | hard-coded backup password and root password in a process argument |
| `config.py:17,22,29,92,113-114` | embedded database/application fallback credentials or DSNs |
| `env.production:10-19` | tracked literal credential-shaped production entries |

Provider/database secrets must be injected through a non-Git secret source and
must not appear in process arguments, health-check definitions, Docker image
metadata, shell tracing, exception text, or normal logs.

### Database and cache port exposure

- `docker-compose.yml:17` publishes MySQL as `3306:3306`. Without an explicit
  host address, Docker publishes on all host interfaces.
- `docker-compose.test.yml:10` similarly publishes test MySQL on all host
  interfaces at host port 3307.
- `docker-compose.yml:36` publishes unauthenticated Redis as `6379:6379` on all
  host interfaces.
- The workstation's separately installed MySQL was observed listening only on
  loopback. This does not attest to production.
- Production security-group, host-firewall, Docker-publish, MySQL-bind, and
  independent external-probe evidence were not available.

Production acceptance requires an independent host outside the CVM/network to
demonstrate that MySQL and Redis service ports are unreachable. A successful
connection is a P0 failure. The application and public health endpoints must be
probed separately on their intended public ports.

### Required containment and remediation order

This ordered list deliberately spans more than Phase 0. Phase 0 records the
current facts, stops adding/restoring/migrating/reusing exposed authorities,
denies promotion of the current unsafe worktree/image and derived artifacts, and
maps every unresolved item to its later task. It does not authorize or claim
completion of the stateful/destructive work in steps 3-11. Those steps remain
required where applicable later in implementation and release verification.

1. Stop deployment, image promotion, log export, and distribution of the
   affected repository or artifacts while preserving an access-controlled
   incident record.
2. Inventory affected provider accounts, database accounts, application secrets,
   images, registries, CI caches, remotes, forks, clones, and logs.
3. Revoke or rotate exposed provider credentials and record provider receipt
   identifiers. D61 alone may defer the existing default-tenant SF/Kuaimai values
   while its maximum-30-day window and all compensating controls remain valid;
   it never covers Xianyu, other providers, future tenants/revisions, or the first
   rehearsal and does not defer cleanup.
4. Rotate the exposed database account/password and replace root/broad-grant
   runtime and backup access with purpose-specific least-privilege accounts. D61
   may temporarily retain only the legacy source account behind verified network
   controls; it cannot be registered as a Core identity and must be replaced/
   revoked before first rehearsal.
5. Stop new legacy `API_KEY` and `SECRET_KEY` use, remove their configuration,
   verifier and restore paths, replace Gantt proof signing with the approved
   purpose-separated platform-root-derived domain, and test that old headers,
   Cookies and signed artifacts have no authority. If either value remains
   accepted in any pre-Core deployment, rotate it and invalidate dependent
   artifacts before that deployment may continue serving.
6. Remove current credential/data literals, eliminate credential logging, and
   securely dispose of affected local/deployed logs and data dumps according to
   an approved retention decision.
7. Narrow the Docker build context, use runtime secret injection, remove secrets
   from health checks/process arguments, and rebuild from a clean context without
   cache.
8. Quarantine/delete affected image tags and CI/registry caches only after clean
   replacement digests and rollback evidence exist.
9. After rotation, evaluate and execute an approved Git-history rewrite; then
   invalidate remote caches and require collaborators to replace old clones.
10. Close database/cache ports at security-group, host-firewall, Docker-publish,
    and service-bind layers; verify from an independent external origin.
11. Repeat current-tree, full-history, log, artifact, and image scans with
    redaction enabled; store zero-finding reports and rotation receipts outside
    Git.

History rewriting, image deletion, log destruction, and credential rotation are
destructive or externally stateful actions. They require exact target inventory,
operator authorization, rollback/continuity planning, and recorded receipts.

### Safe repeatable local scans

Key-name references only:

```bash
git grep -nI -o -E \
  '(DATABASE_URL(_HOST)?|SQLALCHEMY_DATABASE_URI|MYSQL_(ROOT_)?PASSWORD|DB_PASSWORD|SECRET_KEY|API_KEY|CHECKWORD|PARTNER_ID|ACCESS_KEY(_ID|_SECRET)?|APP_SECRET|TOKEN|MAIL_PASSWORD)' \
  -- . ':!openspec/**' | sort -u
```

Credential-bearing URI line locations only:

```bash
git grep -nI -E \
  '(mysql|postgres(ql)?|redis|mongodb)(\+[A-Za-z0-9_]+)?://[^[:space:]]*:[^/@[:space:]]+@' \
  -- . ':!openspec/**' \
  | awk -F: '{print $1 ":" $2}' \
  | sort -u
```

Private-key marker locations only:

```bash
git grep -nI -E \
  'BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY|BEGIN PGP PRIVATE KEY' \
  -- . ':!openspec/**' \
  | awk -F: '{print $1 ":" $2}' \
  | sort -u
```

Port/build-context review:

```bash
rg -n '3306:3306|3307:3306|6379:6379|COPY[[:space:]]+\.[[:space:]]+\.' \
  docker-compose.yml docker-compose.test.yml Dockerfile
nl -ba .dockerignore
lsof -nP -iTCP:3306 -sTCP:LISTEN
```

No dedicated secret scanner was installed at capture time. The remaining 0.10
inventory work should run a redacted scan against the working tree and Git
history, preserving findings by class/location without emitting values or useful
fingerprints. A Phase 0 result may be nonzero, but every finding must be stopped
from new use, covered by the current-image promotion deny, and mapped to later
remediation. Tasks 12.10 and 13.11 perform the final old-value/no-authority validation after
the replacement implementation exists.

## 0.11 Phase 0 external-readiness baseline

### Repository capability findings

| Prerequisite | Repository evidence | Status |
| --- | --- | --- |
| Tencent Cloud SMS qualification | No Tencent SMS runtime implementation, configuration set, or automated test was found | External and unverified |
| Real SF timing capability | SF request/tracking code exists; local tests cover mocks and parsing only | Real account capability unverified |
| CVM and external probe channel | `env.production:102-108` contains declarative flags; `app/routes/web.py:31-37` and `app/routes/external_api.py:470-477` return static health payloads | Alert delivery and dependency health unverified |
| NAS pull | `simple_backup.sh:1-17` performs a local root dump to a fixed directory; it is not a least-privilege NAS pull, receipt, retention, tombstone, or cloud-sync workflow | External pull capability unverified |
| Two offline root-key copies | No platform root-key loader or custody-verification facility exists yet | External custody prerequisite unverified |

Additional production risk at the base commit:

- `app/routes/sf_test_api.py:15,75,108` defines provider test routes.
- Base-commit `app/__init__.py:50,58` registered the blueprint without a
  production-disable or authorization gate.
- The current containment worktree addresses registration at
  `app/__init__.py:73-77`: the blueprint is available only while testing, or in
  debug mode with explicit development opt-in. The local production-like route-
  absence regression passes; deployed route-map verification is still required.
- These routes are not acceptable evidence for real SF capability and must not be
  publicly reachable in production.

Local provider-focused automated evidence:

- 36 tests passed across SF tracking/parser and Xianyu request/reconciliation/API
  suites.
- These tests use mocks or local parsing and make no claim about real provider
  entitlement, rate limits, account binding, delivery, printing, or alerting.
- No Kuaimai, Tencent SMS, NAS pull, or real monitoring-channel acceptance test
  was found.

### Phase 0 readiness package

Task 0.11 is an implementation-independent readiness review. For each external
dependency, record an opaque account/resource reference, current qualification
or entitlement state, required versus current permission classes, owner and
backup owner, provider/contact path, lead time, expiry/renewal risk, target
topology, known gaps, downstream implementation task, and active-smoke plan.
Unknown or pending fields remain visibly unfinished; no secret, phone, address,
waybill, host address, or useful fingerprint is stored in Git.

The minimum service-specific readiness fields are:

- **Tencent Cloud SMS:** enterprise qualification, domestic signature/template
  and carrier-filing state; intended CAM permission boundary; owner; approval/
  filing lead time and renewal risk; target action-bound OTP topology; and a
  later send/verify/negative/rate-limit/delivery-receipt smoke plan using an
  approved test number.
- **SF:** real account ownership and monthly-account/timing capability entitlement
  state; intended query/create/cancel/print service-code permissions; owner and
  provider escalation path; enablement lead time; target tenant/warehouse binding;
  and a later synthetic timing/waybill/query/print smoke plan. A Phase 0 console
  or read-only entitlement check is not a provider transaction receipt.
- **CVM and external monitoring:** cloud account/permission class, notification-
  recipient owner and backup, channel eligibility, target Agent/off-host serving/
  dead-man/dependency topology, planned health routes and no-store contract,
  provisioning lead time, and a later per-channel alert/acknowledgement/recovery
  smoke plan.
- **NAS pull and backup:** NAS owner and availability, proposed least-privilege
  account/forced-command boundary, target pull/completion/checksum/retention/
  cloud-sync/restore topology, capacity and provisioning lead time, RPO/RTO
  owner, and a later transfer/corruption/retention/restore smoke plan.
- **Platform root-key custody:** custodian and backup custodian roles, intended
  two failure domains and media controls, target non-Git load/copy/recovery
  topology, ceremony lead time, and a later correct-key/incorrect-key recovery
  plan.

Phase 0 does **not** require runtime capabilities that are scheduled for
implementation: `/health/external`, `/health/monitor`, a NAS pull job, completed
backup/restore flow, generated platform-root-key material, two offline copies, or
active SMS/SF/alert/recovery receipts. Their absence remains recorded above and
must not be reported as implemented.

### Later implementation and active-smoke work

After the corresponding implementation exists, stage 11 and tasks 12.13/13.1 perform
the real active-smoke work, including:

- action-bound SMS send/verify plus incorrect, expired, replayed, rate-limited,
  delivery, and alert-path results;
- controlled SF timing, account binding, waybill create/cancel/query/print using
  approved synthetic fixtures;
- independent serving/dependency probes and every approved alert channel's
  acknowledgement and recovery notification;
- NAS-initiated pull, completion marker, checksum, retention/cloud-sync receipt,
  corruption handling, and restore drill;
- two encrypted/offline root-key copies in different failure domains and a
  correct-key/incorrect-key recovery drill.

Every active operation uses approved test data, bounded side effects, an abort/
cleanup rule, and redacted results. This later evidence is required before
release but is not a Phase 0 completion condition.

## Phase 0 evidence targets

### Task 0.2 current target

- the deployed commit and image digest are fixed;
- a restricted schema-only dump and checksum exist;
- Alembic head and production `alembic_version` agree or documented drift is
  resolved;
- exact table counts, amount totals, state distributions, and every orphan query
  have timestamped results;
- all orphan/invalid counts are zero or have a documented migration disposition;
- the database account/grant report is complete and unknown/global/wildcard
  privileges have an owner and remediation decision;
- provider configuration sources are reduced to an authoritative key-name map;
- no production value or credential-bearing artifact is committed to Git.

### Task 0.10 current target

- the current tree, Git history/remotes, images/caches, logs, data artifacts,
  command/health-check paths, database/network posture, and provider/account
  surfaces have a timestamped redacted inventory by key/data class and location class;
  unknown surfaces remain explicit rather than being treated as clean;
- every accepting path and currently authoritative class has a disposition. The
  exact D61 legacy DB/SF/Kuaimai rows include owner, approval/expiry, triggers,
  accepted impact, non-reuse rule, and a rotation/revocation boundary no later
  than the first production-scale rehearsal;
- adding, restoring, copying, migrating, or reusing the exposed authorities is
  prohibited. Legacy `SECRET_KEY`/`API_KEY` cannot be introduced into any new Core
  identity, session, signer, compatibility path, image, or recovery input;
- the current worktree/image and every unscanned derivative are explicitly
  marked unsafe and denied promotion. This containment record does not claim a
  clean replacement image already exists;
- each unresolved rotation, revocation, least-privilege conversion, port probe,
  history/log/data/image cleanup, session invalidation, and application-key
  retirement/negative-test obligation is mapped to its downstream task and due
  boundary, without containing a secret, PII, or useful fingerprint.

Task 0.10 does not require Phase 0 to implement Core retirement paths or perform
destructive/external remediation. Tasks 4.3, 4.9-4.10, 8.10, 12.10, and 13.11 later remove
`SECRET_KEY`/`API_KEY` configuration, verifier, session, signer, compatibility,
and restore paths and prove old values/artifacts have no authority. All other
mapped remediation and D61 deadlines remain enforceable.

### Task 0.11 current target

- every SMS, SF, monitoring, NAS, and root-key dependency has the common readiness
  fields and service-specific fields listed above, including current pending/
  unavailable states rather than inferred success;
- required accounts/qualifications/entitlements and permission gaps are verified
  read-only where possible, with owner, backup owner, provider/contact route,
  lead time, expiry/renewal risk, and target topology recorded;
- every not-yet-implemented capability is mapped to its stage 1-11 task and tasks
  12.13/13.1 active-smoke work;
- each active-smoke plan identifies test data, permitted side effects, abort/
  cleanup boundary, expected result, and redaction rule.

Task 0.11 readiness never counts a mock as real entitlement and never counts a
plan as an active-smoke pass. Actual endpoints, NAS flow, root-key copies, real
provider actions, alert delivery, and recovery drills remain later stage 11 and
tasks 12.13 and 13.1 work after implementation.

## Current project sequencing

Local inventory and read-only readiness work may continue, but the current unsafe
worktree/image must not be promoted and no active provider/alert/backup/key smoke
may run without a controlled plan. The unfinished 0.10/0.11 evidence does not
stop unrelated safe implementation; final app-key retirement and real external
active smokes occur in their later tasks. D61 remains a bounded exception for
three legacy credential classes, not a waiver of missing controls or a claim of
non-exposure, and it expires at its signed deadline, on a trigger, or no later
than the first production-scale rehearsal. The remaining project order is the
short sequence in `migration-checklist.md`.
