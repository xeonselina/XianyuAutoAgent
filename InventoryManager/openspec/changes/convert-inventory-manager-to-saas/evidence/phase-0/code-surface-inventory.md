# Code Surface Inventory and Trace Plan

## 1. Context, scope, and evidence status

- Captured: 2026-08-21; refreshed against the same working tree on 2026-08-22
  (Asia/Shanghai)
- Scope: the current `InventoryManager` working tree, including already-present
  uncommitted changes; this is a static code inventory unless a result is explicitly
  labelled as a runtime route-map observation.
- Covered Phase 0 tasks: static evidence for 0.1 and the code-derived request/SQL
  amplification hypotheses needed to execute 0.3.
- Excluded: product-code changes, schema changes, provider submissions, physical
  printing, production database inspection, and deployment mutation.

The current application has one global Flask application, one global
Flask-SQLAlchemy binding, one business database URI, global provider credentials,
and no trusted user or tenant context. Unless stated otherwise, every resource in
this document is therefore owned by the single legacy installation rather than by
an enforceable tenant boundary.

This document does **not** complete task 0.1 or 0.3. Task 0.1 still needs the bounded
deployed-environment inventory in section 11. The HTTP/SQL counts below are static
fan-out expectations, not measured p50/p95 or byte results for task 0.3.

## 2. Reproducible generation and refresh method

Run all commands from the `InventoryManager` repository root. The reproducible
route-map command below uses the testing configuration, disables scheduler startup
in memory, and neither calls a provider nor queries the database. Because testing
intentionally enables the SF test blueprint, its result is not the production route
surface.

### 2.1 Registered route map, method counts, and exact duplicate rules

```bash
TESTING=true venv/bin/python3 - <<'PY'
from collections import Counter, defaultdict

from app.utils import scheduler as scheduler_module
scheduler_module.init_scheduler = lambda app: None

from app import create_app

app = create_app('testing')
rules = [
    rule for rule in app.url_map.iter_rules()
    if rule.endpoint != 'static'
]

method_counts = Counter()
by_rule_method = defaultdict(list)
for rule in rules:
    methods = sorted(set(rule.methods) - {'HEAD', 'OPTIONS'})
    for method in methods:
        method_counts[method] += 1
        by_rule_method[(str(rule), method)].append(rule.endpoint)
    print(f"{','.join(methods):10} {str(rule):65} {rule.endpoint}")

print('route_rules', len(rules))
print('methods', dict(sorted(method_counts.items())))
print('duplicates')
for (path, method), endpoints in sorted(by_rule_method.items()):
    if len(endpoints) > 1:
        print(method, path, endpoints)
PY
```

Observed testing result for this snapshot:

- 125 non-`static` rules;
- 76 GET, 35 POST, 10 PUT, 3 DELETE, and 1 PATCH rule;
- five exact duplicate GET paths, listed in section 3.3.

`app/__init__.py:73-77` registers the three `/api/sf-test` rules only when
`app.testing` is true or when development is both in debug mode and explicitly sets
`ENABLE_SF_TEST_API`. Therefore the current environment boundary is:

- testing and opted-in development: 125 rules (76 GET / 35 POST / 10 PUT /
  3 DELETE / 1 PATCH);
- production, default configuration, and development without the opt-in: 122 rules
  (75 GET / 33 POST / 10 PUT / 3 DELETE / 1 PATCH), with no SF test routes.

The arithmetic for the disabled case removes the SF test blueprint's one GET and
two POST rules. A raw environment-specific route-map artifact is still required by
section 11 before task 0.1 is checked.

### 2.2 Static refresh commands

```bash
# Blueprint composition and decorator routes.
rg -n "register_blueprint|@.*(route|get|post|put|patch|delete)\\(" \
  app/__init__.py app/routes --glob '*.py'

# ORM/session reads, writes, and transaction boundaries.
rg -n "db\\.session|\\.query\\b|db\\.get\\(|paginate\\(" \
  app --glob '*.py'
rg -n "db\\.session\\.(add|add_all|delete|flush|commit|rollback|execute)" \
  app --glob '*.py'

# Server/client timers, scripts, provider calls, and file/print effects.
rg -n "BackgroundScheduler|add_job|setInterval|setTimeout|debounce" \
  app frontend/src frontend-mobile/src scripts \
  --glob '*.py' --glob '*.ts' --glob '*.vue' --glob '*.sh'
rg -n "requests\\.(get|post)|OcrClient|print_image|window\\.print|open\\(|write\\(" \
  app frontend/src frontend-mobile/src scripts . \
  --glob '*.py' --glob '*.ts' --glob '*.vue' --glob '*.sh'

# Confirm that no identity/session/tenant middleware has appeared.
rg -n "flask\\.session|session\\[|login_required|current_user|csrf|tenant_id|RBAC" \
  app config.py run.py --glob '*.py'

# Operational entry points outside the Python application tree.
rg -n "db upgrade|docker|push|pull|ssh|mysql|drop|create_all|DATABASE_URL" \
  Makefile makefile.example windows-*.ps1 Dockerfile docker-compose*.yml \
  init.sql migrations deploy.sh start.sh simple_backup.sh
```

When refreshing this evidence, save the command output with the commit, dirty-tree
status, Python/Node versions, and timestamp. A changed route total or a new ORM /
provider file requires this inventory to be reviewed before migration work resumes.

## 3. HTTP route and permission inventory

### 3.1 Blueprint composition

| Registration surface | Registered resources | Evidence |
| --- | --- | --- |
| Application factory | Always registers `web` at `/`, `external_api` at `/external-api`, `vue_app`, legacy tracking, device-model, statistics, shipping-batch, SF tracking, inspection, and rental statistics. SF test is testing-only or debug-development opt-in and is absent in production/default operation. | `app/__init__.py:60-77` |
| Nested `web` blueprint | pages, Gantt, device, rental, inventory, OCR, customer, Xianyu alert, and relay-case blueprints | `app/routes/web.py:6-28` |
| Cross-cutting policy | `CORS(app)` is applied globally. `Config.CORS_ORIGINS` exists but is not passed to the extension. | `app/__init__.py:46-47`; `config.py:62-63` |
| Health | Global `GET /health` | `app/routes/web.py:31-38` |

### 3.2 Complete grouped rule list

The count column is the number of concrete Flask rules, not the number of logical
capabilities.

| Group | Count | Registered methods and paths | Evidence |
| --- | ---: | --- | --- |
| Customer | 2 | `GET /api/customers/search`; `GET /api/customers/rentals` | `app/routes/customer_api.py:50,126` |
| Device | 10 | `GET /api/devices`; `POST /api/devices/search`; `GET/PUT/DELETE /api/devices/<device_id>`; `POST /api/devices`; `PUT /api/devices/<device_id>/lifecycle`; `PUT /api/devices/<device_id>/mark-sold`; `GET /api/devices/lifecycle/summary`; `GET /api/devices/lifecycle/list` | `app/routes/device_api.py:19-383` |
| Device model | 2 | `GET /api/device-models`; `GET /api/device-models/<model_id>/accessories` | `app/routes/device_model_api.py:13-20` |
| External API (`/external-api`) | 12 | `PUT /devices/<id>/status`; `GET /inventory/available`; `POST /inventory/check`; `POST /rentals`; `GET/PUT /rentals/<id>`; `POST /rentals/<id>/cancel`; `GET /devices`; `GET /devices/<id>`; `GET /statistics`; public `GET /health`; public `GET /docs` | `app/routes/external_api.py:30-480` |
| Gantt/reorder | 6 | `GET /api/gantt/data`; `GET /api/gantt/daily-stats`; `POST /api/rentals/find-slot`; `POST /api/gantt/reorder/analyze`; `POST /api/gantt/reorder/preview`; `POST /api/gantt/reorder/execute` | `app/routes/gantt_api.py:13-48` |
| Inspection (`/api/inspections`) | 6 | `GET /rental/latest/<device_id>`; `GET /rental/latest/by-name/<device_name>`; `POST /`; `GET/PUT /<inspection_id>`; `GET /` | `app/routes/inspection.py:11-255` |
| Inventory | 1 | `GET /api/inventory/available` | `app/routes/inventory_api.py:13` |
| OCR | 1 | `POST /api/ocr/id-card` | `app/routes/ocr_api.py:17` |
| Relay case | 6 | `GET /api/relay-cases`; `GET /api/relay-cases/manual-options`; `POST /api/relay-cases/manual`; `PUT /api/relay-cases/<predecessor>/<successor>`; `POST /api/relay-cases/<case>/tracking/refresh`; `POST /api/relay-cases/tracking/refresh-batch` | `app/routes/relay_case_api.py:12-48` |
| Rental | 18 | `GET /api/rentals/estimate-logistics`; `GET/POST /api/rentals`; `GET /api/rentals/pending-returns`; `GET /api/rentals/due-today`; `GET/PUT/DELETE /api/rentals/<id>`; `PUT /api/rentals/<id>/status`; `POST /api/rentals/<id>/ship-to-xianyu`; `POST /api/rentals/check-conflict`; `POST /api/rentals/check-duplicate`; `GET/PUT/DELETE /web/rentals/<id>`; `POST /api/rentals/fetch-xianyu-order`; `POST /api/rentals/search`; `GET /api/rentals/by-ship-date` | `app/routes/rental_api.py:15-145` |
| Rental statistics (`/api/rental-stats`) | 3 | `GET /models`; `GET /periodic`; `GET /x200u-forecast` | `app/routes/rental_stats_api.py:48-338` |
| SF test (`/api/sf-test`, conditional) | 3 | `POST /order/<rental_id>`; `GET /status`; `POST /mock-order`; registered only in testing or opted-in debug development | `app/__init__.py:73-77`; `app/routes/sf_test_api.py:15-102` |
| SF tracking (`/api/sf-tracking`) | 3 | `GET /list`; `POST /query`; `POST /batch-query` | `app/routes/sf_tracking_api.py:28-176` |
| Shipping batch (`/api/shipping-batch`) | 6 | `POST /schedule`; `GET /status`; `PATCH /express-type`; `GET /printers`; `POST /print-waybills`; `POST /ship-to-xianyu/<rental_id>` | `app/routes/shipping_batch_api.py:13-48` |
| Statistics (`/api/statistics`) | 4 | `GET /recent`; `GET /date-range`; `GET /latest`; `POST /calculate` | `app/routes/statistics_api.py:14-270` |
| Legacy tracking | 7 | `POST /api/tracking/query`; `POST /api/tracking/batch-query`; `POST /api/tracking/update-now`; `GET /api/tracking/scheduler-status`; removed 410 endpoints `POST /api/device/update-status`, `POST /api/device/force-update-status`, `GET /api/device/status-summary` | `app/routes/tracking_api.py:15-175` |
| Vue/static-page serving | 22 | `GET /`, `/app/`, `/assets/<path>`, `/favicon.ico`; desktop SPA aliases `/gantt`, `/contract/<path>`, `/shipping/<path>`, `/batch-shipping-order`, `/batch-shipping`, `/statistics`, `/rental-stats`, `/sf-tracking`, `/relay-management`, `/inspection`, `/inspection-records`; mobile `/mobile`, `/mobile/`, `/mobile/assets/<path>`, `/mobile/<path>`; legacy `/vue`, `/vue/`, `/vue/<path>` | `app/routes/vue_app.py:29-113` |
| Legacy/page serving | 9 | `GET /gantt`; `/shipping/<int:rental_id>`; `/contract/<int:rental_id>`; `/sf-tracking`; `/batch-shipping`; `/batch-shipping-order`; `/inspection`; `/devices`; `/rentals` | `app/routes/web_pages.py:20-89` |
| Xianyu alerts | 3 | `GET /api/xianyu-order-alerts`; `POST /api/xianyu-order-alerts/refresh`; `POST /api/xianyu-order-alerts/<order_no>/ignore` | `app/routes/xianyu_order_alert_api.py:14-26` |
| Health | 1 | `GET /health` | `app/routes/web.py:31` |
| **Testing / opted-in development total** | **125** | **76 GET / 35 POST / 10 PUT / 3 DELETE / 1 PATCH** | generated by section 2.1 |
| **Production/default total** | **122** | **75 GET / 33 POST / 10 PUT / 3 DELETE / 1 PATCH; SF test absent** | testing result minus the conditional blueprint; must be attached as a separate raw route-map artifact |

### 3.3 Duplicate and overlapping page rules

| URL shape | Registered endpoints | Risk |
| --- | --- | --- |
| Exact `GET /gantt` | nested `web.web_pages.gantt` and `vue_app.vue_router_routes` | Registration/order-dependent handler selection; both currently return the desktop SPA. |
| Exact `GET /batch-shipping` | nested legacy page and `vue_app.vue_router_routes` | Same result today, but future changes can silently diverge. |
| Exact `GET /batch-shipping-order` | nested legacy page and `vue_app.vue_router_routes` | Same risk. |
| Exact `GET /sf-tracking` | nested legacy page and `vue_app.vue_router_routes` | Same risk. |
| Exact `GET /inspection` | nested legacy page and `vue_app.vue_router_routes` | Same risk. |
| Overlap `/shipping/123` | `/shipping/<int:rental_id>` and `/shipping/<path:subpath>` | Not reported as an exact rule-string duplicate, but both patterns accept a numeric URL. |
| Overlap `/contract/123` | `/contract/<int:rental_id>` and `/contract/<path:subpath>` | Same pattern-overlap risk. |

Evidence: `app/routes/web_pages.py:20-80`, `app/routes/vue_app.py:57-68`.

### 3.4 Effective authorization and tenant boundary

| Surface | Resource | Effective permission now | Tenant ownership now | Retry / abuse risk |
| --- | --- | --- | --- | --- |
| Internal APIs and pages | All device, rental, customer PII, inspection, statistics, tracking, provider, print, and mutation resources | No login, server-side session, membership, RBAC, or CSRF checks were found. Routes are anonymously callable when network-reachable. | Global legacy schema; IDs, names, dates, and request bodies select rows directly. | Any caller can repeat mutations or provider/print requests; no stable request idempotency key. |
| Global CORS | All Flask responses | `CORS(app)` with default permissive behavior; configured origin list is unused. | Global | Broadens browser-callable attack surface. |
| External API | Ten protected business routes | `Config.API_KEY` loads the environment value and the decorator compares it with `X-API-Key`; a missing header or missing configured value fails closed with 401. | One configured global key, never tenant-scoped | When configured, one key grants all protected records and writes. There is no key rotation/audit/tenant binding. |
| External health/docs | `/external-api/health`, `/external-api/docs` | Public | Global | Docs disclose route surface; low direct side effect. |
| SF test API | Configuration booleans and order submission | Absent in production/default operation. When enabled for testing or opted-in debug development, it has no route-level authentication; `/status` exposes endpoint/mode/configuration booleans (not sender values), and `/mock-order` can call the configured account. | Global SF account | High inside an enabled environment: duplicate or unauthorized provider orders. `/order/<id>` still omits the required `scheduled_time`, so that path is stale/broken. |
| OCR | Raw identity-card image and extracted identity data | Public upload endpoint | Global Aliyun account; no tenant | PII exfiltration, memory/CPU amplification, provider cost. |
| Print | Global printer and all eligible rentals | Public internal API; no warehouse/printer authorization | One global printer SN | Critical physical duplicate/partial printing on retries. |

The absence check is reproducible with the last command in section 2.2.
`Config`'s cookie flags (`config.py:57-60`) do not establish identity because no
application session usage was found. `run.py:11-14` also calls the default `Config`
rather than selecting `ProductionConfig` from `FLASK_ENV`.

## 4. Database reads, writes, and session/commit model

### 4.1 Topology and active models

- One global `db = SQLAlchemy()` is initialized once and attached to the application
  factory (`app/__init__.py:23,43`).
- Docker requires `DATABASE_URL`; a non-Docker process selects
  `DATABASE_URL_HOST`, then `DATABASE_URL`, then a local SQLite fallback
  (`config.py:9-32`). There are no SQLAlchemy binds and no tenant-aware
  engine/session resolver.
- Engine options set `pool_size=10`, `pool_recycle=3600`, and `pool_pre_ping=True`,
  but do not cap `max_overflow` (`config.py:34-38`). The checked-in Gunicorn config
  uses four non-preloaded gevent workers (`gunicorn_config.py:15-18,29-32`): the
  base pool budget is therefore 40 connections, before SQLAlchemy's default
  overflow and before workers/jobs outside Gunicorn.
- Flask-SQLAlchemy supplies an application/request-context-scoped ORM session, but
  the code has no higher-level unit-of-work abstraction. Services and handlers call
  `commit()` independently.
- Active model imports are `Device`, `Rental`, `AuditLog`, `DeviceModel`,
  `RentalStatistics`, `InspectionRecord`, `InspectionCheckItem`,
  `RentalRelayBinding`, `RentalRelayCase`, `XianyuOrderAlert`, and
  `XianyuOrderSyncState` (`app/models/__init__.py:5-20`). A legacy
  `rental_accessory.py` exists but is not imported into active metadata.
- Redis is declared in Compose but no Redis-backed cache, task queue, lock, or
  server-side session use was found.

### 4.2 ORM-touching code surface

Static scanning found database access in the following active areas. Model files
contain reusable query helpers; routes/handlers/services are the externally
triggerable entry points.

- Handlers: `app/handlers/rental_handlers.py`,
  `app/handlers/shipping_batch_handlers.py`,
  `app/handlers/relay_case_handlers.py`.
- Routes: `customer_api.py`, `device_api.py`, `external_api.py`, `inspection.py`,
  `rental_stats_api.py`, `sf_test_api.py`, `sf_tracking_api.py`, and
  `statistics_api.py` under `app/routes/`.
- Services: `device/device_service.py`, `gantt/gantt_service.py`,
  `gantt/reorder_service.py`, `inspection_service.py`, `inventory_service.py`,
  `relay/relay_case_service.py`, `rental/rental_service.py`, legacy
  `rental_service.py`, `shipping/waybill_print_service.py`,
  `printing/shipping_slip_image_service.py`, and
  `xianyu_order_reconciliation_service.py`.
- Utilities/models: `rental_validator.py`, `scheduler_tasks.py`, and query helpers
  in `device.py`, `device_model.py`, `rental.py`, `rental_statistics.py`,
  `audit_log.py`, and `xianyu_order_alert.py`.

### 4.3 Resource/permission/tenant/transaction matrix

All rows inherit the anonymous internal-route and global-schema boundary described
in section 3 unless the external-key exception is stated.

| Resource and operation | Read/write entry points | Commit boundary now | Retry, race, and isolation risk |
| --- | --- | --- | --- |
| Devices and lifecycle | Reads/writes in `device_api.py:19-408`; validators in `rental_validator.py:37-147`; reusable queries in `models/device.py:84-263` | Device create/update/delete/lifecycle handlers each commit directly (`device_api.py:103-121,168-184,210-219,263-280,304-324`). | Repeated POST can duplicate unless a field-level constraint happens to reject it; repeated delete/update has no request ledger. No tenant or warehouse filter. |
| Rental create and logical accessories | `rental_api.py:21-145`; `rental_handlers.py:83-474`; `services/rental/rental_service.py:146-254` | Main rental is flushed, child accessory rentals are added, then one commit (`rental_service.py:218-254`). | Conflict checks and create are separate requests/queries with no row/advisory lock or exclusion constraint: concurrent bookings can both pass. Client retry after an ambiguous response can create a second rental. |
| Rental edit/delete/status | `rental_handlers.py:161-474,747-821`; `rental_service.py:258-328,375-498`; legacy external service in `services/rental_service.py:38-143` | Multiple service/handler-local commits; child updates share the local transaction, but no repository-wide unit of work. | PUT/DELETE/status operations are not idempotency-ledgered. Lazy child collections add SQL and can race concurrent edits. |
| External rental/device/statistics access | `/external-api` handlers (`external_api.py:30-468`) | Legacy service commits internally; external direct rental update commits at `external_api.py:286-299`. | Intended global key has whole-schema reach. A retry can repeat creates/cancels; no tenant attribution. |
| Gantt reads | `gantt_service.py:23-138` | Read-only request session | Base device+rental queries are followed by lazy device model, device, and accessory/child traversal (`gantt_service.py:79-135`; `models/rental.py:101-126`). SQL grows with returned devices/rentals. |
| Daily Gantt statistics | `gantt_service.py:145-231`; `inventory_service.py:19-79` | Read-only request session | For each day, `get_available_devices` queries all main devices and then up to two rental queries per in-service device. Desktop calls 16 days and mobile 14 days concurrently. |
| Find slot/conflict | `gantt_service.py:234-320`; `inventory_service.py:128-181`; `rental_service.py:333-372` | Read-only checks, followed later by a separate rental mutation | Find-slot executes an availability query per candidate device. Browser conflict checking issues one HTTP request per active device/accessory. Classic time-of-check/time-of-use double-booking risk. |
| Gantt reorder/relay binding | `gantt/reorder_service.py:60-865` | Execute applies binding deletes/adds, audit rows, flush, then commit; rollback on exception (`reorder_service.py:713-865`). | Better local transaction grouping, but no tenant lock key or request idempotency ledger. Preview token and execute still share global rows. |
| Relay cases/bindings/audit | `relay/relay_case_service.py:63-730` | Case creation/update commits at several service operation boundaries (`:440-458`, `:516-540`, `:663-730`). | Local DB atomicity only. Tracking refresh invokes global SF credentials; batch retries can repeat provider reads. |
| Batch shipping selection | `rental_handlers.py:608-745` | Read-only | One base query plus batched relay bindings, then one additional “previous rental” query per returned rental (`:689-731`); serialization can add lazy queries. |
| SF order scheduling | `shipping_batch_handlers.py:27-188` | Reads all selected rentals, calls SF once per eligible rental, mutates rows, and commits once after the loop (`:52-176`). | Critical crash gap: provider order can succeed before DB commit/HTTP response. Whole-request rollback does not undo provider orders. Retry can orphan or duplicate orders; no provider-operation ledger. |
| Express type | `shipping_batch_handlers.py:199-279` | One commit after validation | Repeated PATCH is logically convergent, but authorization/tenant checks are absent. |
| Manual Xianyu shipping | `rental_handlers.py:747-821`; `shipping_batch_handlers.py:354-401`; relay path `relay_case_service.py:560` | Provider call occurs before status/DB commit. | Critical response-loss/crash gap; retry can send the shipment notification again. |
| Inspection records/items | `inspection.py:11-294`; `inspection_service.py:19-194` | Create inserts record+items and commits once (`inspection_service.py:61-96`). Update selects each item individually, recomputes, then commits (`:129-147`). | Update has one SELECT per checklist item and no version check; stale concurrent update can overwrite. No user/device/tenant ownership check. |
| Rental/customer search and history | `rental_service.py:63-138`; `customer_api.py:50-195` | Read-only | Pagination performs count+select; `Rental.to_dict()` can lazy-load device/children. Customer search fetches up to 500 candidates for Python grouping; history fetches up to 200 then lazy-loads device/device-model per result. PII is returned without auth. |
| SF tracking list | `sf_tracking_api.py:28-100` | Read-only | List serialization lazily traverses device/device-model. Provider query endpoints add outbound calls and rate/capacity risk. |
| Statistics | `statistics_api.py:14-312`; `rental_stats_api.py:33-490`; model helpers | `POST /api/statistics/calculate` inserts/updates and commits (`statistics_api.py:241-266`), rolling back at `:312`. | Public recalculation and cron can race; large analytical queries are global and can contend with OLTP. |
| Xianyu alert cache/state | `xianyu_order_reconciliation_service.py:107-275`; `models/xianyu_order_alert.py:94-105` | Full provider list is fetched, pending cache replaced, sync state updated, then committed (`reconciliation_service.py:190-245`); ignore commits separately (`:247-275`). | Host-local file lock only. Reconcile is mostly replace-style but provider pagination/load can be repeated by each host. Alert PII is globally visible. |
| Tracking scheduler writes | `scheduler_tasks.py:23-262` | Batch tracking updates commit once at `:230-236`. | This class is not registered by the current scheduler; if invoked manually it uses global rows/account and has no tenant/job ledger. |
| Audit log | `models/audit_log.py:54-71` and explicit audit rows in relay/reorder | `AuditLog.log_action()` calls `commit()` itself. | A nested audit call can commit business changes earlier than the caller expects, breaking an intended larger transaction/rollback boundary. |

## 5. Server timers, browser timers, and background execution

| Timer/job | Resource/effect | Current permission and tenant boundary | Retry/duplication risk | Evidence |
| --- | --- | --- | --- | --- |
| App-factory scheduler startup | Every `create_app()` tries to start APScheduler, including each non-preloaded Gunicorn worker and scripts that create an app. | Process-local; no user; global schema/providers | `/tmp/inventory_scheduler.lock` serializes only processes sharing one host filesystem. Multiple containers/hosts can each run a scheduler. Jobs are not durable. | `app/__init__.py:63-69`; `gunicorn_config.py:29-32`; `scheduler.py:17-49` |
| Due shipment | Every minute, select due `scheduled_for_shipping` rentals; update state and notify Xianyu. | Global rows/account | Separate host-local task lock. Provider submit precedes commit; failure rolls back and explicitly retries next run, so response loss can duplicate. | `scheduler.py:51-63`; `scheduler_tasks.py:306-421` |
| Xianyu reconciliation | Every ten minutes, list provider orders and replace alert cache. | Global rows/account | Local `flock`; multi-host duplicate provider reads and concurrent DB writes remain possible. | `scheduler.py:65-72`; `xianyu_order_reconciliation_service.py:25-75,190-245` |
| Tracking scheduler | Class and manual entry exist, described as hourly. | Global | Not registered in `scheduler.py`. `/api/tracking/update-now` asks for job id `update_tracking`, which does not exist among the two registered ids, so the endpoint is stale/nonfunctional. | `scheduler_tasks.py:23-262`; `tracking_api.py:111-128`; `scheduler.py:56-70` |
| Desktop Xianyu poll | Snapshot GET every 60 seconds after Gantt mount; mount also triggers immediate provider reconciliation. | Anonymous browser/global alerts | Every open tab adds one read per minute; each initial page load adds a provider-backed refresh. | `frontend/src/composables/useXianyuOrderAlerts.ts:35-124`; `GanttChart.vue:1220-1232` |
| Desktop daily-stat debounce | 300 ms debounce, then 16 concurrent daily-stat requests. Watchers on date range, devices/rentals, and selected model reschedule it. | Anonymous/global | Debounce coalesces nearby changes but does not aggregate days; many tabs or separated changes multiply load. | `GanttChart.vue:536-540,1068-1141,1186-1206` |
| Search debounce | 300 ms customer search; 400 ms mobile rental search. | Anonymous/global PII | Each pause emits a new request; prior in-flight request is not cancelled. | `CustomerHistoryDialog.vue:115-150`; `frontend-mobile/src/views/SearchView.vue:81-128` |

## 6. Independent scripts and operational side effects

| Script/entry point | Resource and existing privilege | Tenant boundary | Side effect and retry risk | Evidence |
| --- | --- | --- | --- | --- |
| `run.py`, `app.py` | App DB credentials and global providers | None | Import creates the app and starts the scheduler. `app.py` also exposes destructive `reset-db` and PII-printing list commands. | `run.py:11-17`; `app.py:12-21,38-136` |
| `start.sh` | Local package manager, filesystem, DB, app | None | Installs dependencies, may create `.env` and directories, runs `flask init-db`/`seed-data`, then starts the app. Commands/config are partly stale; rerun is not a safe production bootstrap. | `start.sh:28-114` |
| `init_db.py` | Full application DB privileges | None | Disables FK checks, `drop_all`, `create_all`, then executes exported SQL. Per-statement errors are printed and processing continues until one final commit, allowing a partially imported result; creating the app can also start scheduler jobs. | `init_db.py:16-113` |
| `migrate_rental_structure.py` | Direct `DATABASE_URL` engine with DDL/DML rights | None | Adds column/FK, copies rows, and drops the legacy table. Existence checks make some steps re-entrant, but commits/DDL span several destructive steps and can leave a partial migration. | `migrate_rental_structure.py:22-46,59-181` |
| `export_data.py` | Full global device/rental read | None | Writes `exported_data.sql.py` containing unmasked customer name, phone, destination, and tracking data; app creation can start scheduler. | `export_data.py:33-140` |
| `scripts/export_db_data.py` | Global model/device/rental/stat/audit read | None | Writes `scripts/exported_data.sql`. Customer identity fields are replaced with Faker data, but tracking numbers remain, and the audit export references fields not present in the active `AuditLog` model, so the script is stale and can fail after partial in-memory generation. | `scripts/export_db_data.py:59-242`; `app/models/audit_log.py:10-33` |
| `simple_backup.sh` | Injected `DB_PASSWORD`, default `inventory_backup` user, one configured database, and a configurable backup directory | Legacy database only | Creates a timestamped single-database dump through a mode-0600 temporary client file, then gzip and append-only log. The hard-coded password and `--all-databases` behavior are gone, but retention, encryption, verification, tenant split, and restore proof are still absent. | `simple_backup.sh:4-45` |
| `scripts/cron_calculate_statistics.sh` | Anonymous HTTP access to statistics mutation | None | POSTs `/api/statistics/calculate` and appends response/log to `/tmp`; concurrent cron/manual calls can race. | `scripts/cron_calculate_statistics.sh:5-34` |
| `deploy.sh` | Docker host, application DB, volumes | None | Stops/rebuilds/restarts all services; uses `db.create_all` rather than migration; `clean` can delete containers, images, and volumes. App creation during init can start a scheduler. | `deploy.sh:44-152,180-230` |
| `Makefile`, `makefile.example` | Developer filesystem, package managers, application DB, Docker/registry, and SSH access to NAS | None; global deployment target | Targets can overwrite `.env`, run schema upgrades, build/run/remove containers, push images, and pull an image on NAS. Repeating a partially completed composite target can repeat stateful steps; target and tag variables are operator-controlled. | `Makefile:50-150,248-349,480-522`; `makefile.example` |
| `windows-config.ps1`, `windows-setup.ps1`, `windows-start.ps1`, `windows-stop.ps1` | Windows package manager, `.env`, local/Docker MySQL, backend/frontend processes | None; one legacy installation | Setup/config scripts install software and write connection settings, including legacy example/default root credentials; start/stop scripts create or control DB/app processes. Partial reruns can overwrite environment state or leave processes/containers running. | `windows-config.ps1:232-284,330-347`; `windows-setup.ps1:117-143`; `windows-start.ps1:81-100`; `windows-stop.ps1:64-82` |
| `init.sql`, active Alembic files, validation SQL, and `migrations_backup/*.py` | Schema/data DDL and DML under the invoking database identity | Global legacy schema | `init.sql` is mounted into MySQL first-start initialization; active Alembic upgrades and validation SQL require explicit version/order control. Backup migration files are outside the active chain and manual execution risks destructive or partial schema drift. | `init.sql`; `migrations/env.py`; `migrations/versions/`; `migrations/validate_bundled_accessory_migration.sql`; `migrations_backup/` |
| `Dockerfile`, Compose files, Nginx config, and Gunicorn config | Image contents, service environment, host ports, volumes, workers, and reverse proxy | Global containers/volumes | Build and startup create stateful services and persistent volumes; Compose initializes MySQL from `init.sql`; Nginx exposes the Web surface and uploads. Port/health settings differ across files, so checked-in topology is not proof of the deployed topology. | `Dockerfile:51-121`; `docker-compose.yml:3-120`; `docker-compose.test.yml`; `docker/nginx/nginx.conf`; `gunicorn_config.py` |
| `build-multiarch.sh` | Docker/buildx | N/A | Replaces a named builder and builds images; optional cleanup. No business DB effect, but it is stateful host tooling. | `build-multiarch.sh:21-116` |
| `check_server_startup.sh` | Docker daemon and container logs/process list | N/A | Read-only diagnostics, but may expose env-adjacent logs/PII to the caller. | `check_server_startup.sh:1-32` |
| `test_slip_generation.py` | Global rental 919 and local filesystem | None | Prints customer PII and writes `/tmp/test_slip.png`; app creation can start scheduler. Rerun overwrites the file. | `test_slip_generation.py:10-46` |
| `test_sf_recursion.py` | SF sandbox client | Global test account | Calls `create_order` with a fixed order id. It is not a unit-only test and can submit to the configured/constructed endpoint. | `test_sf_recursion.py:21-35` |
| `app/utils/sf/callExpressRequest.py` | Embedded SF-looking credentials and sandbox endpoint | Global | Executes a create-order HTTP request at module/import time, without a timeout or main guard. Never import/run during discovery. Credential values are intentionally not reproduced here. | `app/utils/sf/callExpressRequest.py:8-15,75-105` |
| `scripts/rental_statistics.py` | None as Python; contents are SQL | N/A | File extension is misleading and the query uses inconsistent identifiers. Treat as stale documentation, not an executable Python job. | `scripts/rental_statistics.py:1-18` |
Off-repository `cron`, systemd timers, NAS tasks, CI jobs, and operator runbooks cannot
be proven absent by this scan and must be inventoried from the deployed hosts.

## 7. Third-party provider matrix

| Provider/capability | Resource and call sites | Existing credential/permission | Tenant/warehouse boundary | Retry and commit risk |
| --- | --- | --- | --- | --- |
| SF order creation | Global SF monthly account; `place_shipping_order`/SDK create order | Environment credentials plus global sender identity; internal scheduling and conditionally enabled unauthenticated SF-test routes can call it | None. Sender and account are process-global; no warehouse binding. | SDK POST has no timeout and uses a new UUID request id (`sf_sdk_wrapper.py:45-105`). Current logging records service/request ids, status and error summaries rather than full request/response bodies, but there is still no provider ledger/reconciliation fence. Provider succeeds before DB commit. |
| SF cloud waybill/PDF | Cloud print API followed by authenticated in-memory PDF download | Same global SF credentials; token/URL returned by provider | None | Download uses a 30-second timeout. Current code no longer logs the PDF URL/token or writes the PDF to `/tmp`; it logs status/size and some rental/provider error details. Retry repeats provider/PDF work. |
| SF tracking | Single/batch route queries, max 100 numbers | Same global SF credentials and a hard-coded sender phone suffix | None | Read-only provider effect, but calls have the SDK's no-timeout behavior, no app rate limiter, and can be multiplied by users/jobs. |
| Xianyu order detail/list | Booking autofill and alert reconciliation | Global app key/secret/seller from environment | None | 30-second request timeout and no automatic retry. List paginates up to 100 pages. Manual refresh and each app host can repeat the complete provider scan. |
| Xianyu shipment notification | Manual ship, relay ship, and due-shipment scheduler | Global app key/secret and sender fields | None | Mutating provider call precedes DB commit. Ambiguous response/crash can be retried with no operation ledger. |
| Kuaimai print/status | Image print and print-job status | Global app id/secret and one default printer SN. Current logs expose only configuration booleans, request field names, response status/code, and job identifiers—not the app secret or printer SN. | No tenant or warehouse/printer binding | Base URL is plaintext HTTP. Rate-limit handling sleeps two seconds and retries once after mutating/re-signing the same params. Response loss/manual retry can duplicate physical output. |
| Aliyun OCR | Raw ID image to Advanced OCR | Global access key/secret | None | Public PII egress; SDK runtime options set no explicit timeout/retry policy. Full OCR text and extracted ID number are logged. |

Key evidence:

- SF global account/sender: `app/services/shipping/sf_express_service.py:21-42`;
  order payload/call: `:44-182`; redacted PDF download/logging: `:198-235,254-408`;
  SDK POST: `app/utils/sf/sf_sdk_wrapper.py:45-105`.
- SF tracking global credentials/limit: `app/services/shipping/sf_tracking_service.py:23-60`;
  hard-coded phone suffix: `app/routes/sf_tracking_api.py:17-20`.
- Xianyu credentials and request: `app/services/xianyu_order_service.py:24-44,100-200`;
  list/detail/ship: `:202-419`.
- Kuaimai URL, credential loading/redacted logging, retry and print:
  `app/services/printing/kuaimai_service.py:20-45,70-219`.
- OCR egress/logging: `ocr_functions.py:39-95,98-153`; public upload:
  `app/routes/ocr_api.py:17-77`.

The “SF logistics estimate” used by booking is not an external capability. It is a
local province/city lookup with a default of three days
(`app/utils/logistics_estimator.py:10-81`). It must not be mistaken for the required
real SF delivery-time entitlement/capability in task 0.11.

## 8. File, PDF, browser-output, and physical-print effects

| Effect | Resource/permission/tenant boundary | Retry and data risk | Evidence |
| --- | --- | --- | --- |
| Application/access logs | Process-local `logs/`, created by any non-debug/non-test app using process filesystem permissions; global mixed-tenant content | Current SF/Kuaimai request and response logging is redacted, but logs still contain rental/order/tracking identifiers, provider error text/stack traces, and customer data in other paths such as print handling and OCR. Rotation is local, not tenant-separated, and multiple app factories attach handlers. | `app/__init__.py:87-117`; provider references in section 7; `waybill_print_service.py:59`; `ocr_functions.py:98-153` |
| SF PDF bytes | Authenticated PDF download held in memory and passed synchronously to conversion/printing | Current code does not write a predictable server `/tmp` PDF. Repeated requests still repeat the provider download, conversion, and downstream print effects; PDF content remains tenant-unscoped in process memory. | `sf_express_service.py:198-235,385-395` |
| PDF conversion | Provider PDF bytes -> Poppler/pdf2image -> PIL images -> base64, in the synchronous Web request | CPU/RAM and temporary-process amplification; multi-page input multiplies memory and print submissions. | `shipping/pdf_conversion_service.py:34-69,114-180` |
| Shipping-slip image | Global rental read, bundled font/QR assets, in-memory PNG/base64 | Contains customer/device/order information and a hard-coded return identity/address; repeated generation is read-only but feeds duplicate print effects. | `printing/shipping_slip_image_service.py:42-73,133-220,265-377` |
| Batch physical print | SF PDF, one Kuaimai submission per PDF page, then optional generated shipping slip; all synchronous | Critical partial completion: page 1 may print before page 2/slip fails. Browser retry repeats already-printed pages. No durable job/operation ledger. | `shipping/waybill_print_service.py:28-297` |
| Browser printing | Contract, shipping order, and batch shipping-order pages call `window.print()` | Local operator/device side effect; double click/reload can duplicate output and is not auditable server-side. | `RentalContractView.vue:509-510`; `ShippingOrderView.vue:267-268`; `BatchShippingOrderView.vue:249-294` |
| Browser downloads | Rental statistics CSV; image preview download named as an identity-card image | Local workstation files outside server retention/audit; may contain PII. | `RentalStatsView.vue:367-371`; `ImagePreviewDialog.vue:73-79` |
| SQL exports/backups | Repository/local output and NAS dump files | Global data aggregation; see scripts in section 6. | `export_data.py`; `scripts/export_db_data.py`; `simple_backup.sh` |
| Upload/static volumes | Compose mounts a global upload volume and Nginx exposes `/uploads/` publicly | Current OCR keeps input in memory, but any future writer would make files globally public unless policy changes. Nginx accepts 50 MB while Flask caps 16 MB. | `docker-compose.yml:69-71,94-97`; `docker/nginx/nginx.conf:45-46,75-80`; `config.py:40-42` |

## 9. Desktop/mobile request fan-out and server amplification

Counts below cover business API XHR/fetch calls only. They exclude HTML, JS/CSS,
images, favicon, automatic OPTIONS, and the recurring 60-second alert poll. `D` is
the number of active main devices checked in the selected model/filter, `A` the
number of accessory devices, `R` selected/returned rentals, and `P` PDF pages.
Runtime traces must replace these expectations with measured counts.

| Client/flow | Static business-HTTP expectation | Server/provider amplification and important evidence |
| --- | --- | --- |
| Desktop Gantt initial load | **21**: 1 Gantt aggregate + 16 daily stats + 1 device-model + 1 alert snapshot + 1 pending-return + 1 immediate alert refresh | Gantt aggregate has lazy model/accessory reads (`gantt_service.py:45-135`). Each daily-stat request runs all-device availability with up to two rental queries/device (`inventory_service.py:35-68`). Mount/fan-out: `GanttChart.vue:536-540,1068-1114,1220-1232`. Alert refresh can make `ceil(provider_orders/100)` Xianyu pages. |
| Mobile Gantt initial load | **15**: 1 Gantt aggregate + 14 parallel daily stats | `frontend-mobile/src/views/GanttView.vue:88-120,167-170`. Shifting the window repeats all 15 (`:123-127`). |
| Desktop booking dialog open | **2**: accessory devices + device models; main devices are copied from the Gantt store | `BookingDialog.vue:999-1018`; `useDeviceManagement.ts:27-74`. Optional initial Xianyu order adds 1 provider-backed request. |
| Desktop booking availability | **D + A** concurrent conflict POSTs whenever both dates are selected; optional find-slot adds 1 | `BookingDialog.vue:562-575`; `useAvailabilityCheck.ts:45-193`; `useConflictDetection.ts:42-90`. Each conflict endpoint executes a rental query; no batch API. |
| Desktop booking successful submit | **23 after pressing submit**, excluding prior conflict checks: duplicate check 1 + local logistics HTTP 1 + create 1 + store Gantt reload 1 + parent Gantt reload 1 + daily stats 16 + alert snapshot 1 + saved-rental confirmation 1 | `BookingDialog.vue:820-945`; store auto-reload `frontend/src/stores/gantt.ts:303-318`; parent reload/fan-out `GanttChart.vue:839-856`. Create itself checks/loads device and accessories and commits once. |
| Mobile booking open/availability | Warm store: **2** init GETs; cold store: **3** including Gantt. Each complete date/model change issues **1** find-slot POST; optional Xianyu detail adds 1. | `CreateRentalView.vue:419-451,490-518,653-685`; mobile store `gantt.ts:147-225`. Watch is not debounced, so sequential field changes can repeat slot queries. |
| Mobile booking successful submit | **5**: duplicate 1 + logistics 1 + create 1 + automatic Gantt reload 1 + confirmation rental 1 | `CreateRentalView.vue:520-635`; mobile store `gantt.ts:227-250`. |
| Desktop edit open | Normally **2** (latest rental + accessories), but current immediate rental watcher plus visible watcher can run `initForm()` twice, yielding **up to 4** | `EditRentalDialogNew.vue:556-674`. Main devices are local. Device selector focus adds **D** conflict requests (`:539-553`); accessory focus adds one find-slot (`:439-487`). |
| Desktop edit successful submit | **21**: logistics 1 + PUT 1 + store Gantt reload 1 + parent Gantt reload 1 + daily stats 16 + confirmation rental 1 | `EditRentalDialogNew.vue:324-369`; store `gantt.ts:328-347`; parent `GanttChart.vue:871-888`. |
| Mobile edit open/submit | Open warm: **2** (accessories + rental); cold: **3** including Gantt. Submit unchanged schedule: **3** (PUT + Gantt reload + confirmation); changed schedule: **4** with logistics estimate. | `EditRentalView.vue:549-570,749-818,838-880`; mobile store `gantt.ts:252-270`. Device change adds 1 conflict request. Tracking buttons call nonexistent `GET /api/shipping/track/<no>` (`EditRentalView.vue:725-746`), so a runtime trace should record 404 rather than count it as working SF tracking. |
| Desktop search | Gantt keyword filtering is local: **0**. Customer-history search: **1** debounced GET, then **1** detail GET on selection. | `GanttChart.vue:665-676`; `CustomerHistoryDialog.vue:115-150`. Customer backend can fetch 500/200 candidates and lazily load device models (`customer_api.py:61-195`). |
| Mobile search | General rental search: **1** POST after 400 ms; customer-history search: **1** GET after 300 ms + **1** detail GET on selection | `SearchView.vue:81-128`; `CustomerHistoryView.vue:115-159`. Rental pagination performs count+select and `to_dict` lazy traversal (`rental_service.py:91-133`). |
| Desktop batch shipping | Preview: **1** GET. Schedule: **1** POST then **1** refresh GET. Express change: **1** PATCH. Print: **1** synchronous POST. | Preview backend adds one previous-rental query per `R` (`rental_handlers.py:649-731`). Schedule calls SF create-order up to `R` times before one DB commit (`shipping_batch_handlers.py:52-188`). Print outbound calls per rental are approximately SF cloud-print 1 + PDF download 1 + Kuaimai `P` pages + optional slip 1 (`waybill_print_service.py:28-297`). Frontend: `BatchShippingView.vue:309-390,404-488`. |
| Mobile batch shipping | Mount/query: **1** GET. Schedule: **1** POST + **1** refresh GET. Print: **1** POST. | Same backend amplification as desktop. `frontend-mobile/src/views/BatchShippingView.vue:211-280`. |
| Desktop SF tracking | Mount/date change: **1** list GET. Single view: **1** provider-backed POST. Batch refresh: **1** POST containing all visible tracking numbers. | List lazily reads device/model (`sf_tracking_api.py:58-92`). Batch makes one SF batch request for up to 100 numbers (`SFTrackingView.vue:214-316`; `sf_tracking_service.py:47-60`). There is no dedicated mobile SF-tracking view. |
| Desktop inspection | Create page mount: **0**. Device lookup: **1** GET; submit: **1** POST. Edit mount: **1** GET; save: **1** PUT. Records page mount: **1** GET. | Update performs one SELECT per checklist item (`inspection_service.py:129-145`); list/detail serialization can lazy-load rental/device/items. `InspectionView.vue:85-155`; `InspectionRecordsView.vue:132-161`. There is no mobile inspection implementation. |
| Desktop Xianyu alerts | Mount: snapshot **1** + immediate refresh **1**; then snapshot **1/minute** per open tab. Ignore: **1** POST. | Immediate refresh and server 10-minute job both list provider pages and write global cache (`useXianyuOrderAlerts.ts:35-124`; `GanttChart.vue:1220-1232`). There is no mobile alert implementation. |

### 9.1 Highest-confidence SQL amplification hypotheses

1. Desktop daily statistics is the largest deterministic multiplier:
   `16 * (1 device-list + up to 2 * active-main-device rental queries + ship-out
   reads/lazy relationships)`. Mobile uses 14 rather than 16.
2. Booking conflict check multiplies both HTTP and SQL by `D + A`; the backend does
   not accept a device-id batch.
3. Gantt and rental serialization can turn two base queries into relationship N+1
   through `Device.device_model`, `Rental.device`, `Rental.child_rentals`, and child
   device models.
4. Batch shipping preview adds `R` previous-rental queries after its base/binding
   queries.
5. Inspection update adds one lookup per submitted check item.

These are hypotheses to measure, not substitutes for query-counter output.

## 10. Task 0.3 runtime measurement protocol and validation commands

### 10.1 Required controlled run

For every supported flow in section 9:

1. Record the repository commit/dirty state, deployment image, MySQL version,
   Gunicorn worker settings, row counts, active main/accessory device counts, rentals
   in the tested range, and provider mode.
2. Use production-equivalent MySQL and Nginx. Nginx gzip is enabled for JSON and
   front-end text resources (`docker/nginx/nginx.conf:29-43`); direct Flask tests do
   not measure the production compressed path.
3. Run at least 5 warm-ups and 30 measured samples per client/flow with browser cache
   disabled. Capture both total navigation traffic and the business-API-only subset.
4. Export a HAR per run (or a deterministic Playwright `recordHar` capture) with
   response headers and body/transfer sizes. Isolate the 60-second alert poll or
   label it separately.
5. Attach SQL count, cumulative SQL time, and DB pool checkout count to each request
   using a temporary instrumentation wrapper or equivalent APM. Do not modify
   business code merely to gather the baseline.
6. Report nearest-rank p50/p95 for end-to-end flow duration and per endpoint, plus
   sum of uncompressed response content bytes and transferred/compressed bytes.
7. Use SF/Xianyu sandbox or deterministic mocks for ambiguous provider mutations.
   Physical printing must use a controlled printer/test order and a predeclared
   maximum count. Never obtain p95 by blindly submitting 30 real orders/prints.
8. Mark unsupported mobile flows (SF tracking, inspection, Xianyu alerts) as
   `N/A—no mobile route`, with the static absence search attached; do not fabricate
   zeros.

### 10.2 Non-mutating endpoint and compression probes

```bash
# Direct endpoint timing/bytes; run through Nginx for compression evidence.
curl --compressed -sS -o /dev/null \
  -w 'code=%{http_code} total=%{time_total} downloaded=%{size_download}\n' \
  'http://TARGET/api/gantt/data?start_date=2026-08-01&end_date=2026-08-31'

# Confirm compressed response headers.
curl --compressed -sSI \
  'http://TARGET/api/gantt/daily-stats?date=2026-08-21'

# MySQL connection budget/runtime state; execute with an approved read-only admin.
mysql -NBe "SHOW VARIABLES LIKE 'max_connections'; SHOW GLOBAL STATUS LIKE 'Threads_connected'; SHOW GLOBAL STATUS LIKE 'Max_used_connections';"
```

### 10.3 Temporary SQL/query/checkout instrumentation pattern

The wrapper should be placed outside the repository (for example in a controlled
temporary directory) and import the unmodified app. The following event points are
the required minimum:

```python
from time import perf_counter
from flask import g, has_request_context
from sqlalchemy import event

# Before create_app(), replace scheduler_module.init_scheduler with a no-op in the
# dedicated trace server so measuring a Web flow cannot submit due jobs.

@app.before_request
def phase0_begin():
    g.phase0_sql_count = 0
    g.phase0_sql_ms = 0.0
    g.phase0_checkouts = 0

@event.listens_for(db.engine, "before_cursor_execute")
def phase0_before_sql(conn, cursor, statement, parameters, context, executemany):
    context._phase0_started = perf_counter()
    if has_request_context():
        g.phase0_sql_count += 1

@event.listens_for(db.engine, "after_cursor_execute")
def phase0_after_sql(conn, cursor, statement, parameters, context, executemany):
    if has_request_context():
        g.phase0_sql_ms += (perf_counter() - context._phase0_started) * 1000

@event.listens_for(db.engine.pool, "checkout")
def phase0_checkout(dbapi_connection, connection_record, connection_proxy):
    if has_request_context():
        g.phase0_checkouts += 1

@app.after_request
def phase0_headers(response):
    response.headers["X-Phase0-SQL-Count"] = str(g.phase0_sql_count)
    response.headers["X-Phase0-SQL-Ms"] = f"{g.phase0_sql_ms:.3f}"
    response.headers["X-Phase0-DB-Checkouts"] = str(g.phase0_checkouts)
    return response
```

Do not log SQL parameter values: rentals and provider tables contain customer PII
and credentials/identifiers. Run a separate concurrency test using the real
four-worker configuration to measure peak checked-out connections; a single-worker
trace is only valid for per-request query counts.

### 10.4 HAR fields and result schema

For each HAR entry, retain URL template, method, status, `timings.wait`, total HAR
time, response `content.size` (decoded/uncompressed), response `bodySize`,
`_transferSize` where available, `content.compression`, and the three phase-0 SQL
headers. Aggregate each complete flow as:

| run_id | client | flow | fixture | HTTP total/API | SQL total | checkouts | p50/p95 source duration | decoded bytes | transferred bytes | provider calls | notes |
| --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |

Raw HARs, instrumentation logs, fixture manifest, and the aggregation script must be
stored or linked from this evidence directory before task 0.3 is checked.

## 11. Completion boundary and priority risks

### 11.1 Task 0.1 boundary

This file is the refreshed **repository-static** inventory, not completion evidence
for task 0.1. Before checking the task, attach raw testing and production/default
route maps and record the owner decision for the five exact duplicates, two dynamic
overlaps, and stale/destructive scripts.

The minimum external package is read-only and bounded to:

- identify the deployed WSGI command/image and reverse-proxy routes, listening ports,
  firewall/security-group exposure, and use only non-side-effect probes to confirm
  that SF test is absent from production and whether OCR/print routes are reachable;
- list deployed-host/NAS `cron` and systemd units, CI jobs, and operator runbooks;
- read actual production DB grants and provider account capabilities and map each
  identity to the resources above, without submitting provider operations;
- obtain owner confirmation that no hidden client build or external integration uses
  routes absent from the checked-in desktop/mobile sources, and apply explicit
  “do not run” controls to stale/destructive entry points.

### 11.2 Task 0.3 boundary

Task 0.3 remains fully unchecked because no representative desktop/mobile HARs,
SQL query counters, connection-checkout samples, p50/p95 distributions, or
compressed/uncompressed byte totals were captured in this read-only pass. Section 9
is only the test oracle for detecting unexpected runtime fan-out.

Its minimum runtime package is one representative, production-equivalent MySQL and
Nginx environment with scheduler startup disabled and all mutating provider/print
effects routed to deterministic mocks, sandboxes, or a bounded test device. For every
supported desktop/mobile flow, run the section 10 protocol (at least five warm-ups
and 30 measured samples), retain HAR plus SQL/checkout instrumentation, and report
per-flow/per-endpoint p50/p95 and decoded/transferred bytes. Attach the mobile
unsupported-flow absence proof and the raw artifacts listed in section 10.4.

### 11.3 Priority risks to carry into implementation

| Priority | Risk | Required later control |
| --- | --- | --- |
| P0 | Internal mutation, PII, provider, OCR, and print APIs have no identity/RBAC/tenant gate. | Trusted server session -> membership -> tenant route -> RBAC/state gate on every entry. |
| P0 | Single global schema/account/provider/printer boundary. | Per-tenant schema route and credentials; warehouse/provider execution snapshot and printer binding. |
| P0 | SF/Xianyu/print side effects occur before durable commit/ledger, and local file locks do not cover multiple hosts. | Persistent job/outbox/provider-operation ledger, stable idempotency keys, leases/fencing, and explicit ambiguous-outcome reconciliation. |
| P0 | Repository contains destructive scripts and live-looking/hard-coded credentials or PII-producing exports. | Quarantine/rotate, least-privilege execution roles, encrypted tenant-scoped backup/export, and restore proof. |
| P1 | Desktop Gantt and booking generate deterministic HTTP/SQL fan-out; serializers and batch preview add N+1. | Aggregate APIs, eager/batched loading, query budgets, and connection-budget checks measured by task 0.3. |
| P1 | Route collisions and stale endpoints/scripts make baseline behavior registration-order dependent or nonfunctional. | Freeze route contract, add route-map regression, retire only through approved compatibility tasks. |
| P1 | Local logs and browser/generated outputs mix PII and provider identifiers with no tenant retention policy. | Structured redacted logging, tenant/request correlation, secure output storage and deletion. |
