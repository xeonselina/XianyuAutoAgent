"""Bounded preview and execution for moving physical inventory."""

from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.tenant_context import current_tenant_id


class StaleMovementPreviewError(ValueError):
    """A movement preview cannot safely be applied anymore."""


class WarehouseMovementService:
    """Preview and apply one physical device warehouse movement."""

    TOKEN_SALT = "warehouse-device-movement-v1"
    TOKEN_MAX_AGE_SECONDS = 600
    AUTOMATABLE_STATUSES = {"not_shipped", "scheduled_for_shipping"}
    OCCUPANCY_STATUSES = {
        "not_shipped", "scheduled_for_shipping", "shipped", "returned"
    }

    @staticmethod
    def _normalize_id(value, field_name):
        if isinstance(value, bool):
            raise ValueError(f"{field_name}无效")
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name}无效") from None
        if normalized <= 0:
            raise ValueError(f"{field_name}无效")
        return normalized

    @staticmethod
    def _model_key(device):
        if device is None:
            return None
        if device.model_id is not None:
            return ("id", device.model_id)
        normalized = str(device.model or "").strip().casefold()
        return ("model", normalized) if normalized else None

    @staticmethod
    def _model_description(device):
        return {
            "model_id": device.model_id if device is not None else None,
            "model": str(device.model or "").strip() if device else "",
        }

    @staticmethod
    def _occupancy(rental):
        if rental.start_date is None or rental.end_date is None:
            return None
        start = rental.ship_out_time or datetime.combine(
            rental.start_date, time.min
        )
        end = rental.ship_in_time or datetime.combine(
            rental.end_date, time.max
        )
        return (start, end) if start < end else None

    @classmethod
    def _is_future(cls, rental, now):
        occupancy = cls._occupancy(rental)
        if occupancy is not None:
            return occupancy[1] >= now
        return rental.end_date is not None and rental.end_date >= now.date()

    @staticmethod
    def _overlaps(left, right):
        return left[0] < right[1] and left[1] > right[0]

    @classmethod
    def _serializer(cls):
        return URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"], salt=cls.TOKEN_SALT
        )

    @classmethod
    def _load_token(cls, token):
        if not isinstance(token, str) or not token:
            raise StaleMovementPreviewError("预览令牌无效，请重新预览")
        try:
            payload = cls._serializer().loads(
                token, max_age=cls.TOKEN_MAX_AGE_SECONDS
            )
        except SignatureExpired as exc:
            raise StaleMovementPreviewError(
                "预览已过期，请重新预览"
            ) from exc
        except BadSignature as exc:
            raise StaleMovementPreviewError(
                "预览令牌无效，请重新预览"
            ) from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise StaleMovementPreviewError("预览令牌无效，请重新预览")
        return payload

    @staticmethod
    def _json_value(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        return value

    @classmethod
    def _row_fingerprint(cls, row):
        values = {
            column.name: cls._json_value(getattr(row, column.name))
            for column in row.__table__.columns
        }
        encoded = json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _fingerprints(cls, rows):
        return [
            {"id": row.id, "fingerprint": cls._row_fingerprint(row)}
            for row in sorted(rows, key=lambda item: item.id)
        ]

    @staticmethod
    def _locked(query, lock):
        query = query.populate_existing()
        return query.with_for_update() if lock else query

    @classmethod
    def _load_affected_groups(cls, source, now, lock):
        direct_query = Rental.query.filter(
            Rental.device_id == source.id
        ).order_by(Rental.id)
        direct = cls._locked(direct_query, lock).all()
        relevant_direct = [
            rental for rental in direct
            if rental.status not in {"completed", "cancelled"}
            and cls._is_future(rental, now)
        ]

        blocked = []
        main_ids = set()
        direct_by_main = {}
        for rental in relevant_direct:
            if source.is_accessory:
                if rental.parent_rental_id is None:
                    blocked.append({
                        "rental_id": rental.id,
                        "reason": "SOURCE_ROLE_MISMATCH",
                    })
                    continue
                main_id = rental.parent_rental_id
            else:
                if rental.parent_rental_id is not None:
                    blocked.append({
                        "rental_id": rental.id,
                        "reason": "SOURCE_ROLE_MISMATCH",
                    })
                    continue
                main_id = rental.id
            main_ids.add(main_id)
            direct_by_main.setdefault(main_id, []).append(rental.id)

        group_rows = []
        if main_ids:
            group_query = Rental.query.filter(
                db.or_(
                    Rental.id.in_(main_ids),
                    Rental.parent_rental_id.in_(main_ids),
                )
            ).order_by(Rental.id)
            group_rows = cls._locked(group_query, lock).all()
        rows_by_main = {main_id: [] for main_id in main_ids}
        main_by_id = {}
        for rental in group_rows:
            main_id = rental.parent_rental_id or rental.id
            if main_id in rows_by_main:
                rows_by_main[main_id].append(rental)
            if rental.parent_rental_id is None:
                main_by_id[rental.id] = rental

        groups = []
        for main_id in sorted(main_ids):
            main = main_by_id.get(main_id)
            if main is None:
                blocked.append({
                    "rental_id": min(direct_by_main[main_id]),
                    "reason": "PARENT_RENTAL_MISSING",
                })
                continue
            groups.append({
                "main": main,
                "rows": rows_by_main[main_id],
                "direct_ids": sorted(direct_by_main[main_id]),
            })
        return groups, sorted(blocked, key=lambda item: item["rental_id"]), direct

    @classmethod
    def _manual_reason(cls, group):
        main = group["main"]
        if any(
            row.ship_out_tracking_no or row.ship_in_tracking_no
            for row in group["rows"]
        ):
            return "TRACKING_EXISTS"
        if main.status not in cls.AUTOMATABLE_STATUSES:
            return (
                "ALREADY_SHIPPED"
                if main.status in {"shipped", "returned"}
                else "STATUS_NOT_AUTOMATABLE"
            )
        if cls._occupancy(main) is None:
            return "INVALID_SCHEDULE"
        return None

    @classmethod
    def _group_needs(cls, source, target_id, group, devices):
        main = group["main"]
        children = [
            row for row in group["rows"]
            if row.parent_rental_id == main.id
        ]
        if source.is_accessory:
            affected_children = [
                child for child in children
                if child.id in set(group["direct_ids"])
            ]
            needs = []
            for child in affected_children:
                if main.warehouse_id != target_id:
                    needs.append((child, devices.get(child.device_id)))
            return main.warehouse_id, affected_children, needs

        needs = []
        for child in children:
            device = devices.get(child.device_id)
            if device is None or device.warehouse_id != target_id:
                needs.append((child, device))
        return target_id, children, needs

    @classmethod
    def _candidate_devices(cls, need_keys, warehouse_ids, source_id, lock):
        if not need_keys:
            return []
        query = Device.query.filter(
            Device.id != source_id,
            Device.warehouse_id.in_(warehouse_ids),
            Device.is_accessory.is_(True),
        ).order_by(Device.id)
        rows = cls._locked(query, lock).all()
        return [
            device for device in rows
            if cls._model_key(device) in need_keys
        ]

    @classmethod
    def _candidate_occupancies(cls, candidate_ids, lock):
        if not candidate_ids:
            return []
        query = Rental.query.filter(
            Rental.device_id.in_(candidate_ids),
            Rental.status.in_(cls.OCCUPANCY_STATUSES),
        ).order_by(Rental.id)
        return cls._locked(query, lock).all()

    @classmethod
    def _select_candidate(
        cls,
        candidates,
        existing_by_device,
        reservations,
        local_reservations,
        warehouse_id,
        model_key,
        interval,
        excluded_rental_ids,
    ):
        for candidate in candidates:
            if (
                candidate.warehouse_id != warehouse_id
                or candidate.lifecycle_status != "active"
                or cls._model_key(candidate) != model_key
            ):
                continue
            occupied = False
            for rental in existing_by_device.get(candidate.id, []):
                if rental.id in excluded_rental_ids:
                    continue
                existing_interval = cls._occupancy(rental)
                if (
                    existing_interval is None
                    or cls._overlaps(interval, existing_interval)
                ):
                    occupied = True
                    break
            if occupied:
                continue
            planned = reservations.get(candidate.id, []) + [
                item[1] for item in local_reservations
                if item[0] == candidate.id
            ]
            if any(cls._overlaps(interval, item) for item in planned):
                continue
            return candidate
        return None

    @classmethod
    def _build_state(cls, device_id, target_warehouse_id, lock=False):
        now = datetime.utcnow()
        source_query = Device.query.filter(Device.id == device_id)
        source = cls._locked(source_query, lock).one_or_none()
        if source is None:
            raise LookupError("设备不存在")
        target_query = Warehouse.query.filter(
            Warehouse.id == target_warehouse_id
        )
        target = cls._locked(target_query, lock).one_or_none()
        if target is None:
            raise LookupError("目标仓库不存在")
        if source.warehouse_id == target.id:
            raise ValueError("设备已在目标仓库")

        groups, blocked, direct_rows = cls._load_affected_groups(
            source, now, lock
        )
        group_rows = [row for group in groups for row in group["rows"]]
        device_ids = {source.id, *(row.device_id for row in group_rows)}
        device_query = Device.query.filter(
            Device.id.in_(device_ids)
        ).order_by(Device.id)
        current_devices = cls._locked(device_query, lock).all()
        device_by_id = {device.id: device for device in current_devices}

        automatic_groups = []
        manual = []
        need_keys = set()
        need_warehouse_ids = set()
        for group in groups:
            reason = cls._manual_reason(group)
            if reason is not None:
                manual.append({
                    "rental_id": group["main"].id,
                    "reason": reason,
                })
                continue
            fulfillment_id, affected_children, needs = cls._group_needs(
                source, target.id, group, device_by_id
            )
            interval = cls._occupancy(group["main"])
            automatic_groups.append({
                **group,
                "fulfillment_warehouse_id": fulfillment_id,
                "affected_children": affected_children,
                "needs": needs,
                "interval": interval,
            })
            for _child, device in needs:
                model_key = cls._model_key(device)
                if model_key is not None:
                    need_keys.add(model_key)
                    need_warehouse_ids.add(fulfillment_id)

        candidates = cls._candidate_devices(
            need_keys, need_warehouse_ids, source.id, lock
        )
        occupancy_rows = cls._candidate_occupancies(
            [device.id for device in candidates], lock
        )
        existing_by_device = {}
        for rental in occupancy_rows:
            existing_by_device.setdefault(rental.device_id, []).append(rental)

        auto_fixable = []
        shortages = []
        operations = []
        reservations = {}
        automatic_groups.sort(
            key=lambda item: (item["interval"][0], item["main"].id)
        )
        for group in automatic_groups:
            replacements = []
            missing = []
            local_reservations = []
            excluded_ids = {row.id for row in group["rows"]}
            for child, old_device in sorted(
                group["needs"], key=lambda item: item[0].id
            ):
                model_key = cls._model_key(old_device)
                if model_key is None:
                    missing.append({
                        "child_rental_id": child.id,
                        **cls._model_description(old_device),
                    })
                    continue
                replacement = cls._select_candidate(
                    candidates,
                    existing_by_device,
                    reservations,
                    local_reservations,
                    group["fulfillment_warehouse_id"],
                    model_key,
                    group["interval"],
                    excluded_ids,
                )
                if replacement is None:
                    missing.append({
                        "child_rental_id": child.id,
                        **cls._model_description(old_device),
                    })
                    continue
                replacements.append({
                    "child_rental_id": child.id,
                    "old_device_id": child.device_id,
                    "new_device_id": replacement.id,
                })
                local_reservations.append(
                    (replacement.id, group["interval"])
                )

            if missing:
                shortages.append({
                    "rental_id": group["main"].id,
                    "code": (
                        "MODEL_UNKNOWN"
                        if any(
                            item["model_id"] is None and not item["model"]
                            for item in missing
                        )
                        else "NO_AVAILABLE_REPLACEMENT"
                    ),
                    "missing": missing,
                })
                continue

            for replacement_id, interval in local_reservations:
                reservations.setdefault(replacement_id, []).append(interval)
            public_row = {
                "rental_id": group["main"].id,
                "fulfillment_warehouse_id": group[
                    "fulfillment_warehouse_id"
                ],
                "replacements": replacements,
            }
            auto_fixable.append(public_row)
            operations.append({
                **public_row,
                "affected_child_rental_ids": [
                    child.id for child in group["affected_children"]
                ],
                "move_main_rental": not source.is_accessory,
            })

        all_rentals = {
            rental.id: rental
            for rental in direct_rows + group_rows + occupancy_rows
        }
        all_devices = {
            device.id: device
            for device in current_devices + candidates
        }
        warehouse_ids = {
            source.warehouse_id,
            target.id,
            *(group["main"].warehouse_id for group in groups),
        }
        warehouse_query = Warehouse.query.filter(
            Warehouse.id.in_(warehouse_ids)
        ).order_by(Warehouse.id)
        warehouses = cls._locked(warehouse_query, lock).all()
        summary = {
            "source_device_id": source.id,
            "old_warehouse_id": source.warehouse_id,
            "target_warehouse_id": target.id,
            "auto_fixable": sorted(
                auto_fixable, key=lambda item: item["rental_id"]
            ),
            "blocked": blocked,
            "shortages": sorted(
                shortages, key=lambda item: item["rental_id"]
            ),
            "manual": sorted(manual, key=lambda item: item["rental_id"]),
        }
        snapshot = {
            "warehouses": cls._fingerprints(warehouses),
            "devices": cls._fingerprints(all_devices.values()),
            "rentals": cls._fingerprints(all_rentals.values()),
        }
        return {
            "source": source,
            "summary": summary,
            "operations": sorted(
                operations, key=lambda item: item["rental_id"]
            ),
            "snapshot": snapshot,
            "related_device_ids": sorted(all_devices),
            "related_rental_ids": sorted(all_rentals),
            "related_warehouse_ids": sorted(warehouse_ids),
        }

    @classmethod
    def preview(cls, device_id: int, target_warehouse_id: int) -> dict:
        device_id = cls._normalize_id(device_id, "设备ID")
        target_warehouse_id = cls._normalize_id(
            target_warehouse_id, "目标仓库ID"
        )
        state = cls._build_state(device_id, target_warehouse_id)
        payload = {
            "version": 1,
            "tenant_id": current_tenant_id(),
            "source_device_id": device_id,
            "target_warehouse_id": target_warehouse_id,
            "summary": state["summary"],
            "operations": state["operations"],
            "snapshot": state["snapshot"],
            "related_device_ids": state["related_device_ids"],
            "related_rental_ids": state["related_rental_ids"],
            "related_warehouse_ids": state["related_warehouse_ids"],
        }
        return {
            **state["summary"],
            "token": cls._serializer().dumps(payload),
        }

    @classmethod
    def _lock_token_rows(cls, payload):
        warehouse_ids = sorted({
            cls._normalize_id(item, "仓库ID")
            for item in payload.get("related_warehouse_ids", [])
        })
        device_ids = sorted({
            cls._normalize_id(item, "设备ID")
            for item in payload.get("related_device_ids", [])
        })
        rental_ids = sorted({
            cls._normalize_id(item, "租赁ID")
            for item in payload.get("related_rental_ids", [])
        })
        if warehouse_ids:
            Warehouse.query.filter(
                Warehouse.id.in_(warehouse_ids)
            ).order_by(Warehouse.id).populate_existing().with_for_update().all()
        if device_ids:
            Device.query.filter(Device.id.in_(device_ids)).order_by(
                Device.id
            ).populate_existing().with_for_update().all()
        if rental_ids:
            Rental.query.filter(Rental.id.in_(rental_ids)).order_by(
                Rental.id
            ).populate_existing().with_for_update().all()

    @classmethod
    def _assert_payload_matches(cls, payload, state):
        expected = {
            "summary": state["summary"],
            "operations": state["operations"],
            "snapshot": state["snapshot"],
            "related_device_ids": state["related_device_ids"],
            "related_rental_ids": state["related_rental_ids"],
            "related_warehouse_ids": state["related_warehouse_ids"],
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise StaleMovementPreviewError(
                "租赁、设备或仓库状态已变化，请重新预览"
            )

    @classmethod
    def execute(cls, token: str, expected_device_id=None) -> dict:
        payload = cls._load_token(token)
        try:
            device_id = cls._normalize_id(
                payload.get("source_device_id"), "设备ID"
            )
            target_id = cls._normalize_id(
                payload.get("target_warehouse_id"), "目标仓库ID"
            )
        except ValueError as exc:
            raise StaleMovementPreviewError(
                "预览令牌无效，请重新预览"
            ) from exc
        if (
            expected_device_id is not None
            and cls._normalize_id(expected_device_id, "设备ID") != device_id
        ):
            raise StaleMovementPreviewError(
                "预览令牌与当前设备不匹配，请重新预览"
            )
        if payload.get("tenant_id") != current_tenant_id():
            raise StaleMovementPreviewError(
                "预览令牌不属于当前租户，请重新预览"
            )

        try:
            cls._lock_token_rows(payload)
            try:
                state = cls._build_state(device_id, target_id, lock=True)
            except (LookupError, ValueError) as exc:
                raise StaleMovementPreviewError(
                    "设备或仓库状态已变化，请重新预览"
                ) from exc
            cls._assert_payload_matches(payload, state)

            source = state["source"]
            old_warehouse_id = source.warehouse_id
            source.warehouse_id = target_id
            flattened_replacements = []
            for operation in state["operations"]:
                main = db.session.get(Rental, operation["rental_id"])
                child_ids = operation["affected_child_rental_ids"]
                children = {
                    child.id: child
                    for child in Rental.query.filter(
                        Rental.id.in_(child_ids or [-1])
                    ).all()
                }
                if operation["move_main_rental"]:
                    main.warehouse_id = target_id
                    all_children = Rental.query.filter_by(
                        parent_rental_id=main.id
                    ).all()
                    for child in all_children:
                        child.warehouse_id = target_id
                else:
                    for child in children.values():
                        child.warehouse_id = main.warehouse_id

                for replacement in operation["replacements"]:
                    child = db.session.get(
                        Rental, replacement["child_rental_id"]
                    )
                    child.device_id = replacement["new_device_id"]
                    child.warehouse_id = operation[
                        "fulfillment_warehouse_id"
                    ]
                    flattened_replacements.append({
                        "rental_id": main.id,
                        **replacement,
                    })

            AuditLog.log_action(
                action="warehouse_device_moved",
                resource_type="device",
                resource_id=str(source.id),
                description="设备跨仓移动",
                details={
                    "old_warehouse_id": old_warehouse_id,
                    "new_warehouse_id": target_id,
                    "replacements": flattened_replacements,
                },
                commit=False,
            )
            db.session.commit()
            return state["summary"]
        except Exception:
            db.session.rollback()
            raise
