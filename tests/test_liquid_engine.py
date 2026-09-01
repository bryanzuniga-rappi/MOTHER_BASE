from engines.liquid_engine import (
    _weighted_integer_allocation,
    parse_manual_skus,
)


def test_parse_manual_skus_accepts_commas_and_lines():
    assert parse_manual_skus("10087, 10589\n10848") == {10087, 10589, 10848}


def test_share_rounding_preserves_all_units():
    options = [
        {"destination": 1, "share": 0.50, "priority": 1},
        {"destination": 2, "share": 0.30, "priority": 2},
        {"destination": 3, "share": 0.20, "priority": 3},
    ]
    capacity = {1: 10, 2: 10, 3: 10}
    allocation = _weighted_integer_allocation(7, options, capacity)
    assert allocation == {1: 4, 2: 2, 3: 1}
    assert sum(allocation.values()) == 7


def test_share_rounding_respects_capacity():
    options = [
        {"destination": 1, "share": 0.80, "priority": 1},
        {"destination": 2, "share": 0.20, "priority": 2},
    ]
    capacity = {1: 2, 2: 10}
    allocation = _weighted_integer_allocation(7, options, capacity)
    assert allocation[1] == 2
    assert allocation[2] == 5
    assert sum(allocation.values()) == 7

