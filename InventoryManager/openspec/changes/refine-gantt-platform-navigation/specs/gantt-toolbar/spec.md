## ADDED Requirements

### Requirement: Hierarchical schedule actions
The booking schedule toolbar MUST present booking as its single primary action, MUST retain direct access to adding a device, pending returns with its count, and customer history, and MUST place less frequent actions in one consistently labeled overflow menu. The toolbar MUST NOT use different filled colors to give every action equal prominence.

#### Scenario: User scans the schedule toolbar
- **WHEN** an authenticated store member opens the booking schedule
- **THEN** the visible action group contains `预定设备`, `添加设备`, `待归还`, `客户历史`, and `更多操作` in that order

#### Scenario: User opens occasional actions
- **WHEN** the member opens `更多操作`
- **THEN** batch shipping, schedule reordering, refresh, statistics, logistics, relay management, and inspection remain available

### Requirement: Responsive schedule toolbar
The schedule toolbar MUST keep date navigation, current period, and business actions as distinct layout groups and MUST move the action group to a separate row before individual actions wrap at narrower desktop widths.

#### Scenario: Toolbar width is constrained
- **WHEN** the schedule is displayed at laptop or mobile width
- **THEN** the groups reflow without overlapping the Gantt content or rendering a detached menu item

