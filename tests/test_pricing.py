import pytest

from app.pricing import PricingError, estimate


def test_single_service(catalog):
    e = estimate(catalog, [("TUNE_BASIC", 1)])
    assert e.total_cents == 6500
    assert e.total_usd == "65.00"
    assert e.requires_inspection is False
    assert e.catalog_version == catalog.version


def test_per_wheel_quantity_and_multiple_lines(catalog):
    # m-1029: pads on both wheels + bleed both brakes = 2*35 + 2*40 = 150
    e = estimate(catalog, [("BRAKE_PADS", 2), ("BRAKE_BLEED", 2)])
    assert e.total_cents == 15000
    assert [i.code for i in e.line_items] == ["BRAKE_PADS", "BRAKE_BLEED"]


def test_duplicate_codes_are_merged(catalog):
    e = estimate(catalog, [("FLAT_FIX", 1), ("FLAT_FIX", 1)])
    assert len(e.line_items) == 1
    assert e.line_items[0].quantity == 2
    assert e.total_cents == 3000


def test_requires_inspection_bubbles_up(catalog):
    e = estimate(catalog, [("TUNE_BASIC", 1), ("EBIKE_DIAG", 1)])
    assert e.requires_inspection is True
    assert e.total_cents == 12500


def test_unknown_code_rejected(catalog):
    with pytest.raises(PricingError):
        estimate(catalog, [("FREE_VIP", 1)])


@pytest.mark.parametrize("qty", [0, 5, -1])
def test_quantity_bounds(catalog, qty):
    with pytest.raises(PricingError):
        estimate(catalog, [("WHEEL_TRUE", qty)])


def test_empty_picks_is_zero(catalog):
    e = estimate(catalog, [])
    assert e.total_cents == 0 and e.line_items == ()
