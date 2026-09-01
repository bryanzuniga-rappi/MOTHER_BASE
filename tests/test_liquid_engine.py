from engines.liquid_engine import (
    _weighted_integer_allocation,
    apply_liquid_engine,
    parse_manual_skus,
)
from types import SimpleNamespace

import modelo_abasto as engine


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


def test_manual_sku_is_liquidated_only_from_selected_origin():
    catalogs = engine.Catalogs(
        volume_m3={10: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 20.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 5.0, (831, 10): 5.0, (100, 10): 0.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            831: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O831"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
        },
        storage={},
        warnings=[],
    )
    config = engine.Config(
        origin_warehouses=(444, 831),
        max_tasks=10,
        default_store_capacity_m3=20,
    )
    result = SimpleNamespace(
        base_rows=[],
        allocation_rows=[],
        capacity_rows=[],
        tasks_used=0,
        max_tasks=10,
        warnings=[],
    )
    apply_liquid_engine(
        result,
        catalogs,
        config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 7.0}],
        set(),
        (),
        {100: 1.0},
        {444: {10}},
        automatic_tail=False,
        forecast_horizon_days=7,
    )
    assert {row["WAREHOUSE_SOURCE"] for row in result.allocation_rows} == {444}
    assert sum(row["QUANTITY"] for row in result.allocation_rows) == 5


def test_automatic_tail_respects_selected_origins():
    catalogs = engine.Catalogs(
        volume_m3={10: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 20.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 5.0, (831, 10): 5.0, (100, 10): 0.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            831: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O831"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
        },
        storage={},
        warnings=[],
    )
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=10)
    result = SimpleNamespace(
        base_rows=[], allocation_rows=[], capacity_rows=[], tasks_used=0,
        max_tasks=10, warnings=[]
    )
    apply_liquid_engine(
        result,
        catalogs,
        config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 7.0}],
        set(),
        (),
        {100: 1.0},
        {},
        automatic_tail=True,
        automatic_tail_origins={444},
        forecast_horizon_days=7,
    )
    assert {row["WAREHOUSE_SOURCE"] for row in result.allocation_rows} == {444}
