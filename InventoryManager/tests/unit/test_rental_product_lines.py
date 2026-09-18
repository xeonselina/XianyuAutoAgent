from types import SimpleNamespace

from app.services.printing.rental_product_lines import get_product_lines


def test_product_lines_prefer_canonical_model_display_name():
    rental = SimpleNamespace(
        lens_combo="bare",
        device=SimpleNamespace(
            model="legacy-camera",
            device_model=SimpleNamespace(
                name="camera-pro",
                display_name="演唱会相机 Pro",
            ),
        ),
    )

    assert get_product_lines(rental)[0] == {
        "name": "演唱会相机 Pro",
        "qty": 1,
        "is_main": True,
    }


def test_product_lines_use_immutable_rental_package_snapshot():
    rental = SimpleNamespace(
        lens_combo="bare",
        device=SimpleNamespace(
            model="camera-pro",
            device_model=SimpleNamespace(
                name="camera-pro",
                display_name="演唱会相机 Pro",
            ),
        ),
        get_rental_package_snapshot=lambda: {
            "id": "pkg_camera",
            "name": "机身 + 70-200",
            "items": [
                {"name": "70-200 镜头", "qty": 1},
                {"name": "相机电池", "qty": 2},
            ],
        },
    )

    assert get_product_lines(rental) == [
        {"name": "演唱会相机 Pro", "qty": 1, "is_main": True},
        {"name": "70-200 镜头", "qty": 1, "is_main": False},
        {"name": "相机电池", "qty": 2, "is_main": False},
    ]
