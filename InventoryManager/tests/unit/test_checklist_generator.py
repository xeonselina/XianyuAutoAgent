"""Tests for dynamically generated inspection checklists."""

from types import SimpleNamespace

from app.models.inspection_check_item import InspectionCheckItem
from app.services.checklist_generator import ChecklistGenerator


class EmptyChildRentals:
    def count(self):
        return 0

    def __iter__(self):
        return iter(())


def make_rental(damage_note=None):
    return SimpleNamespace(
        includes_handle=False,
        includes_lens_mount=False,
        child_rentals=EmptyChildRentals(),
        photo_transfer=False,
        damage_note=damage_note,
    )


def test_rental_without_damage_note_keeps_base_checklist():
    checklist = ChecklistGenerator.generate_checklist(make_rental())

    assert len(checklist) == len(ChecklistGenerator.BASE_ITEMS)
    assert all("default_checked" not in item for item in checklist)


def test_damage_note_appends_default_unchecked_final_item():
    checklist = ChecklistGenerator.generate_checklist(
        make_rental("屏幕右下角碎裂")
    )

    assert checklist[-1] == {
        "name": "处理用户反馈：屏幕右下角碎裂",
        "order": len(ChecklistGenerator.BASE_ITEMS) + 1,
        "default_checked": False,
    }
    assert ChecklistGenerator.calculate_expected_count(
        make_rental("屏幕右下角碎裂")
    ) == len(ChecklistGenerator.BASE_ITEMS) + 1


def test_inspection_item_column_holds_maximum_damage_note_snapshot():
    required_length = len("处理用户反馈：") + 1000

    assert InspectionCheckItem.item_name.type.length >= required_length

