"""Independent control-plane database primitives."""

from app.control.models import ControlBase
from app.control.store import ControlStore

__all__ = ["ControlBase", "ControlStore"]
