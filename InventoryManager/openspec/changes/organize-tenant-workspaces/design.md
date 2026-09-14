# Design

## Navigation model

The tenant header owns four stable destinations. Nested shipping, inspection, relay, and tracking routes keep the receiving/shipping tab active. Schedule actions remain local dialogs or drawers, while inventory mutations live on the device page.

## Device safety

Mutations require a concrete warehouse. Cross-warehouse listing remains available in read-only mode. Deletion requires confirmation and the API refuses deletion when rental history exists. Warehouse moves continue to use the existing signed preview workflow.

## Alert visibility

Synchronization errors remain available to logs and monitoring but are not rendered in the tenant workflow. The visual warning is reserved for a positive count of orders requiring action.
