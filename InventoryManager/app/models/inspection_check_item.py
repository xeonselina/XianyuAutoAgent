"""
验货检查项模型
"""
from app import db


class InspectionCheckItem(db.Model):
    """验货检查项表"""
    __tablename__ = 'inspection_check_item'

    id = db.Column(db.Integer, primary_key=True)
    inspection_record_id = db.Column(
        db.Integer,
        db.ForeignKey('inspection_record.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    item_name = db.Column(db.String(100), nullable=False, comment='检查项名称')
    is_checked = db.Column(db.Boolean, nullable=False, default=False, comment='是否勾选')
    item_order = db.Column(db.Integer, nullable=False, default=0, comment='显示顺序')

    def __repr__(self):
        return f'<InspectionCheckItem {self.id} {self.item_name} checked={self.is_checked}>'

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'inspection_record_id': self.inspection_record_id,
            'item_name': self.item_name,
            'is_checked': self.is_checked,
            'item_order': self.item_order
        }
