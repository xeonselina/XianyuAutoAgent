# Tasks: Show Gantt Schedule Conflicts

## Frontend Tasks

### Task 1: Add conflict detection logic to GanttRow component
- [x] Open `frontend/src/components/GanttRow.vue`
- [x] Define `ConflictInfo` interface with fields:
  - `hasConflict: boolean`
  - `nextRentalId?: number`
  - `dayGap?: number`
  - `currentDestination?: string`
  - `nextDestination?: string`
- [x] Add `rentalConflicts` computed property that:
  - Filters out cancelled rentals (`status !== 'cancelled'`)
  - Sorts rentals by `start_date` ascending using dayjs
  - Iterates through consecutive rental pairs
  - Calculates day gap: `dayjs(next.start_date).diff(dayjs(current.end_date), 'day')`
  - Checks location requirement: `!(current.destination?.includes('广东') || next.destination?.includes('广东'))`
  - Creates conflict info when `dayGap <= 4 && locationConflict`
  - Returns `Map<rentalId, ConflictInfo>`

**Validation:**
- Function correctly identifies conflicts
- Sorting is stable and deterministic
- Edge cases handled (null destination, same-day turnaround)

### Task 2: Add warning icon to rental bar template
- [x] In `GanttRow.vue` template, locate the rental-period bar div
- [x] Add conflict warning icon element after `.rental-content`:
  ```vue
  <span
    v-if="rentalConflicts.get(rental.id)?.hasConflict"
    class="conflict-warning-icon"
    @click.stop="showConflictDetails(rental)"
  >
    ⚠️
  </span>
  ```
- [x] Ensure `.rental-bar` has `position: relative` for absolute positioning (kept as absolute, icon uses absolute positioning within)
- [x] Add CSS for `.conflict-warning-icon`:
  - `position: absolute`
  - `top: 2px; right: 2px`
  - `font-size: 16px`
  - `cursor: pointer`
  - `z-index: 10`
  - `filter: drop-shadow(0 0 2px rgba(255, 193, 7, 0.6))`
  - `transition: transform 0.2s`
- [x] Add hover styles:
  - `transform: scale(1.2)`
  - `filter: drop-shadow(0 0 4px rgba(255, 193, 7, 0.9))`

**Validation:**
- Icon appears on conflicting rentals
- Icon positioned correctly in top-right corner
- Icon does not overlap customer name or phone
- Hover effect is smooth

### Task 3: Implement conflict details click handler
- [x] Add `showConflictDetails` method to GanttRow component:
  - Accepts `rental` parameter
  - Retrieves conflict info from `rentalConflicts` Map
  - Triggers tooltip display with rental and conflict info
- [x] Ensure `@click.stop` prevents event bubbling to parent
- [x] Test that clicking icon shows tooltip but doesn't open edit dialog

**Validation:**
- Click event properly stops propagation
- Tooltip shows conflict details
- Edit dialog does NOT open on icon click

### Task 4: Update RentalTooltip to display conflict information
- [x] Open `frontend/src/components/RentalTooltip.vue`
- [x] Add `conflictInfo` prop to component Props interface:
  ```typescript
  interface Props {
    rental: Rental | null
    visible: boolean
    triggerRef: HTMLElement | undefined
    conflictInfo?: ConflictInfo  // New optional prop
  }
  ```
- [x] Add conflict warning section to tooltip template:
  ```vue
  <div v-if="conflictInfo?.hasConflict" class="conflict-warning-section">
    <div class="warning-header">⚠️ 档期冲突警告</div>
    <div class="warning-details">
      <p>下一个租赁距离本次结束仅 {{ conflictInfo.dayGap }} 天</p>
      <p>目的地: {{ conflictInfo.currentDestination || '未知' }} → {{ conflictInfo.nextDestination || '未知' }}</p>
      <p class="warning-suggestion">建议调整档期或确认物流时效</p>
    </div>
  </div>
  ```
- [x] Add CSS styles for conflict warning section:
  - `.conflict-warning-section`: `margin-top: 8px`, `padding: 8px`, `border-radius: 4px`, `background-color: #FFF9E6`, `border: 1px solid #FFC107`
  - `.warning-header`: `font-weight: 600`, `color: #FF6F00`, `margin-bottom: 4px`
  - `.warning-details p`: `margin: 4px 0`, `font-size: 13px`
  - `.warning-suggestion`: `color: #E65100`, `font-style: italic`

**Validation:**
- Conflict warning section displays correctly
- Text is readable with good contrast
- Layout doesn't break with long destination names
- Warning section only shows when conflict exists

### Task 5: Pass conflict info to tooltip component
- [x] In `GanttRow.vue`, update tooltip component usage
- [x] Add computed property to get current rental's conflict info:
  ```typescript
  const currentRentalConflictInfo = computed(() => {
    if (!hoveredRental.value) return undefined
    return rentalConflicts.value.get(hoveredRental.value.id)
  })
  ```
- [x] Pass `conflictInfo` prop to `RentalTooltip`:
  ```vue
  <RentalTooltip
    :rental="hoveredRental"
    :visible="tooltipVisible"
    :trigger-ref="tooltipTriggerRef"
    :conflict-info="currentRentalConflictInfo"
    @tooltip-enter="handleTooltipEnter"
    @tooltip-leave="handleTooltipLeave"
  />
  ```

**Validation:**
- Tooltip receives correct conflict info for hovered rental
- Tooltip updates when hovering different rentals
- No errors when hovering rentals without conflicts

## Testing Tasks

### Task 6: Manual testing - Conflict detection accuracy
- [ ] Create test scenario 1: Two rentals 2 days apart, both to non-Guangdong destinations
  - Rental A: `end_date = today`, `destination = "北京市"`
  - Rental B: `start_date = today + 2 days`, `destination = "上海市"`
  - **Expected**: Warning icon on Rental A
- [ ] Create test scenario 2: Two rentals 2 days apart, both to Guangdong
  - Rental A: `end_date = today`, `destination = "广东省广州市"`
  - Rental B: `start_date = today + 2 days`, `destination = "广东省深圳市"`
  - **Expected**: NO warning icon
- [ ] Create test scenario 3: Two rentals 6 days apart, non-Guangdong destinations
  - Rental A: `end_date = today`, `destination = "北京市"`
  - Rental B: `start_date = today + 6 days`, `destination = "上海市"`
  - **Expected**: NO warning icon (gap > 4 days)
- [ ] Create test scenario 4: One Guangdong, one not, 3 days apart
  - Rental A: `end_date = today`, `destination = "广东省广州市"`
  - Rental B: `start_date = today + 3 days`, `destination = "北京市"`
  - **Expected**: Warning icon on Rental A

**Pass Criteria:**
- All scenarios produce expected results
- Conflict logic matches specification exactly

### Task 7: Manual testing - Visual display and interactions
- [ ] Verify warning icon appears in top-right corner of rental bar
- [ ] Verify icon size is appropriate (16px, clearly visible)
- [ ] Verify yellow glow effect is visible but not overwhelming
- [ ] Test hover interaction:
  - Icon scales to 120% smoothly
  - Glow effect intensifies
  - Cursor changes to pointer
- [ ] Test click interaction:
  - Clicking icon shows tooltip
  - Clicking icon does NOT open edit dialog
  - Tooltip displays conflict details correctly

**Pass Criteria:**
- Icon is easy to spot when scanning the Gantt chart
- Interactions are intuitive and responsive
- No visual glitches or layout issues

### Task 8: Manual testing - Tooltip content
- [ ] Hover over a rental with conflict warning
- [ ] Verify tooltip shows:
  - "⚠️ 档期冲突警告" header
  - Day gap value (e.g., "仅 2 天")
  - Both destinations (current → next)
  - Suggestion text
- [ ] Verify tooltip styling:
  - Light yellow background (#FFF9E6)
  - Dark orange text for emphasis
  - Good readability
- [ ] Test with long destination names (e.g., "广东省深圳市南山区科技园...")
  - Verify text wraps properly
  - No overflow or truncation issues

**Pass Criteria:**
- All conflict information is displayed accurately
- Tooltip is readable and well-formatted
- Long text handles gracefully

### Task 9: Manual testing - Edge cases
- [ ] Test with rental where `destination = null`
  - **Expected**: Treated as NOT containing "广东", conflict applies
- [ ] Test with rental where `destination = ""`
  - **Expected**: Treated as NOT containing "广东", conflict applies
- [ ] Test with same-day turnaround (gap = 0 days)
  - **Expected**: Shows conflict if location requirement met
- [ ] Test with cancelled rental in sequence
  - **Expected**: Cancelled rental ignored, no conflict shown
- [ ] Test with only one rental for a device
  - **Expected**: No conflict (no consecutive pair)

**Pass Criteria:**
- All edge cases handled correctly
- No JavaScript errors in console
- System behavior matches specification

### Task 10: Manual testing - Performance
- [ ] Create device with 20 rentals
- [ ] Navigate through different weeks in Gantt chart
- [ ] Observe rendering performance:
  - No noticeable lag when scrolling
  - Conflict icons appear immediately
  - Tooltip shows without delay
- [ ] Check browser console for warnings
- [ ] Use browser DevTools Performance tab to profile:
  - Conflict detection should take < 10ms for 20 rentals

**Pass Criteria:**
- Gantt chart remains responsive
- No performance degradation compared to baseline
- Conflict detection completes in < 50ms for 100 rentals

### Task 11: Manual testing - Multiple devices and conflicts
- [ ] Create Gantt chart with 5 devices, each having 2-3 rentals
- [ ] Set up conflicts on 2-3 devices
- [ ] Verify:
  - Correct devices show warning icons
  - Tooltips show correct destination info for each conflict
  - No cross-contamination of conflict data between devices
- [ ] Edit a rental to resolve conflict (change date or destination)
- [ ] Verify warning icon disappears after save

**Pass Criteria:**
- Conflicts are device-specific and isolated
- Editing rental updates conflict status correctly
- No stale or incorrect warnings

## Documentation Tasks

### Task 12: Update user documentation (if exists)
- [ ] Check if there's user documentation for Gantt chart usage
- [ ] If docs exist, add section explaining:
  - What the ⚠️ warning icon means
  - Conflict detection rules (4 days, non-Guangdong)
  - How to resolve conflicts (adjust dates or confirm logistics)
- [ ] If no docs exist, skip this task

**Pass Criteria:**
- Documentation reflects new warning feature
- OR: Skip if no user docs exist

## Completion Checklist

Before marking this change as complete:
- [x] All frontend tasks completed
- [ ] Conflict detection logic tested and verified (requires manual testing)
- [ ] Warning icons display correctly in all scenarios (requires manual testing)
- [ ] Tooltip shows accurate conflict information (requires manual testing)
- [ ] All edge cases handled properly (requires manual testing)
- [ ] No console errors or warnings (requires manual testing)
- [ ] Performance meets requirements (< 50ms for 100 rentals) (requires manual testing)
- [x] Code follows project conventions
- [ ] Manual testing covers all scenarios (requires user to perform Tasks 6-11)
