# Device Lifecycle Implementation Guide

Quick reference for implementing the device lifecycle status feature.

---

## 1. Database Migration

Create file: `migrations/versions/{timestamp}_add_device_lifecycle_status.py`

```python
"""add_device_lifecycle_status"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '{generate_uuid}'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Create enum type
    lifecycle_enum = sa.Enum('active', 'sold', 'decommissioned', 'damaged', 'retired',
                             name='device_lifecycle_status')
    
    # For PostgreSQL, create the enum type first
    op.execute("CREATE TYPE device_lifecycle_status AS ENUM ('active', 'sold', 'decommissioned', 'damaged', 'retired')")
    
    # Add columns to devices table
    op.add_column('devices', sa.Column(
        'lifecycle_status',
        lifecycle_enum,
        server_default='active',
        nullable=False
    ))
    op.add_column('devices', sa.Column(
        'lifecycle_reason',
        sa.String(255),
        nullable=True
    ))
    op.add_column('devices', sa.Column(
        'lifecycle_date',
        sa.DateTime,
        nullable=True
    ))

def downgrade():
    op.drop_column('devices', 'lifecycle_date')
    op.drop_column('devices', 'lifecycle_reason')
    op.drop_column('devices', 'lifecycle_status')
    op.execute("DROP TYPE device_lifecycle_status")
```

Run migration:
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
flask db upgrade
```

---

## 2. Update Device Model

File: `app/models/device.py`

Add these fields to the Device class:

```python
from datetime import datetime

class Device(db.Model):
    # ... existing fields ...
    
    # Device Lifecycle Status (NEW)
    lifecycle_status = db.Column(
        db.Enum('active', 'sold', 'decommissioned', 'damaged', 'retired', name='device_lifecycle_status'),
        default='active',
        nullable=False,
        comment='Device lifecycle status'
    )
    lifecycle_reason = db.Column(
        db.String(255),
        nullable=True,
        comment='Reason for lifecycle status change'
    )
    lifecycle_date = db.Column(
        db.DateTime,
        nullable=True,
        comment='Date when lifecycle status was changed'
    )
    
    # ... rest of fields ...
    
    def to_dict(self):
        """Convert to dictionary - UPDATE THIS METHOD"""
        result = {
            'id': self.id,
            'name': self.name,
            'serial_number': self.serial_number,
            'model': self.model,
            'model_id': self.model_id,
            'device_model': self.device_model.to_dict() if self.device_model else None,
            'is_accessory': self.is_accessory,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            # NEW FIELDS
            'lifecycle_status': self.lifecycle_status,
            'lifecycle_reason': self.lifecycle_reason,
            'lifecycle_date': self.lifecycle_date.isoformat() if self.lifecycle_date else None,
        }
        return result
    
    # NEW HELPER METHODS
    def is_in_service(self):
        """Check if device is in active service"""
        return self.lifecycle_status == 'active'
    
    def is_excluded_from_statistics(self):
        """Check if device should be excluded from rental statistics"""
        return self.lifecycle_status in ['sold', 'decommissioned', 'damaged']
    
    def can_create_new_rental(self):
        """Check if new rentals can be created for this device"""
        return self.lifecycle_status == 'active'
```

---

## 3. Update Rental Statistics API

File: `app/routes/rental_stats_api.py`

Replace the `_get_excluded_device_ids_from_db()` function:

```python
def _get_excluded_device_ids_from_db():
    """
    Returns set of device IDs that should be excluded from statistics.
    
    Includes:
    1. Devices marked as sold/decommissioned/damaged (lifecycle_status)
    2. Legacy hardcoded exclusions (for backward compatibility)
    """
    # New approach: query lifecycle_status
    excluded_by_lifecycle = Device.query.filter(
        Device.lifecycle_status.in_(['sold', 'decommissioned', 'damaged'])
    ).all()
    
    # Legacy approach: keep hardcoded list for backward compatibility
    excluded_by_name = Device.query.filter(
        Device.name.in_(EXCLUDED_DEVICE_NAMES)
    ).all()
    
    # Combine both approaches
    excluded_ids = {d.id for d in excluded_by_lifecycle + excluded_by_name}
    return excluded_ids
```

---

## 4. Add API Endpoint for Device Lifecycle

File: `app/routes/device_api.py`

Add this new endpoint:

```python
@bp.route('/api/devices/<device_id>/lifecycle', methods=['PUT'])
def update_device_lifecycle(device_id):
    """
    Update device lifecycle status.
    
    Request body:
    {
      "lifecycle_status": "sold|decommissioned|damaged|retired|active",
      "reason": "Optional reason for change"
    }
    """
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': 'Device not found'
            }), 404
        
        data = request.get_json()
        new_status = data.get('lifecycle_status')
        
        # Validate status
        valid_statuses = ['active', 'sold', 'decommissioned', 'damaged', 'retired']
        if not new_status or new_status not in valid_statuses:
            return jsonify({
                'success': False,
                'error': f'Invalid lifecycle_status. Must be one of: {", ".join(valid_statuses)}'
            }), 400
        
        # Prevent new rentals if device is being removed
        if new_status != 'active' and device.lifecycle_status == 'active':
            # Optional: Check for active rentals
            active_rentals = device.rentals.filter(
                Rental.status.in_(['not_shipped', 'shipped'])
            ).count()
            if active_rentals > 0:
                current_app.logger.warning(
                    f"Device {device.name} has {active_rentals} active rentals "
                    f"but is being marked as {new_status}"
                )
        
        # Update device
        old_status = device.lifecycle_status
        device.lifecycle_status = new_status
        device.lifecycle_reason = data.get('reason')
        device.lifecycle_date = datetime.utcnow()
        device.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        current_app.logger.info(
            f"Device {device.name} lifecycle status changed from {old_status} to {new_status}"
        )
        
        return jsonify({
            'success': True,
            'message': f'Device {device.name} marked as {new_status}',
            'data': device.to_dict()
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to update device lifecycle: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to update device lifecycle'
        }), 500


@bp.route('/api/devices/lifecycle/status', methods=['GET'])
def get_device_lifecycle_summary():
    """Get count of devices by lifecycle status"""
    try:
        summary = db.session.query(
            Device.lifecycle_status,
            db.func.count(Device.id).label('count')
        ).group_by(Device.lifecycle_status).all()
        
        result = {status: count for status, count in summary}
        
        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        current_app.logger.error(f"Failed to get lifecycle summary: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to get lifecycle summary'
        }), 500
```

---

## 5. Add Admin UI (HTML/JavaScript)

Create new section in device management page or admin panel:

```html
<!-- Device Lifecycle Management Modal -->
<div id="lifecycleModal" class="modal">
  <div class="modal-content">
    <span class="close">&times;</span>
    <h2>Mark Device as Sold/Decommissioned</h2>
    
    <form id="lifecycleForm">
      <input type="hidden" id="deviceId">
      
      <div class="form-group">
        <label for="currentStatus">Current Status:</label>
        <span id="currentStatus" style="font-weight: bold;"></span>
      </div>
      
      <div class="form-group">
        <label for="newStatus">New Status:</label>
        <select id="newStatus" required>
          <option value="">-- Select Status --</option>
          <option value="active">Active (In Service)</option>
          <option value="sold">Sold (Permanently Removed)</option>
          <option value="decommissioned">Decommissioned (End of Life)</option>
          <option value="damaged">Damaged (Under Repair)</option>
          <option value="retired">Retired (Voluntarily Removed)</option>
        </select>
      </div>
      
      <div class="form-group">
        <label for="reason">Reason for Change:</label>
        <textarea id="reason" rows="4" placeholder="e.g., Sold to customer on 2026-05-09"></textarea>
      </div>
      
      <button type="submit" class="btn btn-primary">Update Status</button>
      <button type="button" class="btn btn-secondary" onclick="closeLifecycleModal()">Cancel</button>
    </form>
  </div>
</div>

<script>
function openLifecycleModal(deviceId, deviceName, currentStatus) {
  document.getElementById('deviceId').value = deviceId;
  document.getElementById('currentStatus').textContent = currentStatus;
  document.getElementById('newStatus').value = '';
  document.getElementById('reason').value = '';
  document.getElementById('lifecycleModal').style.display = 'block';
}

function closeLifecycleModal() {
  document.getElementById('lifecycleModal').style.display = 'none';
}

document.getElementById('lifecycleForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const deviceId = document.getElementById('deviceId').value;
  const newStatus = document.getElementById('newStatus').value;
  const reason = document.getElementById('reason').value;
  
  try {
    const response = await fetch(`/api/devices/${deviceId}/lifecycle`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        lifecycle_status: newStatus,
        reason: reason
      })
    });
    
    const data = await response.json();
    
    if (data.success) {
      alert(`Device marked as ${newStatus}`);
      closeLifecycleModal();
      location.reload(); // Reload page to show updated status
    } else {
      alert(`Error: ${data.error}`);
    }
  } catch (error) {
    alert(`Error: ${error}`);
  }
});

// Close modal when clicking outside
window.onclick = function(event) {
  const modal = document.getElementById('lifecycleModal');
  if (event.target === modal) {
    modal.style.display = 'none';
  }
}
</script>
```

---

## 6. Testing

### Test 1: Mark Device as Sold

```bash
curl -X PUT http://localhost:5000/api/devices/1005/lifecycle \
  -H "Content-Type: application/json" \
  -d '{
    "lifecycle_status": "sold",
    "reason": "Sold to customer"
  }'
```

Expected response:
```json
{
  "success": true,
  "message": "Device 2005 marked as sold",
  "data": {
    "id": 1005,
    "name": "2005",
    "lifecycle_status": "sold",
    "lifecycle_reason": "Sold to customer",
    "lifecycle_date": "2026-05-09T15:30:00"
  }
}
```

### Test 2: Get Device Details

```bash
curl http://localhost:5000/api/devices/1005
```

Verify `lifecycle_status`, `lifecycle_reason`, `lifecycle_date` are present.

### Test 3: Verify Statistics Exclude Device

```bash
curl "http://localhost:5000/api/rental-stats/periodic?model=x200u&start_date=2026-05-01&end_date=2026-05-31"
```

Verify that device 1005 is NOT counted in `device_count`.

### Test 4: Get Lifecycle Summary

```bash
curl http://localhost:5000/api/devices/lifecycle/status
```

Expected response:
```json
{
  "success": true,
  "data": {
    "active": 7,
    "sold": 1,
    "decommissioned": 2,
    "damaged": 0,
    "retired": 0
  }
}
```

---

## 7. Data Migration (if needed)

Migrate existing excluded devices to use new field:

```sql
-- Mark broken/decommissioned devices
UPDATE devices 
SET lifecycle_status = 'decommissioned',
    lifecycle_reason = 'Previously hardcoded exclusion - needs repair',
    lifecycle_date = NOW()
WHERE name IN ('2005', '3005', '3006');

-- Mark dropshipping devices
UPDATE devices 
SET lifecycle_status = 'retired',
    lifecycle_reason = 'Dropshipping device - not counted in statistics',
    lifecycle_date = NOW()
WHERE name IN ('代发01', '代发02', '代发03', '代发 04 深圳');

-- Verify
SELECT lifecycle_status, COUNT(*) as count FROM devices GROUP BY lifecycle_status;
```

---

## 8. Deployment Checklist

- [ ] Create and test migration file
- [ ] Update Device model with new fields
- [ ] Update device.to_dict() method
- [ ] Update rental_stats_api.py _get_excluded_device_ids_from_db()
- [ ] Add new API endpoint /api/devices/<id>/lifecycle
- [ ] Add lifecycle summary endpoint
- [ ] Create admin UI for device lifecycle management
- [ ] Test all API endpoints
- [ ] Run database migration on production
- [ ] Verify statistics calculations
- [ ] Document new feature for users
- [ ] Update API documentation

---

## 9. Backward Compatibility Notes

✓ **Fully backward compatible:**
- New fields have defaults (lifecycle_status='active')
- Existing rental records unchanged
- Hardcoded EXCLUDED_DEVICE_NAMES still works alongside new system
- No breaking changes to existing API endpoints

---

## 10. Future Enhancements

- [ ] Add audit trail (who changed status, when, why)
- [ ] Add bulk operations (mark multiple devices at once)
- [ ] Add soft delete / restore capability
- [ ] Add email notifications when device is marked as sold
- [ ] Add reporting on device lifecycle transitions
- [ ] Add historical cost analysis for sold/decommissioned devices

