## ADDED Requirements

### Requirement: Separate the control plane from tenant business databases

The system MUST store platform-wide identity, tenant registry, subscription, routing, job, recovery, and audit state in `inventory_control`, while each tenant SHALL have its own business database and tenant-scoped database accounts even when all schemas initially share one MySQL instance.

#### Scenario: A new tenant is provisioned
- **WHEN** a registration attempt reaches database provisioning
- **THEN** the system SHALL allocate a new immutable tenant UUID and database UUID, create a distinct business schema, and register its instance key and database name in the control plane
- **AND** the system SHALL NOT place that tenant's inventory, rental, shipment, inspection, relay, or tenant audit rows in another tenant's schema or in shared business tables distinguished only by `tenant_id`

#### Scenario: The first production tenant is migrated
- **WHEN** the existing business schema is registered as the default tenant during the approved migration
- **THEN** the system SHALL keep that schema in place and register it as one tenant database rather than copying all business rows into a shared multi-tenant schema

### Requirement: Resolve tenant routes only from trusted server context

The system MUST derive a tenant database route from a server-verified tenant user session or an explicitly trusted background-job context, and SHALL NOT accept a client-supplied tenant identifier, database name, connection URL, or `USE <database>` instruction as routing authority.

#### Scenario: An authenticated browser request reaches a business API
- **WHEN** the control plane validates the opaque session, user auth version, unique active membership, and effective tenant gate
- **THEN** the router SHALL use the membership's immutable tenant UUID to resolve `database_instance_key + database_name`
- **AND** any `tenant_id`, database name, or connection value supplied in the URL, query, headers, or body SHALL be ignored or rejected

#### Scenario: A worker enters tenant scope
- **WHEN** a worker claims a job containing a server-issued tenant UUID and access version
- **THEN** it SHALL establish an explicit tenant context and validate the current route and database identity before using the tenant ORM

### Requirement: Verify immutable database identity at connection boundaries

Every tenant business database MUST contain exactly one immutable `database_identity` record with the tenant UUID, database UUID, creation time, and schema generation, and every DML or platform-read route SHALL verify that identity against trusted control-plane metadata.

#### Scenario: A pooled connection targets the expected schema
- **WHEN** an engine is first created, a connection is checked out, or an inactive cached engine is reactivated
- **THEN** the router SHALL verify the schema's `database_identity` and expected schema generation before executing business SQL

#### Scenario: A route or pool points at the wrong database
- **WHEN** the observed tenant UUID, database UUID, or required schema generation does not match the trusted route
- **THEN** the system SHALL fail closed, invalidate the affected connection or engine, execute no tenant query, and emit a security signal

### Requirement: Enforce database-level least privilege

The system MUST use separate least-privilege credentials for control-plane application access, each tenant's DML access, each tenant's platform SELECT-only access, and migration/provisioning operations; ordinary Web and worker processes SHALL NOT possess database creation, grant, cross-schema, or platform-read-to-DML fallback privileges.

#### Scenario: Tenant application code accesses its business database
- **WHEN** Web or worker code opens the DML route for a trusted tenant
- **THEN** the MySQL account SHALL be limited to the required DML operations on that tenant schema and SHALL be denied access to every other tenant schema

#### Scenario: A platform administrator reads tenant business data
- **WHEN** an authorized platform read route selects a trusted tenant
- **THEN** it SHALL use that tenant's distinct SELECT/SHOW VIEW-only account with read-only transactions, bounded query time, and forced pagination
- **AND** the route SHALL NOT borrow or expose the tenant DML engine

#### Scenario: A provisioning operation needs DDL
- **WHEN** a schema, database account, grant, or migration must be created or changed
- **THEN** only the isolated migration/provisioning identity SHALL perform the operation

### Requirement: Derive tenant database passwords with purpose-separated versioned metadata

The system MUST derive tenant DML and platform-read database passwords from the active 256-bit platform root key using HKDF-SHA256 with distinct fixed domains, immutable database identity, account-specific credential generation, root-key version, and derivation version; derived passwords SHALL NOT be stored in the control plane, job payloads, logs, errors, or connection strings exposed outside process memory.

#### Scenario: Both account kinds are derived for one tenant database
- **WHEN** the provisioner derives generation 1 credentials for DML and platform-read access
- **THEN** it SHALL use `inventory-manager/tenant-db-password/v1` and `inventory-manager/platform-read-db-password/v1` respectively
- **AND** the resulting 32-byte, unpadded Base64URL passwords SHALL differ even though the tenant and database UUIDs are the same

#### Scenario: Root-key metadata is unavailable or inconsistent
- **WHEN** the route references an unknown root-key version, a missing key file, a mismatched key fingerprint, or unsupported derivation metadata
- **THEN** startup or route creation SHALL fail closed without trying other key files until one happens to work

### Requirement: Keep routing engines bounded, versioned, and purpose-specific

The routing layer MUST use bounded per-tenant connection pools and a bounded engine cache whose identity includes account kind, database UUID, username, credential generation, root-key version, derivation version, and route version; it SHALL actively retire stale engines when routing, access, login-state, or credential versions change.

#### Scenario: A cached DML engine is considered for reuse
- **WHEN** any component of its complete routing identity differs from current control-plane metadata
- **THEN** the router SHALL reject reuse, close or drain that engine, and build a connection only from the current published route

#### Scenario: A tenant is fenced or its credentials rotate
- **WHEN** suspension, deletion, recovery hold, migration, or account rotation advances the applicable route or access version
- **THEN** new checkouts through stale engines SHALL stop immediately and existing connections SHALL be drained according to the persisted barrier state

### Requirement: Publish tenant routes only after provisioning proof

The provisioner MUST keep a tenant database route non-public and non-ready until the schema is migrated, immutable identity is written, DML and platform-read grants pass positive and negative smoke tests, and the expected schema generation is recorded.

#### Scenario: All provisioning checks pass
- **WHEN** the latest tenant migration, identity match, permitted-operation tests, and cross-schema denial tests succeed under the applicable lease and advisory lock
- **THEN** the control plane SHALL atomically publish the versioned route as ready for the registration final transaction

#### Scenario: Any provisioning check fails
- **WHEN** migration, identity, grant, positive-connectivity, or cross-schema-denial verification fails
- **THEN** the route SHALL remain unpublished and unavailable to normal Web, worker, and platform-read traffic

### Requirement: Rotate database accounts through persisted fenced generations

The system MUST rotate DML and platform-read accounts by creating and verifying unpublished next-generation accounts, atomically switching the complete route tuple, draining the old generation, and only then revoking it; account mutations SHALL use persisted rotation state, fencing leases, and per-database MySQL advisory locks rather than in-place password changes.

#### Scenario: A normal credential rotation succeeds
- **WHEN** the next account generation has passed identity, permission, and cross-schema tests
- **THEN** the router SHALL atomically publish its username, credential generation, root-key version, derivation version, and route version before draining and revoking the old account

#### Scenario: Both account kinds are rotated
- **WHEN** one operation coordinates DML and platform-read accounts
- **THEN** lease acquisition, advisory locks, and final route changes SHALL use the fixed `dml` then `platform_read` order

#### Scenario: Rotation crashes before its final compare-and-swap
- **WHEN** a candidate account was created but the expected fencing token or route version no longer matches
- **THEN** the reconciler SHALL keep the published account in its prior safe state and lock or revoke the unpublished candidate before releasing the advisory lock

### Requirement: Preserve tenant identity outside database rows

All tenant-scoped cache keys, temporary-file paths, logs, jobs, platform links, and cross-database resource references MUST include the immutable tenant UUID in addition to resource type and local resource identifier; a resource UUID or repeated integer primary key SHALL NOT by itself authorize or select a tenant.

#### Scenario: Two tenant schemas contain the same local rental ID
- **WHEN** the system creates a log correlation, job reference, temporary output, or platform link for either rental
- **THEN** it SHALL namespace the reference by the trusted tenant UUID so the two resources cannot collide or be fetched through the other tenant's route

