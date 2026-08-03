# Gantt Alert Scroll Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Gantt rentals viewport scrollable through its final row when the missing-Xianyu-order alert appears, expands, or collapses.

**Architecture:** Replace competing viewport/minimum-height rules with one continuous flex height chain from `GanttView` to `.gantt-body`. Observe `.gantt-body` size changes and synchronize the virtual list from the element's current `clientHeight` and `scrollTop`, so alert-driven layout changes cannot leave a stale visible range.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript, CSS Flexbox, browser `ResizeObserver`, Pinia, Vue Test Utils, Vitest.

## Global Constraints

- The single-line alert, expanded alert details, and collapsed alert must all leave the Gantt vertically scrollable through the final device row.
- Preserve horizontal scrolling, the sticky Gantt header, existing filtering, rental data, and the fixed 44px virtual-row height.
- Do not add another page-level vertical scrolling container.
- Do not change Xianyu alert query behavior or copy.
- Do not add a frontend dependency.

---

### Task 1: Synchronize the virtual viewport after alert-driven resizing

**Files:**
- Modify: `InventoryManager/frontend/tests/unit/components/GanttPendingReturnsFlow.spec.ts`
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue:481-708,1209-1213`

**Interfaces:**
- Consumes: the existing `.gantt-body` element referenced by `ganttBodyRef`, the existing `itemHeight = 44`, and `filteredDevices`.
- Produces: a `ResizeObserver` owned by `GanttChart` that calls `updateVisibleRange()` whenever `.gantt-body` changes size and is disconnected during unmount.
- Produces: `updateVisibleRange()` derives both viewport height and current scroll position directly from `.gantt-body`, then clamps `startIndex` so the last viewport stays filled through the final device.

- [ ] **Step 1: Add controllable ResizeObserver state to the component test**

Add `type Device` to the Gantt store import and place the following test state near the existing hoisted axios mocks:

```ts
let resizeCallback: ResizeObserverCallback | undefined
const observeGanttBody = vi.fn()
const disconnectGanttBody = vi.fn()

class ResizeObserverStub {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback
  }

  observe = observeGanttBody
  unobserve = vi.fn()
  disconnect = disconnectGanttBody
}

const makeDevices = (): Device[] => Array.from({ length: 20 }, (_, index) => ({
  id: index + 1,
  name: `测试设备 ${index + 1}`,
  serial_number: `SN-${index + 1}`,
  model: '测试型号',
  is_accessory: false,
  lifecycle_status: 'active',
  created_at: '2026-08-03T00:00:00',
  updated_at: '2026-08-03T00:00:00',
}))
```

In `beforeEach`, reset the spies and install the stub before mounting:

```ts
resizeCallback = undefined
observeGanttBody.mockClear()
disconnectGanttBody.mockClear()
vi.stubGlobal('ResizeObserver', ResizeObserverStub)
```

In `afterEach`, add:

```ts
vi.unstubAllGlobals()
```

Change `mountGantt` to accept `devices: Device[] = []` and assign
`store.devices = devices` before `shallowMount`.

- [ ] **Step 2: Write the failing resize regression test**

Add this test to `GanttChart pending-returns flow`:

```ts
it('keeps the final rows rendered when the alert changes the viewport height', async () => {
  const { wrapper } = await mountGantt(makeDevices())
  const body = wrapper.get('.gantt-body').element as HTMLElement

  Object.defineProperty(body, 'clientHeight', {
    configurable: true,
    value: 88,
  })
  Object.defineProperty(body, 'scrollTop', {
    configurable: true,
    writable: true,
    value: 0,
  })

  expect(resizeCallback).toBeTypeOf('function')
  resizeCallback?.([], {} as ResizeObserver)
  await wrapper.vm.$nextTick()

  expect(wrapper.findAllComponents({ name: 'GanttRow' })).toHaveLength(4)

  body.scrollTop = (20 * 44) - 88
  body.dispatchEvent(new Event('scroll'))
  await wrapper.vm.$nextTick()

  Object.defineProperty(body, 'clientHeight', {
    configurable: true,
    value: 440,
  })
  body.scrollTop = (20 * 44) - 440
  resizeCallback?.([], {} as ResizeObserver)
  await wrapper.vm.$nextTick()

  const renderedRows = wrapper.findAllComponents({ name: 'GanttRow' })
  expect(renderedRows).toHaveLength(12)
  expect(renderedRows.at(-1)?.props('device').id).toBe(20)
})
```

This catches removal of the observer, reading a stale reactive `scrollTop`, or failing to clamp the final virtual viewport.

- [ ] **Step 3: Write the failing observer cleanup test**

```ts
it('disconnects the Gantt viewport observer when unmounted', async () => {
  const { wrapper } = await mountGantt(makeDevices())

  expect(observeGanttBody).toHaveBeenCalledWith(
    wrapper.get('.gantt-body').element,
  )

  wrapper.unmount()

  expect(disconnectGanttBody).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 4: Run the tests and verify the RED state**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/components/GanttPendingReturnsFlow.spec.ts
```

Expected: both new tests fail because current production code never constructs or disconnects a `ResizeObserver`; the first failure reports that `resizeCallback` is `undefined`.

- [ ] **Step 5: Implement the minimal virtual viewport synchronization**

In `GanttChart.vue`, add observer ownership beside the other virtual-scroll state:

```ts
let ganttBodyResizeObserver: ResizeObserver | null = null
```

Replace the virtual-scroll methods with:

```ts
const updateVisibleRange = () => {
  const container = ganttBodyRef.value
  if (!container) return

  const containerHeight = container.clientHeight
  scrollTop.value = container.scrollTop
  visibleCount.value = Math.ceil(containerHeight / itemHeight) + 2

  const requestedStartIndex = Math.floor(scrollTop.value / itemHeight)
  const maxStartIndex = Math.max(
    0,
    filteredDevices.value.length - visibleCount.value,
  )
  startIndex.value = Math.min(requestedStartIndex, maxStartIndex)
  endIndex.value = Math.min(
    startIndex.value + visibleCount.value,
    filteredDevices.value.length,
  )
}

const handleScroll = () => {
  updateVisibleRange()
}

const observeGanttBodyResize = () => {
  const container = ganttBodyRef.value
  if (!container || typeof ResizeObserver === 'undefined') return

  ganttBodyResizeObserver = new ResizeObserver(() => {
    updateVisibleRange()
  })
  ganttBodyResizeObserver.observe(container)
}

const initVirtualScroll = async () => {
  await nextTick()
  if (ganttBodyRef.value) {
    ganttBodyRef.value.addEventListener('scroll', handleScroll)
    updateVisibleRange()
    observeGanttBodyResize()
  }
}
```

Extend `onUnmounted` after removing the scroll listener:

```ts
ganttBodyResizeObserver?.disconnect()
ganttBodyResizeObserver = null
```

- [ ] **Step 6: Run the focused tests and verify the GREEN state**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/components/GanttPendingReturnsFlow.spec.ts
```

Expected: all tests in the file pass, including 12 rows after the simulated viewport growth and one observer disconnect on unmount.

- [ ] **Step 7: Commit the virtual viewport change**

```bash
git add InventoryManager/frontend/src/components/GanttChart.vue \
  InventoryManager/frontend/tests/unit/components/GanttPendingReturnsFlow.spec.ts
git commit -m "fix: sync gantt virtual viewport on resize"
```

---

### Task 2: Make the Gantt body consume the true remaining page height

**Files:**
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue:1227-1234,1253-1262,1417-1434`
- Modify: `InventoryManager/frontend/src/components/XianyuOrderAlertBar.vue:151-158`

**Interfaces:**
- Consumes: `GanttView.vue`'s existing `height: 100vh; overflow: hidden` page boundary.
- Produces: one flex height chain where fixed controls and the alert use natural height, `.gantt-main` receives all remaining height, `.gantt-body` is the only vertical scrollbar, and `.gantt-scroll-container` remains the horizontal scrollbar.

- [ ] **Step 1: Record the layout RED state in a real browser**

With the current build and one visible missing-order alert, verify these user-visible failures before editing CSS:

1. Scroll `.gantt-body` to its maximum `scrollTop`.
2. Confirm the last device row remains below or clipped by the `.gantt-view` bottom edge.
3. Expand the alert details and confirm the available Gantt viewport does not shrink cleanly.
4. Record the `.gantt-view`, `.gantt-main`, and `.gantt-body` bounding rectangles from browser developer tools so the clipped boundary is explicit.

Expected: the Gantt content extends beyond the fixed `.gantt-view` because `.gantt-container` and `.gantt-body` enforce their own viewport/minimum heights.

- [ ] **Step 2: Replace the competing height rules with the approved flex chain**

In `GanttChart.vue`, replace the affected style rules with:

```css
.gantt-container {
  padding: 20px;
  height: 100%;
  min-height: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: white;
}

.toolbar,
.filters {
  flex: 0 0 auto;
}

.gantt-main {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  overflow: hidden;
  border: 2px solid #c0c0c0;
  border-radius: 8px;
  background: white;
  width: 100%;
}

.gantt-scroll-container {
  width: 100%;
  min-height: 0;
  flex: 1 1 auto;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow-x: auto;
  overflow-y: hidden;
}

.gantt-body {
  min-height: 0;
  width: fit-content;
  min-width: 100%;
  flex: 1 1 auto;
  position: relative;
  overflow-y: auto;
  overflow-x: visible;
}
```

In `XianyuOrderAlertBar.vue`, keep the alert at its natural height inside the parent flex column:

```css
.xianyu-alert-bar {
  flex: 0 0 auto;
  margin: 0 16px 12px;
  padding: 12px 16px;
  color: #7a271a;
  background: #fef0f0;
  border: 1px solid #fab6b6;
  border-radius: 6px;
}
```

- [ ] **Step 3: Verify the layout GREEN state in the real browser**

Repeat the Step 1 checks in all three states: alert summary visible, details expanded, and details collapsed.

Expected in every state:

- `.gantt-main` and `.gantt-body` remain within the `.gantt-view` bottom edge.
- The Gantt body height changes when the alert height changes.
- Scrolling `.gantt-body` to its maximum shows the complete final device row.
- The page itself does not acquire a second vertical scrollbar or jump.
- Horizontal scrolling and the sticky header still work.

- [ ] **Step 4: Run related tests, type checking, and production build**

```bash
cd InventoryManager/frontend
npm run test:run -- \
  tests/unit/components/GanttPendingReturnsFlow.spec.ts \
  tests/unit/components/GanttRentalConfirmationFlow.spec.ts \
  tests/unit/components/XianyuOrderAlertBar.spec.ts
npm run type-check
build_dir="$(mktemp -d /tmp/xianyu-gantt-alert-build.XXXXXX)"
npx vite build --outDir "$build_dir" --emptyOutDir
```

Expected: all related tests pass, type checking exits 0, and Vite completes the temporary production build without modifying tracked static build output.

- [ ] **Step 5: Run the complete frontend suite**

```bash
cd InventoryManager/frontend
npm run test:run
```

Expected: all frontend test files and tests pass.

- [ ] **Step 6: Check scope and commit the layout fix**

```bash
git diff --check
git status --short
git add InventoryManager/frontend/src/components/GanttChart.vue \
  InventoryManager/frontend/src/components/XianyuOrderAlertBar.vue
git commit -m "fix: keep gantt scrollable below alerts"
```

Confirm that existing `InventoryManager/static/vue-dist`,
`InventoryManager/static/vue-mobile-dist`, and
`ai_kefu/xianyu_provider/upstream` working-tree changes remain unstaged.
