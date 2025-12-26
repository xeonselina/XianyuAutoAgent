# Proposal: Show Gantt Schedule Conflicts

## Overview
Add visual conflict warnings (⚠️ yellow warning icon) to the Gantt chart to highlight tight scheduling situations where rentals have insufficient turnaround time between consecutive bookings for non-local destinations.

## Why
Currently, users cannot easily identify scheduling conflicts where consecutive rentals have tight timelines. When a device needs to be shipped back from one customer and then sent to another customer within a short timeframe (≤4 days), and at least one destination is outside Guangdong province, there's a risk of delays and customer dissatisfaction. By visually highlighting these conflicts in the Gantt chart, users can proactively identify and resolve scheduling issues before they become problems.

## Problem Statement
The Gantt chart displays rental periods and shipping timelines, but doesn't warn users when consecutive rentals have insufficient turnaround time. Specifically:

- If Rental B starts ≤4 days after Rental A ends (based on `end_date` to `start_date`)
- AND at least one of the rentals has a destination (`destination` field) that doesn't contain "广东"
- This creates a scheduling conflict that should be visually highlighted

Without this warning, users may accidentally create tight schedules that are difficult to fulfill, especially when devices need to be shipped long distances.

## Proposed Solution
Add conflict detection logic to the Gantt chart that:

1. **Detects conflicts** for each device's rental sequence:
   - For each rental, check if the next rental on the same device starts ≤4 days after the current rental ends
   - Check if either rental's `destination` field does NOT contain "广东"
   - If both conditions are true, mark this as a conflict

2. **Visual indicators**:
   - Add a yellow ⚠️ warning icon at the **end** of the rental bar (棕色 rental period bar)
   - Position the icon in the top-right corner of the rental bar
   - The icon should be clickable to show conflict details in the tooltip

3. **Tooltip enhancement**:
   - When hovering over a rental with a conflict warning, the tooltip should show:
     - "⚠️ 档期冲突警告"
     - "下一个租赁距离本次结束仅 X 天"
     - "目的地: [current destination] → [next destination]"
     - Recommendation: "建议调整档期或确认物流时效"

## Conflict Detection Rules

**A conflict exists when ALL of the following are true:**

1. **Time Gap**: `next_rental.start_date - current_rental.end_date ≤ 4 days`
2. **Location Requirement**: `!current_rental.destination.includes('广东') OR !next_rental.destination.includes('广东')`
3. **Same Device**: Both rentals are for the same `device_id`
4. **Sequential Rentals**: The rentals are consecutive (no other rentals between them on the timeline)

**Important Notes:**
- The comparison is based on `start_date` and `end_date` (not `ship_out_time` or `ship_in_time`)
- If destination is `null` or empty, treat it as NOT containing "广东"
- Only show the warning on the **earlier** rental in the conflict pair
- Cancelled rentals should be excluded from conflict detection

## Benefits
- **Proactive Risk Management**: Identify scheduling issues before they cause problems
- **Improved Customer Service**: Avoid delays by ensuring adequate turnaround time
- **Visual Clarity**: Users can quickly scan the Gantt chart for yellow warnings
- **Informed Decision Making**: Users can adjust schedules or confirm logistics feasibility

## Scope

**In Scope:**
- Frontend: Conflict detection logic in `GanttRow.vue`
- Frontend: Visual warning icon (⚠️) display on rental bars
- Frontend: Enhanced tooltip to show conflict details
- Frontend: CSS styling for warning icon positioning

**Out of Scope:**
- Backend API changes (all logic is frontend-based)
- Automatic conflict resolution or suggestions
- Email/notification alerts for conflicts
- Conflict detection for accessory rentals
- Historical conflict tracking or reporting

## Success Criteria
1. Yellow ⚠️ icon appears on rentals with scheduling conflicts
2. Icon is positioned at the end of the rental bar (top-right corner)
3. Tooltip shows conflict details when hovering
4. Conflict detection correctly identifies 4-day gaps with non-Guangdong destinations
5. No performance degradation in Gantt chart rendering
6. Warning icons do not overlap with other UI elements

## Dependencies
- Existing Gantt chart rendering logic (`GanttRow.vue`)
- Existing tooltip component (`RentalTooltip.vue`)
- Rental data includes `destination` field

## Risks & Mitigations

**Risk**: Performance impact when calculating conflicts for many rentals
**Mitigation**:
- Cache conflict detection results per device
- Only recalculate when rental data changes
- Use efficient sorting and comparison algorithms

**Risk**: Warning icon might be too small or hard to see
**Mitigation**:
- Use appropriate icon size (16px-20px)
- Add subtle yellow glow/shadow for visibility
- Ensure icon has sufficient contrast with bar background

**Risk**: Users might not understand what "广东" means in the conflict rule
**Mitigation**:
- Provide clear tooltip explanation
- Document the conflict detection rules in user help/docs (if they exist)

## Related Changes
- None - this is a standalone visual enhancement to the Gantt chart

## Technical Notes
- Conflict detection should run on the **sorted list** of rentals for each device
- Sort by `start_date` ascending to ensure proper sequencing
- Consider edge cases:
  - Same-day rentals (gap = 0 days)
  - Null/empty destination fields
  - Overlapping rentals (should not show conflict warning)
