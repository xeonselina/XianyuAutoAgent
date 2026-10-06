from types import SimpleNamespace

from app.services.printing.rental_product_lines import (
    get_product_lines, is_non_default_rental_package,
)


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


def test_print_highlight_uses_model_package_default_and_legacy_combo_fallback():
    model = SimpleNamespace(
        get_effective_rental_package_config=lambda: ([], 'pkg_default'),
        get_effective_lens_combo_config=lambda: ([], 'bare'),
    )
    rental = SimpleNamespace(
        device=SimpleNamespace(model='x300u', device_model=model),
        rental_package_id='pkg_special', lens_combo='bare',
    )
    assert is_non_default_rental_package(rental)
    rental.rental_package_id = 'pkg_default'
    assert not is_non_default_rental_package(rental)

    rental.rental_package_id = None
    rental.lens_combo = 'lens_400mm'
    assert is_non_default_rental_package(rental)
    rental.lens_combo = 'bare'
    assert not is_non_default_rental_package(rental)
    rental.device.device_model = None
    assert is_non_default_rental_package(rental)  # x300u 默认 400MM
    rental.rental_package_id = 'legacy_bare'
    assert is_non_default_rental_package(rental)
    rental.lens_combo = None
    assert not is_non_default_rental_package(rental)
