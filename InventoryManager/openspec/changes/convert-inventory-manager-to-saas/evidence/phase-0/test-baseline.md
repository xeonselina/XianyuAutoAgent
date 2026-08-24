# Local Test and Build Baseline

## Context

- Captured: 2026-08-21 (Asia/Shanghai)
- Branch: `saas-main`
- Base commit: `53193b6724693132be13cd084101e9cd62142c63`
- Python: 3.12.13 (`venv/bin/python3`)
- Node.js: 24.6.0
- npm: 11.5.1
- OpenSpec CLI: 0.16.0

The working tree already contained the approved SaaS design/spec/task edits when
this baseline was captured. This document records local regression evidence; it
does not claim production acceptance.

## Results

| Surface | Command | Result | Elapsed |
| --- | --- | --- | --- |
| Backend collection | `venv/bin/python3 -m pytest --collect-only -q` | 165 tests collected | local run |
| Backend suite | `venv/bin/python3 -m pytest -q` | 165 passed; 1,192 warnings | 9.23 s |
| Desktop unit suite | `npm run test:run` in `frontend/` | 33 files, 319 tests passed | 7.12 s |
| Mobile production build | `npm run build` in `frontend-mobile/` | passed; 409 modules transformed | 3.25 s |
| Desktop production build | `npm run build` in `frontend/` | passed; 2,727 modules transformed | 5.58 s |
| OpenSpec strict validation after damage-note archive | `openspec validate --all --strict --no-interactive` | 22 passed, 0 failed | local run |
| Patch hygiene | `git diff --check` | passed | local run |

## Baseline observations

- Backend warnings are dominated by deprecated `datetime.utcnow` /
  `datetime.utcfromtimestamp` calls and SQLAlchemy legacy `Query.get` usage. They
  are migration risk signals, not failures in this run.
- The desktop production build reports a main JavaScript chunk of approximately
  2.78 MB (approximately 883 KB gzip), above Vite's 500 KB warning threshold.
- Neither frontend build left tracked generated artifacts in the working tree.

## Evidence still required for task 0.3

The following must be captured against a representative environment and data set;
the local suite above cannot substitute for it:

- desktop and mobile network traces for booking, editing, Gantt, search, batch
  shipping, SF tracking, inspection, and Xianyu alerts;
- SQL query counts and connection checkout counts for the same flows;
- p50/p95 latency and uncompressed/compressed response byte counts;
- test data scale, run identifier, sampling window, and raw trace locations.

Task 0.3 therefore remains unchecked in the simplified Phase 0 checklist.

## Post-D12 and repository-containment verification

After closing the two D12 archive items and applying repository-side P0
containment, the following verification was run against the shared worktree:

| Surface | Result |
| --- | --- |
| Backend full suite | 189 passed; 1,246 warnings |
| Desktop full suite | 33 files, 326 tests passed |
| Desktop type-check and production build | passed; 2,727 modules transformed |
| Express-type focused backend suite | 20 passed |
| Express-type focused desktop suite | 13 passed |
| Security fail-closed/log-redaction suite | 4 passed |
| OpenSpec full strict validation | 22 passed, 0 failed |
| Active `.env` values versus tracked worktree | 0 exact matches; scanner emitted no values |
| Shell syntax / missing-password fail-closed checks | passed |
| Compose YAML parse | both production and test files parsed; 4 and 1 services respectively |
| Patch hygiene | `git diff --check` passed |

The installed Docker CLI does not include the Compose subcommand/plugin, so full
Compose interpolation/runtime validation was not performed locally. Production
deployment and independent network probes remain explicit external gates.
