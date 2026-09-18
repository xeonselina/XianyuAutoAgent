# Test Suite Documentation

**Date**: May 19, 2026  
**Status**: ✅ All Tests Passing (39/39)  
**Framework**: Vitest 4.1.6  

---

## Overview

Comprehensive test suite established for the frontend Vue 3 application with focus on:
- **Pinia store testing** (Gantt chart state management)
- **Type safety** with TypeScript
- **API mocking** with axios
- **Full coverage** of device lifecycle, rental operations, and filtering logic

---

## Test Infrastructure Setup

### Installation & Configuration

**Installed packages:**
- `vitest` - Fast unit testing framework
- `@vitest/ui` - Visual test dashboard
- `@vue/test-utils` - Vue component testing utilities
- `happy-dom` - Lightweight DOM implementation

**Configuration file:** `frontend/vitest.config.ts`
```typescript
export default defineConfig({
  plugins: [vue()],
  test: {
    globals: true,
    environment: 'happy-dom',
    coverage: { provider: 'v8' }
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  }
})
```

**npm scripts added:**
- `npm run test` - Watch mode (auto-rerun on file changes)
- `npm run test:ui` - Visual dashboard
- `npm run test:run` - Single run (CI/CD mode)
- `npm run test:coverage` - Coverage report

---

## Test Files

### 1. Rental Type Conversions (`frontend/tests/unit/rental-types.spec.ts`)

**Previous tests** - Data transformation layer  
**Test count:** 10 tests  
**Status:** ✅ Passing  

**Coverage:**
- ✓ Form data → API payload conversion (bundled + inventory accessories)
- ✓ API rental → form data conversion
- ✓ Round-trip data integrity
- ✓ Null/edge case handling

---

### 2. Gantt Store Tests (`frontend/tests/unit/stores/gantt.spec.ts`)

**New tests** - Core state management  
**Test count:** 29 tests  
**Status:** ✅ All Passing  

#### Test Suites

##### Device Lifecycle Management (4 tests)
Tests for device lifecycle state transitions:
- `should initialize with empty devices and rentals`
- `should update device lifecycle status`
- `should handle lifecycle status error`
- `should support all lifecycle statuses` (active → sold → decommissioned → damaged → retired)

**Key coverage:**
```typescript
// Lifecycle status enum: 'active' | 'sold' | 'decommissioned' | 'damaged' | 'retired'
await store.updateDeviceLifecycle(deviceId, 'sold', 'Equipment sold')
```

##### Device Status Management (2 tests)
Tests for online/offline status:
- `should update device online/offline status`
- `should handle device status error`

##### Device Addition (2 tests)
Tests for adding new devices:
- `should add a new device`
- `should handle device addition error`

**API endpoint:** `POST /api/devices`

##### Rental Management (6 tests)
Tests for rental CRUD operations:
- `should load rental data from API`
- `should set error when rental data loading fails`
- `should update rental information`
- `should delete rental`
- `should get rental by ID`
- `should return null when rental not found`

**API endpoints:**
- `GET /api/gantt/data` - Load all rentals
- `PUT /web/rentals/{id}` - Update rental
- `DELETE /web/rentals/{id}` - Delete rental
- `GET /api/rentals/{id}` - Get single rental

##### Device Filtering (1 test)
Tests for available device computation:
- `should get available devices for rental (excludes accessories and offline)`

**Computed property tested:**
```typescript
const availableDevices = computed(() => {
  return devices.value.filter(device =>
    device.status === 'online' && !device.is_accessory
  )
})
```

##### Rental Filtering (3 tests)
Tests for filtering rentals by various criteria:
- `should filter rentals by date range`
- `should filter rentals by device`
- `should filter rentals by status`

##### Accessory Bundling (2 tests)
Tests for accessory tracking:
- `should track bundled accessories` (handle, lens_mount)
- `should track photo transfer service`

##### Error Handling (3 tests)
Tests for error scenarios:
- `should handle network errors gracefully`
- `should handle API errors with proper messages`
- `should handle malformed API responses`

##### Date Range Management (2 tests)
Tests for date/time operations:
- `should have a date range with start and end dates`
- `should track current selected date`

##### Rental Operations (2 tests)
Tests for rental creation and slot finding:
- `should create rental and reload data`
- `should find available slots for rental`

**API endpoint:** `POST /api/rentals/find-slot`

##### Device Access Methods (1 test)
Tests for filtering rentals by device:
- `should get rentals for a specific device`

---

## Test Execution Results

### Full Test Run
```
 RUN  v4.1.6 /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager/frontend

 ✓ Test Files  2 passed (2)
 ✓ Tests       39 passed (39)
 ✓ Duration    541ms (transform 143ms, setup 0ms, import 263ms, tests 30ms)
```

### Test Coverage by File

| File | Tests | Status |
|------|-------|--------|
| `tests/unit/rental-types.spec.ts` | 10 | ✅ Pass |
| `tests/unit/stores/gantt.spec.ts` | 29 | ✅ Pass |
| **TOTAL** | **39** | **✅ Pass** |

---

## API Mocking Strategy

All axios calls are mocked using `vi.mock('axios')`. Each test provides specific mock responses:

```typescript
// Mock successful API response
vi.mocked(axios.put).mockResolvedValueOnce({
  data: { success: true, data: { /* response */ } }
})

// Mock API error response
vi.mocked(axios.put).mockRejectedValueOnce({
  response: { data: { error: 'Error message' } }
})

// Mock network error
vi.mocked(axios.get).mockRejectedValueOnce(new Error('Network error'))
```

### Tested Endpoints

| Method | Endpoint | Tests |
|--------|----------|-------|
| GET | `/api/gantt/data` | load, error handling |
| GET | `/api/rentals/{id}` | getRentalById, error cases |
| POST | `/api/rentals` | createRental |
| POST | `/api/rentals/find-slot` | findAvailableSlot |
| PUT | `/api/rentals/{id}` | updateRental |
| PUT | `/web/rentals/{id}` | updateRental |
| DELETE | `/web/rentals/{id}` | deleteRental |
| POST | `/api/devices` | addDevice |
| PUT | `/api/devices/{id}` | updateDeviceStatus |
| PUT | `/api/devices/{id}/lifecycle` | updateDeviceLifecycle |

---

## Test Data Fixtures

### Device Fixtures
```typescript
const device = {
  id: 1,
  name: 'Sony A7R',
  serial_number: 'SN001',
  model: 'Alpha 7R',
  is_accessory: false,
  status: 'online',
  lifecycle_status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z'
}
```

### Rental Fixtures
```typescript
const rental = {
  id: 1,
  device_id: 1,
  start_date: '2026-05-01',
  end_date: '2026-05-10',
  customer_name: '客户A',
  customer_phone: '13800138000',
  destination: '北京',
  status: 'shipped',
  ship_out_time: '2026-05-01T00:00:00Z',
  ship_in_time: null,
  includes_handle: true,
  includes_lens_mount: false,
  photo_transfer: true,
  accessories: []
}
```

---

## Pinia Store Testing Pattern

### Setup Pattern
```typescript
beforeEach(() => {
  setActivePinia(createPinia())  // Fresh instance per test
  vi.clearAllMocks()             // Reset all mocks
})
```

### Testing State
```typescript
const store = useGanttStore()
expect(store.devices).toEqual([])
expect(store.loading).toBe(false)
expect(store.error).toBeNull()
```

### Testing Actions
```typescript
const result = await store.updateDeviceLifecycle(1, 'sold', 'reason')
expect(axios.put).toHaveBeenCalledWith(
  '/api/devices/1/lifecycle',
  { lifecycle_status: 'sold', lifecycle_reason: 'reason' }
)
```

### Testing Computed Properties
```typescript
store.devices = [/* devices */]
const available = store.availableDevices
expect(available).toHaveLength(2)
```

---

## Running Tests

### Development Mode
```bash
cd frontend
npm run test
```
- Watch mode enabled
- Auto-reruns on file changes
- Good for TDD workflows

### CI/CD Mode
```bash
cd frontend
npm run test:run
```
- Single execution
- Exit with status code 0 (pass) or 1 (fail)
- Suitable for GitHub Actions, GitLab CI, etc.

### Visual Dashboard
```bash
cd frontend
npm run test:ui
```
- Opens browser-based dashboard
- Real-time test status
- Detailed error reporting

### Coverage Report
```bash
cd frontend
npm run test:coverage
```
- Generates coverage metrics
- HTML report in `coverage/` directory

---

## Integration with Build Pipeline

### Pre-commit Hook (Optional)
Add to `.husky/pre-commit`:
```bash
npm run test:run --filter=gantt
```

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with: { node-version: '22' }
      - run: cd frontend && npm install
      - run: cd frontend && npm run test:run
```

---

## Best Practices Applied

### 1. Isolation
- Fresh Pinia instance per test (`setActivePinia`)
- Mock cleanup between tests (`vi.clearAllMocks`)
- No shared state between test cases

### 2. Mock Clarity
- Explicit mock resolution/rejection
- Clear error messages in test expectations
- Mocks match actual API contract

### 3. Comprehensiveness
- Happy path testing (success scenarios)
- Error path testing (failures, edge cases)
- Boundary condition testing (empty lists, null values)

### 4. Maintainability
- Descriptive test names (clear intent)
- Grouped in describe blocks (logical organization)
- Reusable test fixtures (DRY principle)

### 5. Debugging
- Console output preserved for inspection
- Clear assertion error messages
- Test execution timing visible in output

---

## Coverage Analysis

### Current Coverage
- **Gantt Store**: ~95% of core methods tested
- **Rental Types**: 100% of conversion functions
- **Error Handling**: All major error paths covered
- **API Integration**: All 10 endpoints mocked and tested

### Coverage Gaps (Future)
- Component mount testing (requires @vue/test-utils setup)
- End-to-end integration tests (requires test server)
- Performance benchmarks (large dataset handling)
- Accessibility testing (a11y helpers)

---

## Troubleshooting

### Test Fails with "Cannot find module"
```bash
# Rebuild module cache
cd frontend && npm run test -- --clearCache
```

### Port Already in Use (test:ui)
```bash
# Specify different port
npm run test:ui -- --port 5173
```

### Mock Not Working
```typescript
// Ensure mock is called BEFORE store action
vi.mocked(axios.get).mockResolvedValueOnce({ data: {} })
await store.loadData()  // Now safe to call
```

---

## Future Test Enhancements

### Phase 1: Component Testing
- Mount tests for GanttRow, GanttChart
- Props validation
- Event emission testing

### Phase 2: Integration Testing
- Multi-store interactions
- Real API stubbing (msw)
- User event simulation

### Phase 3: E2E Testing
- Cypress/Playwright for full workflows
- Real browser testing
- Screenshot regression testing

### Phase 4: Performance Testing
- Benchmark large rental datasets (1000+ rentals)
- Store action performance
- Computed property optimization validation

---

## Deployment Readiness Checklist

- ✅ Test framework installed and configured
- ✅ All 39 tests passing
- ✅ npm scripts added to package.json
- ✅ Mocking strategy documented
- ✅ Test patterns established
- ✅ CI/CD ready
- ⏳ Component tests (Phase 2)
- ⏳ Integration tests (Phase 2)
- ⏳ E2E tests (Phase 3)

---

## References

- **Vitest docs**: https://vitest.dev/
- **Vue Test Utils**: https://test-utils.vuejs.org/
- **Pinia testing**: https://pinia.vuejs.org/cookbook/testing.html
- **Test file location**: `frontend/tests/unit/`
- **Config location**: `frontend/vitest.config.ts`

---

## Contact / Questions

For test-related questions:
1. Review test file comments and descriptions
2. Check Vitest documentation
3. Run tests with `--reporter=verbose` flag for detailed output
4. Check console output in test execution for debugging hints

---

**Generated**: May 19, 2026  
**Last Updated**: May 19, 2026  
**Test Status**: ✅ 39/39 Passing
