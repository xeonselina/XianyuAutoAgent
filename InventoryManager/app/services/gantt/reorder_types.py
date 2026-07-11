"""档期重排的纯数据类型。"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RelayDecision:
    predecessor_rental_id: int
    successor_rental_id: int
    action: Literal["keep", "separate"]


@dataclass(frozen=True)
class ScheduleBlock:
    key: str
    rental_ids: tuple[int, ...]
    model_id: int
    start_day: int
    end_day: int
    current_device_id: int
    allowed_device_ids: tuple[int, ...]
    fixed: bool
