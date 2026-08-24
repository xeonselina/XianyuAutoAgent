"""Declarative base used only by the inventory control database."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


CONTROL_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class ControlBase(DeclarativeBase):
    """Metadata boundary that must never include tenant business models."""

    metadata = MetaData(naming_convention=CONTROL_NAMING_CONVENTION)
