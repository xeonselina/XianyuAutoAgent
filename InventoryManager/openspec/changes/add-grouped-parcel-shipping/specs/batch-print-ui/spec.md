## ADDED Requirements
### Requirement: Group machines into one parcel
The system SHALL group selected pending main rentals with matching warehouse, shipping day, express type, actual recipient address and phone into one parcel, excluding relay successors.

#### Scenario: Two machines share a recipient
- **WHEN** two compatible machines are scheduled together
- **THEN** one carrier order is created and both rentals persist its waybill atomically
- **AND** both desktop and mobile display their parcel grouping

#### Scenario: Printing a combined parcel
- **WHEN** any member of a confirmed parcel is selected for printing with contents enabled
- **THEN** one address label states the total machine count and each machine gets one numbered contents page
- **AND** machines already bearing different waybills are not merged

### Requirement: Edit start and shipping dates
The system SHALL permit editing a rental's start date and ship-out time, including an individual machine of a multi-machine booking, while preserving date and inventory conflict validation.

#### Scenario: Change one machine's dates
- **WHEN** valid dates are saved
- **THEN** the selected machine and its inventory accessories are updated without changing the other machine or an existing carrier pickup appointment
