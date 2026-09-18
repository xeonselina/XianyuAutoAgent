"""Join independently applied booking and rental-alert migration histories.

Neither parent is rewritten, so databases already on either head can upgrade.
"""
revision = '20260914_merge_booking_alerts'
down_revision = ('20260914_multi_device_booking', '20260908_xianyu_alert_ignore')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
