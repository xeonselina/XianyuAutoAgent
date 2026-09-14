## Context
The Gantt toolbar currently uses a fixed three-column Element Plus row with eight colorful actions in the right column. At ordinary laptop widths these actions wrap independently and the overflow menu visually collides with its refresh item. Platform store creation already has secure backend support but needs clearer presentation and discovery.

## Goals / Non-Goals
- Goals: reduce toolbar competition, preserve fast access to frequent work, support responsive layouts, and make platform onboarding understandable.
- Non-Goals: change any booking, shipping, return, statistics, or platform authentication behavior.

## Decisions
- `预定设备` remains the only primary-colored schedule action.
- `添加设备`, `待归还`, and `客户历史` remain direct secondary actions on wide screens; constrained screens keep `待归还` visible and move the other two into overflow.
- All less frequent actions use one `更多操作` menu in this order: operational work, schedule tools, then secondary business pages.
- The fixed row/column toolbar is replaced by a compact responsive command bar. At laptop width it abbreviates the period and collapses secondary actions instead of adding a second row; very narrow screens use horizontal overflow.
- The platform screen uses summary cards, a focused onboarding panel, and Chinese lifecycle labels while retaining all existing secure API behavior and test selectors.

## Risks / Trade-offs
- Batch shipping and schedule reordering require one extra click. Their lower frequency and higher operational impact justify that cost.
- A visible platform-login link exposes no new capability; authentication still requires the independent platform password and TOTP session.
