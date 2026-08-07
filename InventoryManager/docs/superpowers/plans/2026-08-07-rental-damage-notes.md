# Rental Damage Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store one current customer-reported damage note on a rental and make inspection staff explicitly handle it.

**Architecture:** Add a nullable `damage_note` column to `Rental` as the single source of truth, expose it through existing rental serialization and update APIs, and derive a default-unchecked inspection item from it. Extend both rental editors and the existing responsive inspection UI without adding a separate workflow or state table.

**Tech Stack:** Flask 3, SQLAlchemy/Flask-Migrate, pytest, Vue 3, TypeScript, Element Plus, Vant, Pinia, Vitest, Playwright.

## Global Constraints

- Damage notes are trimmed strings of at most 1000 characters; blank input is stored as `NULL`.
- Only one current note is stored; no change history or repair workflow is introduced.
- Existing rental creation screens remain unchanged.
- Desktop and mobile rental editing MUST both support the field.
- Inspection completion MUST NOT clear the rental note.
- Existing unrelated worktree changes and untracked `.superpowers` files must remain untouched.

---

### Task 1: Persist and validate rental damage notes

**Files:**
- Create: `migrations/versions/20260807_add_rental_damage_notes.py`
- Modify: `app/models/rental.py`
- Modify: `app/handlers/rental_handlers.py`
- Test: `tests/integration/test_rental_damage_notes.py`

**Interfaces:**
- Consumes: `PUT /web/rentals/<rental_id>` and `Rental.to_dict()`.
- Produces: nullable `Rental.damage_note: str | None` and JSON field `damage_note`.

- [ ] **Step 1: Write failing serialization and update tests**

Create integration tests that seed a main rental, assert `GET /api/rentals/<id>` returns `damage_note: null`, then update with `"  屏幕右下角碎裂  "` and assert the persisted/API value is `"屏幕右下角碎裂"`. Add cases for whitespace clearing, a numeric value, and 1001 characters; invalid requests must return 400 and preserve the previous value.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest tests/integration/test_rental_damage_notes.py -v`

Expected: failures because the model field and handler validation do not exist.

- [ ] **Step 3: Add the migration and model serialization**

Add a nullable `sa.Text()` migration column and matching model column:

```python
damage_note = db.Column(
    db.Text,
    nullable=True,
    comment='客户反馈的当前设备损坏备注',
)
```

Add `'damage_note': self.damage_note` to `Rental.to_dict()`.

- [ ] **Step 4: Add update validation before mutations**

Normalize the optional payload value before updating any rental fields:

```python
if 'damage_note' in data:
    raw_damage_note = data['damage_note']
    if raw_damage_note is not None and not isinstance(raw_damage_note, str):
        return bad_request('损坏备注必须是字符串或 null')
    normalized_damage_note = raw_damage_note.strip() if raw_damage_note else None
    if normalized_damage_note and len(normalized_damage_note) > 1000:
        return bad_request('损坏备注不能超过 1000 个字符')
    data['damage_note'] = normalized_damage_note
```

Assign `rental.damage_note` before the existing status commit path and include the field in the success response.

- [ ] **Step 5: Run the focused tests**

Run: `pytest tests/integration/test_rental_damage_notes.py -v`

Expected: all cases pass.

### Task 2: Derive an inspection task and preserve its snapshot

**Files:**
- Modify: `app/services/checklist_generator.py`
- Modify: `app/models/inspection_check_item.py`
- Modify: `migrations/versions/20260807_add_rental_damage_notes.py`
- Test: `tests/unit/test_checklist_generator.py`
- Test: `tests/integration/test_rental_damage_notes.py`

**Interfaces:**
- Consumes: `Rental.damage_note`.
- Produces: checklist item `{name: str, order: int, default_checked: bool}` for damage reports; submitted item text persists in `inspection_check_item.item_name`.

- [ ] **Step 1: Write failing checklist and snapshot tests**

Assert a rental without a note has the unchanged base checklist. Assert `damage_note="屏幕右下角碎裂"` appends the final item `处理用户反馈：屏幕右下角碎裂` with `default_checked is False`. Submit the generated items to `POST /api/inspections`, update/clear the rental note, and assert the saved inspection item text remains unchanged.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `pytest tests/unit/test_checklist_generator.py tests/integration/test_rental_damage_notes.py -v`

Expected: damage item assertions fail.

- [ ] **Step 3: Implement checklist derivation and safe storage length**

Append after all existing conditional items:

```python
if rental.damage_note:
    checklist.append({
        'name': f'处理用户反馈：{rental.damage_note}',
        'order': order_counter,
        'default_checked': False,
    })
```

Update `calculate_expected_count()`. Expand `inspection_check_item.item_name` to `String(1020)` through model and migration so a 1000-character note plus prefix is never truncated.

- [ ] **Step 4: Run focused backend tests**

Run: `pytest tests/unit/test_checklist_generator.py tests/integration/test_rental_damage_notes.py -v`

Expected: all cases pass, including the stored snapshot.

### Task 3: Show damage state and default-unchecked handling in inspection UI

**Files:**
- Modify: `frontend/src/types/inspection.ts`
- Modify: `frontend/src/stores/inspection.ts`
- Modify: `frontend/src/components/inspection/RentalInfoCard.vue`
- Modify: `frontend/src/types/rental.ts`
- Create: `frontend/tests/unit/components/InspectionDamageNote.spec.ts`
- Create: `frontend/tests/unit/stores/inspection-damage-note.spec.ts`

**Interfaces:**
- Consumes: `Rental.damage_note?: string | null` and `ChecklistItem.default_checked?: boolean`.
- Produces: danger alert and `CheckItem.is_checked` initialized from `default_checked ?? true`.

- [ ] **Step 1: Write failing component and store tests**

Mount `RentalInfoCard` with a non-empty note and assert both `用户反馈设备可能损坏` and the full text render; mount with `null` and assert the alert is absent. Mock the latest-rental API with one regular item and one damage item and assert the store initializes them to `true` and `false` respectively.

- [ ] **Step 2: Run focused frontend tests and confirm failure**

Run: `npm --prefix frontend run test:run -- tests/unit/components/InspectionDamageNote.spec.ts tests/unit/stores/inspection-damage-note.spec.ts`

Expected: alert and default-state assertions fail.

- [ ] **Step 3: Implement types, initialization, and alert**

Add `damage_note?: string | null` to `Rental`, `default_checked?: boolean` to `ChecklistItem`, and initialize both lookup paths with:

```ts
is_checked: item.default_checked ?? true
```

Render an `el-alert` above the descriptions only when `rental.damage_note` is non-empty, using danger/error styling, a non-closable state, and a description containing the full note.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm --prefix frontend run test:run -- tests/unit/components/InspectionDamageNote.spec.ts tests/unit/stores/inspection-damage-note.spec.ts`

Expected: all tests pass.

### Task 4: Edit damage notes on desktop

**Files:**
- Modify: `frontend/src/components/rental/EditRentalDialogNew.vue`
- Modify: `frontend/src/stores/gantt.ts`
- Modify: `frontend/src/types/rental.ts`
- Create: `frontend/tests/unit/components/EditRentalDamageNote.spec.ts`

**Interfaces:**
- Consumes: API rental `damage_note`.
- Produces: update payload `{damage_note: string}` and desktop multiline editor limited to 1000 characters.

- [ ] **Step 1: Write a failing editor test**

Mount the dialog with `damage_note="屏幕右下角碎裂"`, assert the textarea and danger warning show the value, edit it, submit, and assert `ganttStore.updateRental()` receives the edited `damage_note`.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `npm --prefix frontend run test:run -- tests/unit/components/EditRentalDamageNote.spec.ts`

Expected: the damage editor cannot be found.

- [ ] **Step 3: Implement desktop editing**

Add `damageNote: ''` to local form state, hydrate it in `initForm()` from `rentalData.damage_note || ''`, and submit it as `damage_note`. Add a dedicated divider, `el-input type="textarea"`, `maxlength="1000"`, `show-word-limit`, and a non-closable danger alert when `form.damageNote.trim()` is non-empty.

- [ ] **Step 4: Run the focused test**

Run: `npm --prefix frontend run test:run -- tests/unit/components/EditRentalDamageNote.spec.ts`

Expected: pass.

### Task 5: Edit damage notes on mobile

**Files:**
- Modify: `frontend-mobile/src/stores/gantt.ts`
- Modify: `frontend-mobile/src/views/EditRentalView.vue`
- Modify: `frontend-mobile/e2e/edit-rental.spec.ts`

**Interfaces:**
- Consumes: mobile `Rental.damage_note?: string | null`.
- Produces: mobile update payload `{damage_note: string}` and Vant textarea limited to 1000 characters.

- [ ] **Step 1: Extend the mobile E2E mock and write the failing scenario**

Return `damage_note="屏幕右下角碎裂"` from the rental mock, open the edit route, assert the warning and textarea value, replace it with `镜头卡口松动`, save, and assert the intercepted PUT body contains that exact `damage_note`.

- [ ] **Step 2: Run the focused mobile test and confirm failure**

Run: `npm --prefix frontend-mobile run test:e2e -- e2e/edit-rental.spec.ts`

Expected: the field and warning are absent.

- [ ] **Step 3: Implement mobile editing**

Add `damage_note` to the mobile rental type, `damageNote: ''` to form state, hydrate from the loaded rental, and submit `damage_note: form.damageNote`. Render a Vant danger notice and `van-field type="textarea" rows="3" maxlength="1000" show-word-limit autosize` in a dedicated damage-feedback group.

- [ ] **Step 4: Run the focused mobile test**

Run: `npm --prefix frontend-mobile run test:e2e -- e2e/edit-rental.spec.ts`

Expected: pass.

### Task 6: Full verification and specification completion

**Files:**
- Modify: `openspec/changes/add-rental-damage-notes/tasks.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified feature with an accurate completed checklist.

- [ ] **Step 1: Run backend verification**

Run: `pytest tests/unit/test_checklist_generator.py tests/integration/test_rental_damage_notes.py tests/integration/test_rental_api.py -v`

Expected: all pass.

- [ ] **Step 2: Run desktop verification**

Run: `npm --prefix frontend run test:run`

Run: `npm --prefix frontend run build`

Expected: tests and build pass.

- [ ] **Step 3: Run mobile verification**

Run: `npm --prefix frontend-mobile run test:e2e -- e2e/edit-rental.spec.ts`

Run: `npm --prefix frontend-mobile run build`

Expected: focused E2E and build pass.

- [ ] **Step 4: Validate migration and OpenSpec**

Run: `flask db heads`

Run: `openspec validate add-rental-damage-notes --strict`

Expected: one valid migration head and valid OpenSpec output.

- [ ] **Step 5: Update the OpenSpec task checklist**

Mark only completed and verified items `- [x]`; leave any unverified item unchecked with an explanatory note.
