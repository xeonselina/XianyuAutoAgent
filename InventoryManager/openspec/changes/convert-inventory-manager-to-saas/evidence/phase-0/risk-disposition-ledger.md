# Phase 0 Credential Risk-Disposition Ledger

## Status and authority

- Captured: 2026-08-21 (Asia/Shanghai)
- Decision recorded at: `2026-08-21T15:27:19Z`
- Initial review expiry: `2026-09-20T15:27:19Z`
- Status: **D61 bounded acceptance approved for exactly three legacy credential
  classes; compensating-control evidence remains incomplete**
- Scope: credential classes only; no value, hash, fingerprint, host, account,
  customer, provider payload, or reconstructible secret fragment is recorded

This ledger separates exposure facts from risk acceptance. A lower perceived
likelihood does not erase a remote-history match, and a target-state Core
retirement does not make a credential non-authoritative in the current
application. D61 now records a temporary, informed exception for the existing
legacy database account, default-tenant SF credentials, and existing Kuaimai
credentials only. The project owner explicitly selected a time-bounded
acceptance; because no numeric review interval was specified, this change uses
30 periods of 24 hours as a conservative operating ceiling rather than
attributing that number to the owner. It does not turn an unknown or exposure
into a clean finding, and it does not complete task 0.10 without the required
machine evidence.

The initial D61 window lasts at most 30 periods of 24 hours. Each renewal must be
an explicit project-owner decision based on refreshed scans, network/provider
controls and anomaly records, and may last at most another 30 periods of 24
hours. There is no automatic renewal. Every D61 exception ends no later than the
D64-scheduled first production-scale migration rehearsal start, even if a review
window would otherwise run longer.

## Current ledger

| Risk ID | Credential class and verified fact | Owner statement | Current authority and worst credible impact | Required disposition | Status |
| --- | --- | --- | --- | --- | --- |
| `P0-DB-001` | The active legacy database credential class has an exact match in remote-tracking-reachable Git history. The configured server is private-addressed, but independent security-group/firewall proof is absent; the connected account has global `ALL` and `GRANT OPTION`. | D61 accepts the known legacy exposure temporarily because current access is intended to remain private-network-only. | Still authoritative. The owner accepts that a repository copy plus network foothold could expose or modify the entire legacy database and interfere with migration/backup. | D61 covers only this legacy source account through the current review window and never beyond first rehearsal. It cannot be reused for Core/control/root/backup/provisioner/tenant accounts. External negative probes, grant inventory and anomaly review remain required; replace it with purpose-specific least-privilege identities and revoke it before first rehearsal. | **D61 approved; compensating-control receipts blocked** |
| `P0-SF-001` | Active SF credential classes appear in remote-tracking-reachable current/history blobs and previously tracked logs. Provider-side sender-address restrictions have not been independently attested. | D61 accepts the known exposure temporarily based on the existing sender-address restriction. | Still authoritative. The owner accepts possible unauthorized waybill/order activity, fees or quota depletion, availability disruption, and shipment-information access even if sender address changes are blocked. | D61 covers only the existing default-tenant account through the current review window and never beyond first rehearsal. Attach provider entitlement/address-control and anomaly/billing evidence; do not extend it to future tenants/revisions; rotate/revoke and validate a new encrypted revision before first rehearsal. | **D61 approved; provider-control receipts blocked** |
| `P0-KM-001` | Active Kuaimai application ID/secret/printer classes were present in remote-tracking-reachable `PROJECT_EXPLORATION.md`; active values also occur in local logs. This is not a local-log-only exposure. | After the remote-history fact was reported, D61 accepts this known exposure temporarily rather than treating it as local-log-only. | Still authoritative unless the provider proves otherwise. The owner accepts unauthorized print/API activity, quota/cost, configuration discovery and availability disruption within the credential's provider capabilities. | D61 covers only the existing legacy credential/printer context through the current review window and never beyond first rehearsal. Attach provider capability/anomaly evidence, prohibit reuse for future tenant revisions, and rotate/revoke before first rehearsal. Encrypting the same exposed value is not remediation. | **D61 approved; provider-control receipts blocked** |
| `P0-XY-001` | The active Xianyu credential classes were not found as exact matches in the cached remote-tracking-reachable blobs reviewed; an application identifier appears in local logs. Registry images, CI/release caches, backups, and all external remotes are not yet attested. | No rotation requested if remote code does not contain the credential. | Authority remains active. Conditional non-rotation is supportable only if the complete external artifact scan is clean and local material remains contained. | Inventory/fetch authorized remotes, images, releases, CI caches, NAS/backups, and local logs with a redacted scanner receipt. Any external active-value match invalidates the condition and triggers rotation. Record local retention/disposal and review expiry. | **Condition unproven; remains open** |
| `P0-APPKEY-001` | `SECRET_KEY` and `API_KEY` occur in remote-tracking-reachable history. In the current worktree, `SECRET_KEY` is still a startup requirement and signs Gantt proofs; `API_KEY` is newly loaded from the environment while `/external-api` is still registered, so a configured old value is accepted. | Core may delete both because the approved design no longer needs generic application keys. | Both remain authoritative in the current application. Deploying this worktree with the old `API_KEY` would reactivate the exposed authentication path. | Approved disposition is irreversible contract retirement, not migration into a new credential: migrate Gantt proof to the purpose-separated platform-root domain, remove config/startup/deploy/restore reads, remove `/external-api` and `X-API-Key`, and prove old Cookies/proofs/headers have no authority. Until implemented, rotate if an existing pre-Core deployment continues accepting either value. | **Retirement approved; current containment is blocked** |

## D61 common controls, expiry, and triggers

| Field | Recorded disposition |
| --- | --- |
| Accepted by | Project owner approved a bounded acceptance; the 30-day ceiling is the conservative execution default because no numeric interval was specified |
| Approval time | `2026-08-21T15:27:19Z` decision-record capture |
| Initial expiry | `2026-09-20T15:27:19Z`; no automatic renewal |
| Maximum renewal | 30×24 hours per explicit reviewed decision |
| Absolute operational expiry | Earliest of current review expiry, a forced trigger, or the D64-scheduled first production-scale migration rehearsal start |
| Required refresh | Current/history/image/cache/log scans; DB external negative probe/grants; SF/Kuaimai provider restriction, anomaly, quota/cost and access evidence |
| Accepted impact | The confidentiality, integrity, unauthorized provider action/cost/quota and availability impacts stated in each row |
| Scope exclusions | Xianyu; `SECRET_KEY`/`API_KEY`; platform root key; Core control/root/backup/provisioner/tenant-derived identities; future tenants and new provider revisions |
| Forced termination | Public or unintended network reachability; suspicious DB/provider activity, charge or quota use; new external artifact exact match; repository/staff/host compromise; provider restriction change; missing/failed compensating evidence; missed review |
| Final action | Revoke/rotate all three legacy authorities and use only least-privilege DB identities/new validated encrypted provider revisions before first rehearsal |

## Required acceptance record template

Any future D61 renewal or different still-authoritative credential exception MUST
contain all of the following without including the credential itself:

| Field | Required content |
| --- | --- |
| Risk ID and asset class | Stable ID plus exact credential/account category |
| Exposure fact and reachability | Current/history/log/image/cache scope and evidence run IDs |
| Current authority | Whether and where the credential is still accepted |
| Compensating controls | Machine evidence for network/provider restrictions, monitoring, and least privilege |
| Accepted impact | Explicit worst credible confidentiality, integrity, cost, quota, and availability impact |
| Scope exclusions | Core/control/root/backup/new-tenant accounts or any other prohibited reuse |
| Owner and approval time | Named accountable approver and UTC timestamp |
| Review/expiry | Mandatory next review and exception expiry; no indefinite acceptance |
| Forced-rotation triggers | External artifact match, network exposure, anomaly/billing event, staff/repository compromise, provider-control change, or failed evidence refresh |
| Final retirement point | Cutover/contract milestone at which the old authority is revoked |
| Evidence identity | Commit, image digest, scanner/rule version, run IDs, and restricted evidence URIs |

Missing or expired fields make the acceptance invalid. Evidence must say
`unknown` rather than converting absence of proof into a negative finding. A
renewal cannot change the D61 scope or extend past first rehearsal; either change
requires a new explicit decision.

## Immediate non-code constraint

No current working-tree containment image may be promoted while `Config.API_KEY`
can reactivate `/external-api`. This ledger does not authorize editing the
business code during the specification/evidence phase; it records the condition
for the later implementation and deployment review.
