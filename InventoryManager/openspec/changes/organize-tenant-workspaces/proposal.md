# Change: Organize tenant workspaces

## Why
The tenant header and schedule toolbar mix schedule, inventory, statistics, and shipping actions in one place. This makes the Gantt page visually dense and leaves device administration without a dedicated workflow. The missing-order alert also exposes synchronization failures that are not actionable for a tenant user.

## What Changes
- Add four primary tenant workspaces: schedule, device management, statistics, and receiving/shipping.
- Keep only booking, customer history, refresh, schedule reorder, and pending returns in the schedule workspace.
- Add a device management page for listing, searching, adding, editing, moving, and safely deleting devices.
- Add a receiving/shipping landing page for batch shipping, inspection, relay shipping, and logistics tracking.
- Compress the tenant identity, warehouse selector, primary navigation, and account menu into a single 42-pixel header.
- Hide the missing-order alert unless at least one order actually needs manual entry.

## Impact
- Affected specs: `tenant-workspace-navigation`, `device-management`, `xianyu-order-alert`
- Affected code: tenant header, router, Gantt toolbar and rows, device APIs, new tenant views, focused tests
