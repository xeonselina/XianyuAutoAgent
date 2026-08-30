"""设备型号业务逻辑服务层。"""

from decimal import Decimal, InvalidOperation
import re

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db
from app.lens_combos import (
    LENS_COMBO_VALUES,
    compatibility_lens_combo_config,
)
from app.models.device import Device
from app.models.device_model import DeviceModel


class DeviceModelConflict(ValueError):
    """型号操作与现有数据冲突。"""


class DeviceModelNotFound(LookupError):
    """型号不存在。"""


_MODEL_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class DeviceModelService:
    """设备型号服务类"""

    @staticmethod
    def get_active_models_with_accessories() -> list:
        """获取所有激活的设备型号及其附件
        
        Returns:
            list: 包含设备型号信息和关联附件的列表
        """
        try:
            # 只获取主设备型号（不包括附件）
            models = DeviceModel.get_active_models(include_accessories=False)
            result = []

            for model in models:
                model_data = model.to_dict(include_accessories=True)
                result.append(model_data)

            return result

        except Exception as e:
            current_app.logger.error(f"获取设备型号失败: {e}")
            raise

    @staticmethod
    def get_accessories_for_model(model_id: int) -> list:
        """获取指定型号的附件
        
        Args:
            model_id: 设备型号ID
        
        Returns:
            list: 该型号的附件列表
        """
        try:
            # 使用 DeviceModel 的类方法来获取附件
            accessories = DeviceModel.get_accessories_for_model(model_id)
            result = [acc.to_dict(include_accessories=False) for acc in accessories]
            return result

        except Exception as e:
            current_app.logger.error(f"获取设备附件失败: {e}")
            raise

    @staticmethod
    def get_library() -> dict:
        """返回包含停用项、引用数和未归类组的完整型号库。"""
        counts = dict(
            db.session.query(Device.model_id, func.count(Device.id))
            .filter(Device.model_id.isnot(None))
            .group_by(Device.model_id)
            .all()
        )
        models = DeviceModel.query.order_by(
            DeviceModel.is_accessory,
            DeviceModel.display_name,
            DeviceModel.id,
        ).all()
        payload = []
        for model in models:
            row = model.to_dict(include_accessories=False)
            row["device_count"] = counts.get(model.id, 0)
            row["accessory_count"] = len(model.accessories)
            payload.append(row)

        normalized_model = func.lower(func.trim(Device.model))
        legacy_rows = (
            db.session.query(
                normalized_model.label("normalized_model"),
                func.min(func.trim(Device.model)).label("model"),
                func.count(Device.id).label("device_count"),
            )
            .filter(
                Device.model_id.is_(None),
                Device.model.isnot(None),
                func.trim(Device.model) != "",
            )
            .group_by(normalized_model)
            .order_by(func.count(Device.id).desc(), func.min(Device.model))
            .all()
        )
        return {
            "models": payload,
            "legacy_groups": [
                {
                    "normalized_model": row.normalized_model,
                    "model": row.model,
                    "device_count": row.device_count,
                }
                for row in legacy_rows
            ],
        }

    @staticmethod
    def _required_text(data, field, maximum):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} 不能为空")
        value = value.strip()
        if len(value) > maximum:
            raise ValueError(f"{field} 长度不能超过 {maximum}")
        return value

    @staticmethod
    def _parse_value(value):
        if value in (None, ""):
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("设备价值必须是有效数字") from exc
        if parsed < 0 or parsed > Decimal("99999999.99"):
            raise ValueError("设备价值必须介于 0 和 99999999.99 之间")
        return parsed

    @staticmethod
    def _parse_bool(data, field, default):
        if field not in data:
            return default
        value = data[field]
        if not isinstance(value, bool):
            raise ValueError(f"{field} 必须是布尔值")
        return value

    @staticmethod
    def _resolve_parent(parent_model_id, model_id=None):
        if parent_model_id in (None, ""):
            return None
        try:
            parent_model_id = int(parent_model_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("主设备型号无效") from exc
        if model_id is not None and parent_model_id == model_id:
            raise ValueError("附件型号不能关联自身")
        parent = db.session.get(DeviceModel, parent_model_id)
        if parent is None or parent.is_accessory:
            raise ValueError("主设备型号不存在或不是主设备")
        return parent

    @staticmethod
    def _apply_lens_combo_fields(model, data, *, creating=False, type_changed=False):
        if model.is_accessory:
            model.set_allowed_lens_combos_list([])
            model.default_lens_combo = None
            return

        should_apply = (
            creating
            or type_changed
            or "allowed_lens_combos" in data
            or "default_lens_combo" in data
        )
        if not should_apply:
            return

        fallback_allowed, fallback_default = compatibility_lens_combo_config(
            model.name
        )
        current_allowed = model.get_allowed_lens_combos_list()
        allowed = data.get(
            "allowed_lens_combos",
            current_allowed or fallback_allowed,
        )
        default = data.get(
            "default_lens_combo",
            model.default_lens_combo or fallback_default,
        )
        if not isinstance(allowed, list) or not allowed:
            raise ValueError("主设备至少要选择一个镜头组合")
        if any(not isinstance(item, str) for item in allowed):
            raise ValueError("镜头组合必须是文本列表")
        allowed = list(dict.fromkeys(allowed))
        invalid = [item for item in allowed if item not in LENS_COMBO_VALUES]
        if invalid:
            raise ValueError(f"无效的镜头组合: {invalid}")
        if default not in allowed:
            raise ValueError("默认镜头组合必须属于允许的组合")
        model.set_allowed_lens_combos_list(allowed)
        model.default_lens_combo = default

    @staticmethod
    def _apply_editable_fields(model, data, *, creating=False):
        if creating:
            name = DeviceModelService._required_text(data, "name", 50)
            if not _MODEL_CODE_RE.fullmatch(name):
                raise ValueError("型号编码只能包含字母、数字、点、横线和下划线")
            duplicate = DeviceModel.query.filter(
                func.lower(DeviceModel.name) == name.casefold()
            ).first()
            if duplicate is not None:
                raise DeviceModelConflict("型号编码已存在")
            model.name = name
        elif "name" in data and str(data["name"] or "").strip() != model.name:
            raise ValueError("型号编码创建后不能修改")

        if creating or "display_name" in data:
            model.display_name = DeviceModelService._required_text(
                data, "display_name", 100
            )
        if "description" in data:
            description = data.get("description")
            model.description = (
                str(description).strip() if description not in (None, "") else None
            )
        type_changed = False
        if creating or "is_accessory" in data:
            requested_accessory = DeviceModelService._parse_bool(
                data, "is_accessory", False
            )
            type_changed = not creating and requested_accessory != model.is_accessory
            if not creating and requested_accessory != model.is_accessory:
                if model.devices.first() is not None:
                    raise DeviceModelConflict("已有设备引用的型号不能改变类型")
                if model.accessories:
                    raise DeviceModelConflict("包含附件的主型号不能改变类型")
            model.is_accessory = requested_accessory
        if "is_active" in data or creating:
            model.is_active = DeviceModelService._parse_bool(
                data, "is_active", True
            )
        if "device_value" in data:
            model.device_value = DeviceModelService._parse_value(
                data.get("device_value")
            )
        if "default_accessories" in data:
            accessories = data.get("default_accessories")
            if accessories is None:
                accessories = []
            if not isinstance(accessories, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in accessories
            ):
                raise ValueError("默认附件必须是非空文本列表")
            model.set_default_accessories_list(
                list(dict.fromkeys(item.strip() for item in accessories))
            )

        if model.is_accessory:
            if creating or "parent_model_id" in data:
                parent = DeviceModelService._resolve_parent(
                    data.get("parent_model_id"), model.id
                )
                model.parent_model_id = parent.id if parent else None
        else:
            model.parent_model_id = None

        DeviceModelService._apply_lens_combo_fields(
            model,
            data,
            creating=creating,
            type_changed=type_changed,
        )

    @staticmethod
    def create(data) -> dict:
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        model = DeviceModel()
        DeviceModelService._apply_editable_fields(model, data, creating=True)
        db.session.add(model)
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise DeviceModelConflict("型号编码已存在") from exc
        except Exception:
            db.session.rollback()
            raise
        result = model.to_dict(include_accessories=False)
        result.update(device_count=0, accessory_count=0)
        return result

    @staticmethod
    def update(model_id, data) -> dict:
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        model = db.session.get(DeviceModel, model_id)
        if model is None:
            raise DeviceModelNotFound("设备型号不存在")
        DeviceModelService._apply_editable_fields(model, data)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        result = model.to_dict(include_accessories=False)
        result.update(
            device_count=model.devices.count(),
            accessory_count=len(model.accessories),
        )
        return result

    @staticmethod
    def delete(model_id) -> None:
        model = db.session.get(DeviceModel, model_id)
        if model is None:
            raise DeviceModelNotFound("设备型号不存在")
        if model.devices.first() is not None:
            raise DeviceModelConflict("该型号已有设备引用，请改为停用")
        if model.accessories:
            raise DeviceModelConflict("该型号仍有关联附件，请先处理附件型号")
        db.session.delete(model)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def assign_legacy_group(legacy_model, model_id) -> dict:
        if not isinstance(legacy_model, str) or not legacy_model.strip():
            raise ValueError("待归类型号不能为空")
        try:
            model_id = int(model_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("目标型号无效") from exc
        model = db.session.get(DeviceModel, model_id)
        if model is None:
            raise DeviceModelNotFound("目标型号不存在")
        if not model.is_active:
            raise DeviceModelConflict("不能归类到已停用型号")

        normalized = legacy_model.strip().casefold()
        devices = Device.query.filter(
            Device.model_id.is_(None),
            func.lower(func.trim(Device.model)) == normalized,
        ).all()
        if not devices:
            raise DeviceModelNotFound("待归类设备组不存在")
        for device in devices:
            device.model_id = model.id
            device.model = model.name
            device.is_accessory = model.is_accessory
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return {"updated_count": len(devices), "model": model.to_dict(False)}
