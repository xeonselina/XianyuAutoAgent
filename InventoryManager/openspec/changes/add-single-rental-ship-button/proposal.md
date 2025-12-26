# Proposal: Add Single Rental Ship Button

## Overview
Add a "发货" (Ship) button to the single rental edit dialog that syncs the tracking number to Xianyu using the existing `ship_order` API, similar to batch shipping functionality.

## Why
Users currently need to navigate to the batch shipping page to sync tracking numbers to Xianyu, even when editing a single rental. This creates unnecessary friction in the workflow. By adding a ship button directly in the edit dialog, users can complete the entire rental editing and shipping workflow in one place, improving efficiency and user experience.

## Problem Statement
Currently, users can only sync tracking numbers to Xianyu through the batch shipping interface. When editing a single rental record, there is no convenient way to trigger Xianyu shipping synchronization without navigating to the batch shipping page.

## Proposed Solution
Add a "发货到闲鱼" button in the `RentalActionButtons` component that:
1. Validates the rental has both `xianyu_order_no` and `ship_out_tracking_no`
2. Calls a new backend API endpoint `/api/rentals/{rental_id}/ship-to-xianyu`
3. The backend uses the existing `XianyuOrderService.ship_order()` method
4. Updates rental status to `shipped` if not already shipped
5. Provides user feedback on success/failure

## Benefits
- Faster workflow for single-rental shipping operations
- Consistent UX with batch shipping (same API, same validation)
- No need to navigate away from edit dialog to sync with Xianyu

## Scope
**In Scope:**
- Frontend: Add ship button to `RentalActionButtons.vue`
- Backend: Create new API endpoint for single rental shipping
- Reuse existing `XianyuOrderService.ship_order()` method
- Update rental status to `shipped` on success

**Out of Scope:**
- Modifying existing batch shipping functionality
- Adding new Xianyu API methods
- Changing the ship_order API contract

## Success Criteria
1. Ship button appears in rental edit dialog
2. Button is disabled when rental lacks required fields
3. Clicking button successfully syncs tracking number to Xianyu
4. User receives clear success/error feedback
5. Rental status updates to `shipped` after successful sync

## Dependencies
- Existing `XianyuOrderService.ship_order()` method (already implemented)
- Rental must have `xianyu_order_no` and `ship_out_tracking_no`

## Risks & Mitigations
**Risk:** Button could be clicked multiple times causing duplicate API calls
**Mitigation:** Disable button during API call with loading state

**Risk:** User might not understand difference between saving rental and shipping to Xianyu
**Mitigation:** Use clear button label "发货到闲鱼" and show confirmation message

## Related Changes
- Uses same API as `simplify-batch-shipping-flow` change
- Complements existing batch shipping workflow
