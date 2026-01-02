# Spec: Single Waybill Print

## Summary

Enables users to print individual waybills for specific rentals directly from the batch shipping page, in addition to the existing batch print functionality.

## ADDED Requirements

### Requirement: The UI MUST display print action for individual rentals

Each rental row in the batch shipping table MUST show a print button when the rental is eligible for printing.

#### Scenario: Show print button for scheduled rental

**GIVEN** a rental with status `'scheduled_for_shipping'`
**AND** the rental has `ship_out_tracking_no = 'SF3261559084017'`
**AND** the rental has `scheduled_ship_time` set
**WHEN** viewing the batch shipping page
**THEN** the rental row should display a "打印" button
**AND** the button should show a printer icon
**AND** the button should be enabled

#### Scenario: Hide print button for ineligible rental

**GIVEN** a rental with status `'not_shipped'`
**AND** the rental does NOT have `ship_out_tracking_no`
**WHEN** viewing the batch shipping page
**THEN** the rental row should NOT display a "打印" button
**OR** the button should be disabled/hidden

### Requirement: The system MUST print single waybill on button click

When the user clicks the print button for a rental, the system MUST send a print job for that single waybill.

#### Scenario: Successfully print single waybill

**GIVEN** a rental with ID `123`
**AND** the rental has status `'scheduled_for_shipping'`
**AND** the rental has `ship_out_tracking_no = 'SF3261559084017'`
**WHEN** the user clicks the "打印" button for this rental
**THEN** a POST request should be sent to `/api/shipping-batch/print-waybills`
**AND** the request body should contain `{"rental_ids": [123]}`
**AND** the Kuaimai print API should be called with the waybill for rental 123
**AND** upon success, a success message "面单打印成功" should be displayed

#### Scenario: Handle print failure

**GIVEN** a rental with ID `456`
**WHEN** the user clicks the "打印" button for this rental
**AND** the print API returns an error
**THEN** an error message "打印失败" should be displayed
**AND** the error details should be logged to console

### Requirement: The API MUST support both single and batch printing via same API

The print waybills API MUST accept an array of rental IDs and work correctly whether the array contains one or multiple IDs.

#### Scenario: Print single rental via batch API

**GIVEN** the `/api/shipping-batch/print-waybills` endpoint exists
**WHEN** a request is made with `{"rental_ids": [123]}`
**THEN** the endpoint should process exactly 1 rental
**AND** the response should contain success/failure for that rental
**AND** the behavior should be identical to batch processing

#### Scenario: Validate rental_ids is array

**GIVEN** a request is made to `/api/shipping-batch/print-waybills`
**WHEN** the request body contains `{"rental_ids": 123}` (not an array)
**THEN** the endpoint should return a 400 Bad Request error
**AND** the error message should indicate that rental_ids must be an array

### Requirement: The UI MUST update table to include print column

The batch shipping table MUST include a new column for individual print actions.

#### Scenario: Display print action column

**GIVEN** the batch shipping page is loaded
**AND** there are rentals in the table
**WHEN** viewing the table
**THEN** a column labeled "操作" should be visible
**AND** the column width should be approximately 100px
**AND** the column should be positioned after the existing columns

#### Scenario: Print column shows correct state

**GIVEN** rental A has status `'scheduled_for_shipping'` with tracking number
**AND** rental B has status `'not_shipped'` without tracking number
**WHEN** viewing the table
**THEN** rental A's row should show an enabled "打印" button
**AND** rental B's row should show no button or a disabled button

## MODIFIED Requirements

None - existing batch print functionality remains unchanged.

## REMOVED Requirements

None - no existing functionality is removed.

## Related Specs

- **rental-status-lifecycle**: Defines which statuses are eligible for printing
- **scheduled-shipping-task**: Rentals transition to shipped status, affecting print eligibility
- **batch-print-ui**: Shares the same print API endpoint

## Implementation Notes

### Frontend Changes

**File**: `frontend/src/views/BatchShippingView.vue`

Add new table column:
```vue
<el-table-column label="操作" width="100">
  <template #default="{ row }">
    <el-button
      v-if="row.status === 'scheduled_for_shipping' && row.ship_out_tracking_no"
      @click="printSingle(row.id)"
      type="primary"
      size="small"
      link
    >
      <el-icon><Printer /></el-icon>
      打印
    </el-button>
  </template>
</el-table-column>
```

Add print method:
```javascript
const printSingle = async (rentalId: number) => {
  try {
    const response = await axios.post('/api/shipping-batch/print-waybills', {
      rental_ids: [rentalId]
    })

    if (response.data.success) {
      const result = response.data.data
      if (result.failed_count === 0) {
        ElMessage.success('面单打印成功')
      } else {
        const errorMsg = result.results[0]?.message || '打印失败'
        ElMessage.error(`打印失败: ${errorMsg}`)
      }
    } else {
      ElMessage.error(response.data.message || '打印失败')
    }
  } catch (error: any) {
    console.error('打印失败:', error)
    ElMessage.error('打印失败')
  }
}
```

### Backend Changes

**File**: `app/routes/shipping_batch_api.py`

No changes needed - existing endpoint already accepts array of rental_ids:

```python
@bp.route('/print-waybills', methods=['POST'])
def print_waybills():
    data = request.get_json()
    rental_ids = data.get('rental_ids', [])

    # Works for both single and batch
    result = waybill_service.batch_print_waybills(rental_ids=rental_ids)

    return jsonify({
        'success': True,
        'data': {
            'total': result['total'],
            'success_count': result['success_count'],
            'failed_count': result['failed_count'],
            'results': result['results']
        }
    }), 200
```

### UI/UX Considerations

**Button Style**: Use `link` type button for minimal visual weight
**Icon**: Printer icon for clear affordance
**Feedback**: Immediate message upon print success/failure
**Error Display**: Show specific error from API response

## Validation

- [ ] Print button appears for eligible rentals
- [ ] Print button is hidden/disabled for ineligible rentals
- [ ] Clicking button sends correct API request with single rental ID
- [ ] API processes single-item array correctly
- [ ] Success message displays on successful print
- [ ] Error message displays on failed print
- [ ] Multiple single prints can be triggered sequentially
- [ ] UI remains responsive during print operation
