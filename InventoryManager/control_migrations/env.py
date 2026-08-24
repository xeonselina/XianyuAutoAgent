"""Standalone Alembic environment for the inventory control database."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from inventory_control.models import ControlBase
from inventory_control.models.base import CONTROL_NAMING_CONVENTION


config = context.config
if config.config_file_name is not None:
    # Standalone and in-process migration runs share this environment.  Keep
    # host application/test loggers alive while installing Alembic handlers.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

def _build_migration_target_metadata() -> MetaData:
    """Keep already-rendered control constraint names stable in Alembic.

    The ORM metadata uses a ``ck_<table>_<semantic-name>`` convention and its
    check-constraint names are already rendered when the model classes are
    imported.  Historical migration files likewise carry those complete
    names.  Reapplying the ORM convention to a complete migration name would
    produce ``ck_<table>_ck_<table>_...`` and make a batch downgrade differ
    from an ORM-created head schema.  The copied metadata remains equivalent
    for autogenerate, while treating complete check names as final.
    """

    migration_convention = dict(CONTROL_NAMING_CONVENTION)
    migration_convention["ck"] = "%(constraint_name)s"
    metadata = MetaData(naming_convention=migration_convention)
    for table in ControlBase.metadata.sorted_tables:
        table.to_metadata(metadata)
    return metadata


target_metadata = _build_migration_target_metadata()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("control migration URL is required")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        context.configure(
            connection=provided_connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section) or {}
    if not section.get("sqlalchemy.url"):
        raise RuntimeError("control migration URL is required")
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
