# Configured Database Read-Only Probe

## Attestation and safety boundary

- Captured at database UTC time: `2026-08-21 14:59:26`
- Branch/base commit: `saas-main` / `53193b6724693132be13cd084101e9cd62142c63`
- Working-tree state: shared and dirty; this record identifies the base commit but
  is not an immutable deployment attestation
- Connection source: the ignored local `.env`
- Target classification: a private-address MySQL-protocol endpoint on a
  non-default port
- Production identity: **not independently proven**; the configured target must
  not be called production until an operator ties it to the deployed commit,
  image digest, server inventory, and restricted evidence package

The probe printed and retained no DSN, host, port number, database name, account
name, password, customer value, row-level value, amount, provider credential, or
secret fingerprint. It used a read-only session and `START TRANSACTION READ ONLY`,
executed only `SELECT`/`SHOW` metadata and aggregate checks, then rolled back and
closed the connection. The first metadata attempt encountered the server's older
isolation-variable name and exited before any data query; the compatible retry
used `@@tx_isolation`. No database or repository write was performed by either
attempt.

## Redacted findings

| Area | Result |
| --- | --- |
| Connectivity | Private target resolved and accepted the configured connection |
| Read-only enforcement | Read-only transaction started successfully; the probe ended with rollback |
| Server family | MariaDB `10.11.6`, not the MySQL 8 target named by the background-job design |
| Isolation | `REPEATABLE-READ` |
| Server character set/collation | `utf8mb3` / `utf8mb3_general_ci` |
| Table-name behavior | `lower_case_table_names=0` |
| Schema inventory | 12 base tables: all 11 expected business tables plus `alembic_version` |
| Alembic identity | One database revision row; it matches the repository's single head |
| Schema fingerprint | Normalized 12-table DDL SHA-256: `02599a0a020cf38020aacacbf934505781c477f58c9a0a77833f7e6eb3b8c692` |
| Exact counts and totals | Exact counts for all 12 tables and two legacy critical-amount queries executed successfully in memory; values were not retained in Git, and the probe did not cover `device_models.device_value` or `xianyu_order_alerts.pay_amount` |
| Relationship checks | 12 relationship/orphan checks executed; all returned zero |
| Express-type distribution | NULL values and legacy value `6` both exist; no other value outside `1/2/263` was observed |
| Runtime account grants | The connected account has global `ALL` and `GRANT OPTION`; `FILE` was not present |
| Server network posture | Server listens on all interfaces, networking is enabled, transport security is not required, and this connection did not use TLS |

The schema fingerprint is normalized to omit volatile `AUTO_INCREMENT` counters.
It is suitable only for detecting later DDL drift; it is not a substitute for the
restricted schema dump, checksum, and restricted evidence URI required by task
0.2.

## Remaining task 0.2 capture and downstream follow-up

1. **Prove target identity.** An authorized operator must bind this endpoint—or
   the actual production endpoint if different—to the deployed commit, image
   digest, database inventory ID, capture identity, and restricted artifact URI.
2. **Persist the complete snapshot outside Git.** Store the schema-only dump,
   exact row counts, monetary aggregates (including `device_value` and Xianyu
   `pay_amount` in their stored units), distributions, orphan results, account
   inventory, grants, and provider configuration-source map in restricted
   evidence storage with a checksum and restricted URI. This probe deliberately
   did not persist those values.
3. **Capture the broad-account fact and map its remediation.** A DBA must provide
   the complete account/grant report and a dedicated read-only collector. For task
   0.2, global `ALL` plus `GRANT OPTION` is a baseline finding that needs an owner
   and downstream disposition; replacing the runtime account belongs to tasks 1.5
   and 12.9.
4. **Record source/target engine drift.** The source is MariaDB 10.11, while the
   approved worker design targets MySQL 8 row-lock/lease semantics. Task 0.2 only
   captures this fact and its mapping; tasks 12.7 and 12.16 prove DDL, data-type,
   collation, SQL-mode, locking, advisory-lock, and dump/restore compatibility.
5. **Record the character-set conversion requirement.** The source default is
   `utf8mb3`. Task 0.2 captures table/column collations and the disposition;
   controlled `utf8mb4` conversion and its truncation, uniqueness, and index
   checks belong to tasks 12.7 and 12.16.
6. **Capture the exact express-type distribution without inventing a mapping.**
   Task 0.2 must persist the counts for NULL, `1`, `2`, `263`, `6`, and any other
   value plus the migration disposition. The later correction/backfill and
   fail-closed provider behavior belong to tasks 12.4 and 12.6; `6` must never be
   silently reinterpreted as `263`.
7. **Map external network verification to later work.** A private address and
   non-default port do not prove isolation. Task 0.2 records the observed posture;
   security-group, host-firewall, Docker/service bind, trusted-source, and
   independent negative probes belong to tasks 0.11, 12.9, and 13.1.

## Task 0.2 effect

This record advances task 0.2 from static repository inspection to a bounded
read-only connectivity/schema probe. It does **not** complete task 0.2, authorize
production mutation, or establish that the endpoint is production. Exact
data/grant evidence remains restricted and outstanding, so task 0.2 remains an
ordinary unchecked checklist item.
