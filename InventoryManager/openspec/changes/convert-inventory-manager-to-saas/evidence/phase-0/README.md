# Phase 0 Evidence Index

This directory records the evidence required by Phase 0 of the SaaS conversion.
It is intentionally separate from the confirmed product design and delta specs:
evidence may be refreshed as the repository and production environment change,
while D01–D64 remain governed by the decision log.

## Snapshot

- Captured: 2026-08-21 (Asia/Shanghai)
- Branch: `saas-main`
- Base commit: `53193b6724693132be13cd084101e9cd62142c63`
- Scope: local repository and local test/build environment, plus the explicitly
  bounded configured-private-database read-only probe; no target is called
  production without independent deployment identity evidence

## Evidence set

- `test-baseline.md`: local backend/frontend regression and build baseline
- `code-surface-inventory.md`: repository-static route, persistence, scheduler,
  provider, file, print, and client-fan-out inventory; runtime/production evidence
  remains outstanding for tasks 0.1 and 0.3
- `security-and-environment-baseline.md`: local schema/configuration/secret/port
  baseline, repository-side containment, Phase 0 credential-disposition inventory,
  and implementation-independent external-readiness evidence for tasks 0.2,
  0.10, and 0.11
- `d12-change-rebase-matrix.md`: completed archive, pause, rebase, and superseding
  disposition for tasks 0.4-0.9
- `configured-database-readonly-probe.md`: redacted read-only connectivity,
  schema-shape, Alembic, integrity, grant, and network-posture findings for the
  private database configured by the ignored local environment; production
  identity and the full restricted task 0.2 package remain outstanding
- `risk-disposition-ledger.md`: D61's bounded acceptance and compensating-control
  status for the existing database/SF/Kuaimai classes, plus the separate Xianyu
  condition and retired Core application-key classes
- `migration-checklist.md`: short execution sequence from inventory/readiness
  through D61 closure, testing, T+168h rehearsal, reconciliation, cutover,
  observation, and contract cleanup

## Current status and sequencing

Production data/grant evidence, runtime trace/query evidence, the complete
current-state credential/exposure inventory, and external-readiness information
are still unfinished. That status must remain visible, but it is not a blanket
prohibition on unrelated implementation work.

For 0.10, the immediate work is containment: finish the current inventory, stop
new or reintroduced use, prohibit promotion of the current unsafe worktree/image,
and bind each unresolved cleanup or retirement item to its later implementation
task. Final removal of legacy `SECRET_KEY`/`API_KEY` and proof that old values or
artifacts have no authority belong to tasks 4.3, 4.9-4.10, 8.10, 12.10, and
13.11, after the replacement mechanisms exist.

For 0.11, Phase 0 records accounts, qualifications, permissions, owners, lead
times, target topology, implementation dependencies, and an active-smoke plan.
It does not require `/health/external`, `/health/monitor`, the NAS pull workflow,
platform-root-key copies, or active-smoke results before those capabilities
exist. Stage 11 implements the operational paths; task 12.13 performs the first
real SMS/SF/monitoring/NAS/root-key verification and task 13.1 refreshes it
before production cutover.

Still-authoritative provider/database credentials remain governed by D61 only
for its three precisely scoped legacy classes. Each D61 window is at most 30×24
hours, needs explicit renewal, ends on any trigger, and never extends past the
first production-scale rehearsal. A delayed or changed candidate never extends
D61. Phase 0 readiness also never asserts that an exposed credential or artifact
is safe.

Tasks 0.1-0.3, 0.10-0.11, and 0.13 remain unfinished in this snapshot. Follow
`migration-checklist.md` for the simplified project sequence; unsafe image
promotion and unapproved live external actions remain out of scope even while
safe implementation work continues.
