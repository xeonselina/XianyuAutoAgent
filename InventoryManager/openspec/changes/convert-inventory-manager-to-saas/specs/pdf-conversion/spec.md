## ADDED Requirements

### Requirement: Isolate PDF conversion artifacts by tenant and print job
The system MUST bind every PDF conversion input, intermediate artifact, output image, and cleanup action to an authorized tenant and immutable print-job context, and MUST prevent artifacts from becoming cross-tenant or publicly addressable resources.

#### Scenario: Convert an authorized job artifact
- **GIVEN** a worker holds a valid lease for a print job owned by tenant A
- **AND** the input PDF reference, label kind, content digest, warehouse snapshot, and job revision match the immutable job payload
- **WHEN** the worker converts the PDF
- **THEN** all temporary files SHALL be created in a private job-specific directory with unpredictable names and least-privilege access
- **AND** outputs SHALL be returned only to the same authorized job pipeline
- **AND** no local path, public URL, PDF token, customer data, or artifact bytes SHALL be written to logs or durable task payloads

#### Scenario: Reject a cross-tenant or stale artifact reference
- **GIVEN** a worker for tenant A receives an input reference owned by tenant B or a digest or job revision that no longer matches
- **WHEN** conversion is attempted
- **THEN** the system SHALL fail closed before reading or converting the artifact
- **AND** the failure SHALL NOT disclose whether the referenced artifact exists for another tenant

#### Scenario: Clean up an isolated conversion workspace
- **GIVEN** conversion succeeds, fails, is cancelled, or the worker lease is lost
- **WHEN** the attempt reaches cleanup or a startup janitor finds the abandoned job workspace
- **THEN** the system SHALL delete only the validated job-specific temporary artifacts
- **AND** it SHALL not follow untrusted paths, symlinks, or identifiers into another job or tenant workspace

#### Scenario: Retry conversion for the same immutable job
- **GIVEN** conversion failed before any Kuaimai submission and the durable job remains retryable
- **WHEN** another worker retries with the same immutable payload and content digest
- **THEN** it SHALL create a fresh isolated temporary workspace
- **AND** it SHALL produce equivalent label content without reusing stale files from the prior attempt
