# Change: Refine Gantt actions and platform store management

## Why
The booking schedule toolbar presents many equally prominent colored controls, causing wrapping and making frequent actions hard to distinguish. The platform store onboarding workflow also needs a clear, discoverable management page rather than appearing as a technical tenant list.

## What Changes
- Keep booking as the single primary schedule action and show only frequent device, return, and customer actions beside it.
- Move batch shipping, schedule reordering, refresh, and secondary business destinations into one consistently labeled overflow menu.
- Present the platform tenant screen as a customer-store management dashboard with summary counts and a clearly explained first-administrator creation form.
- Add a low-emphasis super-administrator entry on the store login page while keeping platform authentication independent.

## Impact
- Affected specs: `gantt-toolbar`, `platform-store-management`
- Affected code: Gantt toolbar, tenant and platform login views, platform store view, frontend tests

