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
