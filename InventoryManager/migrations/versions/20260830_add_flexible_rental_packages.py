"""add flexible model rental packages and rental snapshots

Revision ID: 20260830_rental_packages
Revises: 20260830_model_lens_combos
Create Date: 2026-08-30
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260830_rental_packages"
down_revision = "20260830_model_lens_combos"
branch_labels = None
depends_on = None


_DEFINITIONS = {
    "lens_400mm": {
        "name": "400MM 镜头",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
            {"name": "400MM 增距镜+增距镜脚架+手机壳", "qty": 1},
            {"name": "套装便携手提包", "qty": 1},
        ],
    },
    "lens_200mm": {
        "name": "200MM 镜头",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
            {"name": "200MM 镜头+手机壳", "qty": 1},
            {"name": "套装便携手提包", "qty": 1},
        ],
    },
    "bare": {
        "name": "裸机",
        "items": [{"name": "90w 充电头+充电线", "qty": 1}],
    },
    "lens_dual": {
        "name": "双镜头",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
            {"name": "400MM 增距镜+增距镜脚架+手机壳", "qty": 1},
            {"name": "200MM 镜头", "qty": 1},
            {"name": "套装便携手提包", "qty": 1},
        ],
    },
}


def _package_id(combo):
    return f"legacy_{combo}"


def _package(combo):
    definition = _DEFINITIONS.get(combo, {"name": combo, "items": []})
    return {
        "id": _package_id(combo),
        "name": definition["name"],
        "is_active": True,
        "items": definition["items"],
    }


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_allowed(value, model_name):
    try:
        allowed = json.loads(value) if value else []
    except (TypeError, json.JSONDecodeError):
        allowed = []
    allowed = [item for item in allowed if item in _DEFINITIONS]
    if allowed:
        return list(dict.fromkeys(allowed))
    normalized = str(model_name or "").lower().replace(" ", "").replace("+", "")
    if "x300u" in normalized and "x300pro" not in normalized:
        return ["lens_400mm", "lens_200mm", "bare", "lens_dual"]
    return ["lens_200mm", "bare"]


def upgrade():
    op.add_column(
        "device_models",
        sa.Column("rental_packages", sa.Text(), nullable=True),
    )
    op.add_column(
        "device_models",
        sa.Column("default_rental_package_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "rentals",
        sa.Column("rental_package_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "rentals",
        sa.Column("rental_package_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "rentals",
        sa.Column("rental_package_items", sa.Text(), nullable=True),
    )

    connection = op.get_bind()
    models = connection.execute(
        sa.text(
            "SELECT id, name, is_accessory, allowed_lens_combos, default_lens_combo "
            "FROM device_models"
        )
    ).mappings().all()
    for model in models:
        if model["is_accessory"]:
            continue
        allowed = _parse_allowed(model["allowed_lens_combos"], model["name"])
        default_combo = model["default_lens_combo"]
        if default_combo not in allowed:
            default_combo = allowed[0]
        connection.execute(
            sa.text(
                "UPDATE device_models SET rental_packages = :packages, "
                "default_rental_package_id = :default_id WHERE id = :model_id"
            ),
            {
                "packages": _json([_package(combo) for combo in allowed]),
                "default_id": _package_id(default_combo),
                "model_id": model["id"],
            },
        )

    rentals = connection.execute(
        sa.text(
            "SELECT r.id, r.lens_combo FROM rentals r "
            "WHERE r.parent_rental_id IS NULL"
        )
    ).mappings().all()
    for rental in rentals:
        combo = rental["lens_combo"] if rental["lens_combo"] in _DEFINITIONS else "lens_200mm"
        package = _package(combo)
        connection.execute(
            sa.text(
                "UPDATE rentals SET rental_package_id = :package_id, "
                "rental_package_name = :package_name, "
                "rental_package_items = :package_items WHERE id = :rental_id"
            ),
            {
                "package_id": package["id"],
                "package_name": package["name"],
                "package_items": _json(package["items"]),
                "rental_id": rental["id"],
            },
        )


def downgrade():
    op.drop_column("rentals", "rental_package_items")
    op.drop_column("rentals", "rental_package_name")
    op.drop_column("rentals", "rental_package_id")
    op.drop_column("device_models", "default_rental_package_id")
    op.drop_column("device_models", "rental_packages")
