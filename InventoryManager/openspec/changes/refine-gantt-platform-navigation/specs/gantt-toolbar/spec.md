## ADDED Requirements

### Requirement: Hierarchical schedule actions
The booking schedule toolbar MUST present booking as its single primary action, MUST retain direct access to pending returns with its count, and MUST place less frequent actions in one consistently labeled overflow menu. At wide desktop widths, adding a device and customer history MUST remain direct secondary actions. The toolbar MUST NOT use different filled colors to give every action equal prominence.

#### Scenario: User scans the schedule toolbar
- **WHEN** an authenticated store member opens the booking schedule
- **THEN** the visible action group contains `预定设备`, `添加设备`, `待归还`, `客户历史`, and `更多操作` in that order

#### Scenario: User opens occasional actions
- **WHEN** the member opens `更多操作`
- **THEN** batch shipping, schedule reordering, refresh, statistics, logistics, relay management, and inspection remain available

#### Scenario: Secondary actions collapse at constrained width
- **WHEN** the schedule width is at most 1280 pixels
- **THEN** `添加设备` and `客户历史` move into `更多操作` while `预定设备` and `待归还` remain directly visible

### Requirement: Responsive schedule toolbar
The schedule toolbar MUST keep date navigation, current period, and business actions within one compact command bar at laptop widths. The current period MUST use a shorter date range when space is constrained, and very narrow screens MUST preserve the single-row height with horizontal overflow instead of wrapping individual actions.

#### Scenario: Toolbar width is constrained
- **WHEN** the schedule is displayed at laptop or mobile width
- **THEN** the command bar remains one row without overlapping the Gantt content or rendering a detached menu item
