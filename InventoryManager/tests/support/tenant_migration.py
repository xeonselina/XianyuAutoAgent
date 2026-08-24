"""Shared migration fixture builders for isolated database tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.schema import MetaData


def build_migration_segment_baseline(
    engine: Engine,
    *,
    script_location: Path,
    target_metadata: MetaData,
    schema_head: str,
    baseline_revision: str | None,
) -> None:
    """Derive a segment baseline through its tested downgrade chain."""

    target_metadata.create_all(engine)
    with engine.connect() as connection:
        config = Config(str(script_location / "alembic.ini"))
        config.set_main_option("script_location", str(script_location))
        config.attributes["connection"] = connection
        config.attributes["target_metadata"] = target_metadata
        command.stamp(config, schema_head)
        connection.commit()
        command.downgrade(config, baseline_revision or "base")
        connection.commit()


def build_tenant_saas_segment_baseline(
    engine: Engine,
    *,
    script_location: Path,
    target_metadata: MetaData,
    schema_head: str,
    baseline_revision: str,
) -> None:
    """Derive the approved tenant SaaS-segment baseline."""

    build_migration_segment_baseline(
        engine,
        script_location=script_location,
        target_metadata=target_metadata,
        schema_head=schema_head,
        baseline_revision=baseline_revision,
    )


__all__ = [
    "build_migration_segment_baseline",
    "build_tenant_saas_segment_baseline",
]
