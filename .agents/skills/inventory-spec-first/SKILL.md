---
name: inventory-spec-first
description: Use for InventoryManager behavior changes and bug fixes. Define or check the OpenSpec behavior before editing implementation; do not apply to other monorepo projects.
---

# InventoryManager spec-first workflow

Use this skill only for `InventoryManager/`. The repository contains unrelated projects; follow the routing and archive exclusions in the repository and subproject `AGENTS.md` files.

1. Read `InventoryManager/docs/INDEX.md` to locate the affected domain. Read its current `InventoryManager/openspec/specs/<capability>/spec.md` and relevant active changes. Treat `openspec/specs/` as deployed behavior and `openspec/changes/` as proposed behavior. Do not use `docs/archive/` as a source.
2. Before editing application code, state the requested observable behavior as OpenSpec `Requirement` and `Scenario` entries. For a new or changed behavior, write a delta under `openspec/changes/<change-id>/specs/<capability>/spec.md` following `InventoryManager/openspec/AGENTS.md`. For an undocumented existing behavior or regression boundary, add a scenario to the current capability spec first. If a current scenario already says exactly what the fix requires, cite it and avoid a duplicate edit.
3. Specify the user action, expected result, rejection or failure behavior, and data effects. Include PC/mobile, tenant or warehouse scope, and nearby rental or inventory flows when they are affected. Keep planned behavior out of the current spec until it is implemented and promoted through the OpenSpec lifecycle.
4. Implement against those scenarios. Add or update tests that observe the behavior and check relevant neighboring flows. Validate the spec with `openspec validate <item> --strict`; run the affected backend and frontend checks before delivery. Before deployment, run the applicable broader regression suite and follow `InventoryManager/DEPLOY.md`.
5. In the final report, identify the spec changed, the behavior verified, tests run, and any important scenarios still lacking automated coverage. A passing spec validator checks format; it does not prove runtime behavior.

Do not create a new proposal for a fix that merely restores an already specified behavior. Use existing user authorization to continue implementation; this workflow does not add a separate approval requirement.
