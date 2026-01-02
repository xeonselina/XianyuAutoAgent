# Design: Show Gantt Schedule Conflicts

## Context
The Gantt chart currently displays rental periods and shipping timelines but lacks visual indicators for scheduling conflicts. Users need to manually calculate turnaround times between consecutive rentals to identify potential logistics issues. This change adds automatic conflict detection and visual warnings directly in the Gantt chart.

## Goals / Non-Goals

**Goals:**
- Automatically detect scheduling conflicts based on time gaps and destination
- Provide clear visual warning indicators in the Gantt chart
- Show helpful conflict details in tooltips
- Maintain Gantt chart rendering performance

**Non-Goals:**
- Prevent users from creating conflicting schedules (warnings only, no blocking)
- Suggest optimal rescheduling (future enhancement)
- Track historical conflicts or generate reports
- Send notifications/alerts about conflicts

## Conflict Detection Algorithm

### Data Flow

```
Rental Data (per device)
    ↓
Sort by start_date ascending
    ↓
For each consecutive rental pair (A, B):
    ↓
Calculate time gap: B.start_date - A.end_date
    ↓
Check location: !(A.destination.includes('广东') OR B.destination.includes('广东'))
    ↓
If gap ≤ 4 days AND location check passes:
    ↓
Mark Rental A as having conflict
Store conflict info: { nextRentalId, dayGap, destinations }
```

### Implementation Details

**1. Conflict Detection Function**

Location: `frontend/src/components/GanttRow.vue`

```typescript
interface ConflictInfo {
  hasConflict: boolean
  nextRentalId?: number
  dayGap?: number
  currentDestination?: string
  nextDestination?: string
}

// Compute conflict info for each rental
const rentalConflicts = computed(() => {
  const conflicts = new Map<number, ConflictInfo>()

  // Sort rentals by start_date for this device
  const sortedRentals = [...props.rentals]
    .filter(r => r.status !== 'cancelled')
    .sort((a, b) => dayjs(a.start_date).diff(dayjs(b.start_date)))

  for (let i = 0; i < sortedRentals.length - 1; i++) {
    const current = sortedRentals[i]
    const next = sortedRentals[i + 1]

    // Calculate day gap
    const endDate = dayjs(current.end_date)
    const nextStartDate = dayjs(next.start_date)
    const dayGap = nextStartDate.diff(endDate, 'day')

    // Check location requirement
    const currentHasGuangdong = current.destination?.includes('广东') ?? false
    const nextHasGuangdong = next.destination?.includes('广东') ?? false
    const locationConflict = !currentHasGuangdong || !nextHasGuangdong

    // Detect conflict
    if (dayGap <= 4 && locationConflict) {
      conflicts.set(current.id, {
        hasConflict: true,
        nextRentalId: next.id,
        dayGap,
        currentDestination: current.destination,
        nextDestination: next.destination
      })
    }
  }

  return conflicts
})
```

**2. Visual Indicator Rendering**

Add warning icon to rental bar template:

```vue
<template>
  <div class="rental-bar rental-period" ...>
    <div class="rental-content">
      <!-- Existing content -->
    </div>

    <!-- Conflict warning icon -->
    <span
      v-if="rentalConflicts.get(rental.id)?.hasConflict"
      class="conflict-warning-icon"
      @click.stop="showConflictDetails(rental)"
    >
      ⚠️
    </span>
  </div>
</template>
```

**3. CSS Styling**

```css
.conflict-warning-icon {
  position: absolute;
  top: 2px;
  right: 2px;
  font-size: 16px;
  cursor: pointer;
  z-index: 10;
  filter: drop-shadow(0 0 2px rgba(255, 193, 7, 0.6));
  transition: transform 0.2s;
}

.conflict-warning-icon:hover {
  transform: scale(1.2);
  filter: drop-shadow(0 0 4px rgba(255, 193, 7, 0.9));
}

.rental-bar {
  position: relative; /* Enable absolute positioning for icon */
}
```

**4. Tooltip Enhancement**

Update `RentalTooltip.vue` to accept and display conflict info:

```typescript
interface Props {
  rental: Rental | null
  visible: boolean
  triggerRef: HTMLElement | undefined
  conflictInfo?: ConflictInfo  // New prop
}

// In tooltip template
<div v-if="conflictInfo?.hasConflict" class="conflict-warning-section">
  <div class="warning-header">⚠️ 档期冲突警告</div>
  <div class="warning-details">
    <p>下一个租赁距离本次结束仅 {{ conflictInfo.dayGap }} 天</p>
    <p>目的地: {{ conflictInfo.currentDestination || '未知' }} → {{ conflictInfo.nextDestination || '未知' }}</p>
    <p class="warning-suggestion">建议调整档期或确认物流时效</p>
  </div>
</div>
```

## Performance Considerations

**Optimization Strategies:**

1. **Memoization**: Cache conflict calculation results
   ```typescript
   const conflictCacheKey = computed(() =>
     props.rentals.map(r => `${r.id}:${r.start_date}:${r.end_date}:${r.destination}`).join('|')
   )
   ```

2. **Efficient Sorting**: Only sort when rental data changes
   - Use `computed` property for reactive updates
   - Avoid sorting on every render

3. **Minimal DOM Updates**: Only show icon when conflict exists
   - Use `v-if` to conditionally render icon
   - Avoid unnecessary style recalculations

**Expected Impact:**
- Conflict detection: O(n log n) for sorting + O(n) for comparison = **O(n log n)** per device
- For typical usage (5-10 rentals per device): negligible performance impact
- For heavy usage (50+ rentals per device): ~10-20ms additional computation time

## Edge Cases

### 1. Null/Empty Destination
**Scenario**: Rental has `destination = null` or `destination = ""`
**Handling**: Treat as NOT containing "广东" → conflict applies
**Rationale**: Missing destination suggests unknown logistics → safer to warn

### 2. Same-Day Turnaround
**Scenario**: `next.start_date = current.end_date` (gap = 0 days)
**Handling**: Show conflict (0 ≤ 4 days)
**Rationale**: Same-day turnaround is high risk for non-local destinations

### 3. Overlapping Rentals
**Scenario**: `next.start_date < current.end_date` (gap < 0 days)
**Handling**: Do NOT show conflict warning (this is a different issue - double booking)
**Rationale**: Overlapping rentals are a more severe problem handled separately

### 4. Cancelled Rentals
**Scenario**: Rental has `status = 'cancelled'`
**Handling**: Exclude from conflict detection entirely
**Rationale**: Cancelled rentals don't affect actual logistics

### 5. Exactly "广东" String Matching
**Scenario**:
- Destination = "广东省广州市" → Contains "广东" ✓
- Destination = "广州市" → Does NOT contain "广东" ✗
- Destination = "广东" → Contains "广东" ✓
**Handling**: Use simple `String.includes('广东')` check
**Rationale**: Users are expected to include province name in full addresses

### 6. Multiple Consecutive Conflicts
**Scenario**: Rental A conflicts with B, B conflicts with C
**Handling**: Show warning on both A and B independently
**Rationale**: Each conflict pair should be highlighted separately

## UI/UX Decisions

### Icon Choice: ⚠️
**Pros:**
- Universally recognized warning symbol
- Yellow color aligns with "caution" semantics
- Available as Unicode emoji (no custom icon needed)

**Alternatives Considered:**
- 🚨 Too severe/alarming
- ⚡ Suggests error rather than warning
- 🔔 Suggests notification rather than conflict

### Icon Positioning: Top-Right Corner
**Rationale:**
- Doesn't overlap with customer name (left side)
- Doesn't interfere with status icons (🚀✅📦)
- Consistent position across all rental bars
- Easy to scan vertically down the Gantt chart

### Click Behavior: Show Details
**Options:**
1. **Icon click shows tooltip** (chosen)
   - Pros: Immediate context, no navigation
   - Cons: Tooltip might block view

2. **Icon click opens rental edit dialog**
   - Pros: Allows immediate fixing
   - Cons: Too aggressive, users may just want to see details

**Decision**: Icon click triggers tooltip hover behavior

### Color Scheme
- **Warning Icon**: Yellow (#FFC107) with subtle glow
- **Tooltip Warning Section**: Light yellow background (#FFF9E6)
- **Warning Text**: Dark orange (#FF6F00) for emphasis

## Data Dependencies

**Required Fields:**
- `rental.id` - Unique identifier
- `rental.start_date` - Rental start date (YYYY-MM-DD format)
- `rental.end_date` - Rental end date (YYYY-MM-DD format)
- `rental.destination` - Delivery destination (string)
- `rental.status` - Rental status (to filter cancelled)
- `rental.device_id` - To group rentals by device

**Optional Fields:**
- `rental.customer_name` - For tooltip display (already used)

## Testing Strategy

### Unit Tests (Not in Scope, but Documented)
1. Test conflict detection with various day gaps (0, 2, 4, 5 days)
2. Test location logic with different destination strings
3. Test edge cases (null destination, cancelled status)
4. Test sorting logic with unsorted input data

### Manual Testing (Included in Tasks)
1. Create two rentals 2 days apart, one to non-Guangdong → Should show warning
2. Create two rentals 2 days apart, both to Guangdong → Should NOT show warning
3. Create two rentals 5 days apart, one to non-Guangdong → Should NOT show warning
4. Verify icon visibility and tooltip content
5. Test icon click behavior

## Migration & Rollout
- No database migrations required
- No configuration changes required
- Feature is purely additive (no breaking changes)
- Can be deployed without feature flag (low risk)

## Open Questions
None - all design decisions have been made based on clear requirements.

## Future Enhancements (Out of Scope)
1. **Configurable Threshold**: Allow users to set custom day gap threshold (currently hardcoded 4 days)
2. **Smart Suggestions**: Recommend alternative time slots to resolve conflicts
3. **Bulk Conflict Resolution**: Tool to automatically adjust multiple conflicting rentals
4. **Conflict Reports**: Export list of all conflicts to Excel/PDF
5. **Location-Aware Thresholds**: Different thresholds for different provinces (e.g., 2 days for Guangdong, 5 days for other provinces)
