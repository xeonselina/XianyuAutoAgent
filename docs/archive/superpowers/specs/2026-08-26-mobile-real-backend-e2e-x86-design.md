# Mobile Real-Backend E2E x86 Design

**Date:** 2026-08-26

**Status:** Approved in chat

## Context

The mobile Playwright suite contains 79 tests. The current suite mixes pure
frontend mocks with tests that assume a live backend, authenticated tenant,
business data, desktop frontend, and mobile frontend. Without that environment,
the authentication bootstrap returns 404, router initialization stops, and the
real-backend cases fail or skip because their data preconditions are absent.

The existing production authentication flow is already implemented. It supports
SMS login, a `tenant_session` cookie, stable per-session CSRF, tenant resolution, and
per-tenant database routing. Tencent Cloud credentials have not been configured
for this release. The E2E environment therefore needs to exercise the real
authentication flow with the existing non-production fixed-code sender, without
calling Tencent Cloud.

The release must also be verified as x86. The host is Apple Silicon, so relying
on host-native Node, Chromium, Python, or MariaDB would not meet that condition.

## Goals

- Run all 79 mobile E2E tests in two explicit groups:
  - 27 pure-mock tests with no backend dependency.
  - 52 real-backend tests with deterministic data.
- Require 79 passed, 0 failed, and 0 skipped.
- Run MariaDB, the backend, Vite, and Playwright/Chromium as `linux/amd64`.
- Exercise the real SMS request/verify routes with a fixed test code.
- Exercise the real tenant cookie, `/auth/me`, CSRF, tenant lookup, and tenant
  database routing.
- Keep test credentials and generated artifacts out of the repository.
- Clean all temporary Docker resources after success, failure, or interruption.
- Keep production authentication and business behavior unchanged.

## Non-Goals

- Connecting Tencent Cloud SMS, SF Express, Kuaimai, or Xianyu providers.
- Testing NAS deployment, public ingress, TLS, or production migration.
- Adding MariaDB or any other service to the production deployment topology.
- Adding Docker Compose, Redis, Celery, APScheduler, or persistent test tables.
- Running tests against the NAS or a production database.
- Replacing real-backend coverage with request mocks or auth bypasses.

## Chosen Architecture

The test harness uses three temporary `linux/amd64` containers on one private
Docker network:

1. An ephemeral MariaDB 10.11 container.
2. An app container built from the current repository with
   `inventory-manager:saas-main-lite` and `PLATFORM=linux/amd64`.
3. A Playwright container matching the locked `@playwright/test` version. It
   installs the locked desktop and mobile dependencies, starts both Vite
   servers, and runs Chromium.

The MariaDB port is not published to the host. The app is reachable only by its
network alias. The Vite servers and Chromium run in the same Playwright
container, so the browser uses loopback ports 5002 and 5003 while Vite proxies
backend requests through the private Docker network.

No Compose file is added. A test-only orchestration script creates exact named
resources, validates their labels and architecture, and removes them through an
exit trap.

## Components

### x86 Orchestrator

The orchestrator has one purpose: create, validate, run, and remove the
temporary E2E stack.

It will:

- Build the current app image with `PLATFORM=linux/amd64`.
- Pull or run MariaDB and Playwright with `--platform linux/amd64`.
- Verify Docker image architecture and `uname -m` before tests begin.
- Create a private network and exact labeled containers.
- Generate random database and application secrets in process memory.
- Run database preparation as a one-shot command.
- Start the restricted app runtime.
- Wait on MariaDB ping, `/health`, and Vite HTTP readiness conditions.
- Run mock and real suites separately.
- Parse machine-readable results and enforce exact pass/skip totals.
- Print redacted diagnostics on failure and clean all resources.

The orchestrator will never accept arbitrary database names or broad cleanup
targets. Its database names must contain `e2e_test`, and its Docker resources
must carry the expected test-scope label before removal.

### Database Preparer

Database preparation is a separate one-shot process. It receives root authority
only while creating the two temporary databases and their restricted test user.
The long-running app does not receive the root URL or provisioner authority.

The preparer will:

- Create a control database and tenant database whose names contain
  `e2e_test`.
- Run the control and business Alembic migrations to their current heads.
- Create one database user with grants limited to those two databases.
- Verify the effective grants before starting the app.
- Seed the control and tenant records described below.

Because the MariaDB container is ephemeral, cleanup removes the entire database
container instead of issuing broad table or schema deletion commands.

### E2E Backend Runner

The app image keeps its production default unchanged. For E2E only, Docker
overrides the command and read-only mounts a small test runner that creates the
app with a `TestingConfig` subclass.

The runner uses:

- `TESTING=True`.
- `IS_PRODUCTION=False`.
- `AUTH_BYPASS_FOR_TESTS=False`.
- A fixed development SMS code.
- The restricted control and tenant database URLs.
- Non-default random `SECRET_KEY` and `SAAS_MASTER_KEY` values.
- No Tencent, SF, Kuaimai, or Xianyu credentials.
- No `PROVISIONER_DATABASE_URL` in the long-running app.

The runner binds port 5001 inside the private network and disables Flask debug
mode and the reloader.

### Vite and Playwright Runner

Desktop Vite runs on port 5002 and mobile Vite runs on port 5003 inside the x86
Playwright container. Both configurations gain a development-only backend
target override and proxy `/auth`, `/api`, and `/web`. Their normal local target
remains `http://localhost:5001` when the override is absent.

All browser and API URLs use one host spelling so host-only cookies are shared
across ports. Direct E2E API calls go through the mobile origin instead of using
a hard-coded backend origin.

## Seed Dataset

The seed is minimal, deterministic, and prefixed as E2E data. It contains:

- One active tenant with a future expiry.
- One active admin member using a reserved test phone number.
- One warehouse.
- Active main-device models and accessory models for a phone holder and tripod.
- Main and accessory devices with stable serial-number prefixes.
- Devices covering active, sold, decommissioned, damaged, and retired lifecycle
  states.
- Rentals covering not-shipped, shipped, returned, and completed states.
- A shipped rental overlapping the current runtime date for Gantt coverage.
- Searchable customer and address values.
- One predecessor/successor rental pair and relay case in the current relay date
  window.

Dates needed for current-state screens are calculated relative to the run date.
Test-created rentals continue to use the existing guarded E2E prefix and safe
date checks. The temporary database is the primary cleanup boundary, while the
existing per-test deletion guards remain defense in depth.

## Authentication and CSRF Flow

The real suite uses Playwright global setup to call `/auth/sms/request` and
`/auth/sms/verify` through the mobile Vite origin. The fixed code is accepted by
the real `AuthService`; the response stores a real host-only `tenant_session`
cookie. Storage state is kept only inside the temporary Playwright container.

Each page then bootstraps through the real `/auth/me` route. `/auth/me` returns
the same one-way-derived CSRF token for the lifetime of the current server-side
session, so multiple pages and API contexts cannot invalidate each other.
Test-only API helpers still refresh the current session immediately before a
write and supply the returned CSRF token. The real project uses one Playwright
worker to keep its deterministic business fixtures isolated.

The mock project does not use global login or storage state. Its existing shared
mock-auth helper remains limited to pure frontend fixtures.

## Test Partition

The current mixed `edit-rental.spec.ts` file contains one pure-mock damage-note
describe block. That block moves to a dedicated mock spec. The remaining files
can then be selected by explicit mock and real Playwright configurations without
title-based grep rules.

The package scripts expose:

- A pure-mock command that starts only mobile Vite and expects 27 passes.
- A real-backend command invoked by the x86 orchestrator and expecting 52
  passes.
- A full command that runs both groups and expects 79 passes.

The real suite is serial. The mock suite may use normal Playwright concurrency
because each page owns its routes and has no shared backend state.

## Error Handling and Cleanup

The harness uses condition-based readiness checks with bounded timeouts. Both
Playwright projects explicitly use zero retries. JSON reports are parsed to
require the exact expected, passed, failed, skipped, flaky, and interrupted
counts instead of matching human-readable reporter text. The harness also
requires an empty top-level runner error list and a zero Playwright process
exit status, so global setup or teardown failures cannot be reported as clean.

On failure it prints:

- The failing stage and command status.
- Exact report statistics and at most ten failed test titles.
- A bounded tail of relevant container logs for readiness failures.
- Architecture and readiness diagnostics.

The diagnostic path redacts passwords, session cookies, fixed codes, CSRF
tokens, and database URLs. It does not print environment dumps.

An exit trap handles success, test failure, shell error, interrupt, and
termination. Before removing a resource, cleanup verifies its exact name and
test-scope label. JSON reports live in an OS temporary directory mounted into
the container and are deleted when the run exits. Screenshots, video, storage
state, `test-results`, installed dependencies, and copied source remain inside
container-local temporary filesystems and disappear with the container.

## Expected Repository Changes

Test infrastructure changes are expected in:

- Desktop and mobile Vite development proxy configuration.
- Mobile Playwright base, mock, and real configurations.
- Mobile E2E global login and authenticated API helpers.
- A test-only database seed/backend runner.
- An exact-target x86 orchestration script and its safety tests.
- The mixed edit-rental E2E split.
- Mobile package scripts and lockfile only if scripts require it; dependency
  versions remain unchanged.

Production route handlers, auth stores, router guards, database models, and
business services are not expected to change. If implementation proves that a
production behavior change or architectural refactor is required, work stops
for user review.

## Verification

Implementation is accepted only when fresh commands show:

- x86 architecture checks pass for MariaDB, app, and Playwright containers.
- Mock E2E: 27 passed, 0 failed, 0 skipped.
- Real E2E: 52 passed, 0 failed, 0 skipped.
- Full E2E: 79 passed, 0 failed, 0 skipped.
- Relevant backend and frontend tests pass.
- Mobile `npm audit --audit-level=low` reports zero vulnerabilities.
- Mobile production build passes.
- `git diff --check` passes.
- Sensitive-information scan finds no committed secrets.
- `git status --short` contains no Playwright or Docker test artifacts.

Before final completion, the broader backend, desktop, and mobile release checks
will be rerun in proportion to the files changed. The final implementation will
be committed and pushed to `origin/saas-main-lite`, with the commit SHA and
local/remote equality reported.

## Known Limits

- Fixed-code login validates application authentication behavior but not the
  Tencent Cloud delivery provider, signing approval, quota, or deliverability.
- External logistics and marketplace providers are not exercised with real
  credentials.
- Docker's x86 emulation on Apple Silicon may be slower than native execution;
  timeouts must represent service readiness, not architecture-specific sleeps.
- This harness validates local release behavior, not NAS networking, reverse
  proxy settings, TLS, or production migration state.
