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
        allocation_rows=[
            # Naked/Solidus ya mandó algo real a la tienda 100 (SKU distinto,
            # solo para "fondear" la tienda en el nuevo universo de Liquid).
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 999, "QUANTITY": 1}
        ],
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
    assert {row["WAREHOUSE_SOURCE"] for row in result.allocation_rows if row["RETAIL_ID"] == 10} == {444}
    assert sum(row["QUANTITY"] for row in result.allocation_rows if row["RETAIL_ID"] == 10) == 5


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
        base_rows=[],
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 999, "QUANTITY": 1}
        ],
        capacity_rows=[], tasks_used=0,
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
    assert {row["WAREHOUSE_SOURCE"] for row in result.allocation_rows if row["RETAIL_ID"] == 10} == {444}


def _make_catalogs(stock_444=6.0, store_capacity=20.0, **overrides):
    base = dict(
        volume_m3={10: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: store_capacity},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): stock_444, (100, 10): 0.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
        },
        storage={},
        warnings=[],
    )
    base.update(overrides)
    return engine.Catalogs(**base)


def _make_result(funded_destinations=(100,), **overrides):
    """``funded_destinations``: tiendas que ya recibieron unidades reales de
    un engine anterior (Naked/Solidus/etc.), simulando el nuevo universo
    restringido de Liquid. Pasa () para probar una tienda SIN fondear."""
    seed_rows = [
        {
            "WAREHOUSE_DESTINATION": destination,
            "WAREHOUSE_SOURCE": 444,
            "RETAIL_ID": 999,
            "QUANTITY": 1,
        }
        for destination in funded_destinations
    ]
    base = dict(
        base_rows=[], allocation_rows=seed_rows, capacity_rows=[], tasks_used=0,
        max_tasks=10, warnings=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_tail_threshold_is_configurable_lower_than_default():
    """Con umbral 5, un remanente de 6 NO debe entrar a la cola automática."""
    catalogs = _make_catalogs(stock_444=6.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result()
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=5,
    )
    assert len(result.allocation_rows) == 1  # solo la fila semilla (999)
    assert summary["candidate_origin_skus"] == 0
    assert summary["tail_threshold"] == 5


def test_tail_threshold_is_configurable_higher_than_default():
    """Con umbral 20, un remanente de 15 SÍ debe entrar (con el default 10 no)."""
    catalogs = _make_catalogs(stock_444=15.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result()
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=20,
    )
    assert sum(row["QUANTITY"] for row in result.allocation_rows if row["RETAIL_ID"] == 10) == 15
    assert summary["tail_threshold"] == 20


def test_tail_threshold_zero_or_negative_raises():
    catalogs = _make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result()
    try:
        apply_liquid_engine(
            result, catalogs, config, [], set(), (), {}, {},
            automatic_tail=True, forecast_horizon_days=7, tail_threshold=0,
        )
    except ValueError as exc:
        assert "umbral" in str(exc)
    else:
        raise AssertionError("debía lanzar ValueError con tail_threshold=0")


def test_skipped_no_destination_eligible_when_all_blocked():
    """Todo destino bloqueado por BLOQUEOS regional -> sin envío, motivo correcto."""
    catalogs = _make_catalogs(
        stock_444=6.0,
        blocked_products={10},
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "STORE GDL"},
        },
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result()
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=10,
    )
    assert len(result.allocation_rows) == 1  # solo la fila semilla (999)
    assert summary["skipped_no_destination_eligible"] == 1
    assert summary["skipped_capacity_full"] == 0
    assert summary["skipped_no_store"] == 1


def test_skipped_capacity_full_when_store_has_no_room():
    """Destino elegible pero sin m3 libres -> motivo distinto al de bloqueo."""
    catalogs = _make_catalogs(stock_444=6.0, store_capacity=0.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result()
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=10,
    )
    assert len(result.allocation_rows) == 1  # solo la fila semilla (999)
    assert summary["skipped_capacity_full"] == 1
    assert summary["skipped_no_destination_eligible"] == 0
    assert summary["skipped_no_store"] == 1


def test_skipped_task_limit_when_budget_exhausted():
    catalogs = _make_catalogs(stock_444=6.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=0)
    result = _make_result(tasks_used=0, max_tasks=0)
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=10,
    )
    assert len(result.allocation_rows) == 1  # solo la fila semilla (999)
    assert summary["skipped_task_limit"] == 1
    assert summary["skipped_no_store"] == 0


def test_skip_reasons_are_mutually_exclusive_categories():
    """Un mismo candidato solo debe caer en UNA de las tres categorías."""
    catalogs = _make_catalogs(stock_444=6.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result()
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=10,
    )
    # Este caso sí se envía (destino elegible, con capacidad, con tareas).
    assert any(row["RETAIL_ID"] == 10 for row in result.allocation_rows)
    total_skipped = (
        summary["skipped_no_destination_eligible"]
        + summary["skipped_capacity_full"]
        + summary["skipped_task_limit"]
    )
    assert total_skipped == 0


def test_liquid_ignores_store_with_only_a_requirement_row_no_real_shipment():
    """Una tienda con renglón en Fountain9 pero SIN asignación real de Naked/
    Solidus (p. ej. quedó en SIN RECOMENDACIÓN o CORTE POR STOCK) NO debe
    poder recibir liquidación: no está 'fondeada' de verdad ese día."""
    catalogs = _make_catalogs(stock_444=6.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    # Sin seed: la tienda 100 nunca recibió una unidad real todavía.
    result = _make_result(funded_destinations=())
    summary = apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=10,
    )
    assert result.allocation_rows == []
    assert summary["candidate_origin_skus"] == 1  # sí es candidato...
    # ...pero como ninguna tienda está fondeada, no hay destino elegible.
    assert summary["skipped_no_destination_eligible"] == 1


def test_liquid_reaches_store_once_it_receives_a_real_shipment():
    """Misma tienda, pero YA fondeada por otro SKU real -> ahora sí califica."""
    catalogs = _make_catalogs(stock_444=6.0)
    config = engine.Config(origin_warehouses=(444,), max_tasks=10)
    result = _make_result(funded_destinations=(100,))
    apply_liquid_engine(
        result, catalogs, config,
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "PREDICTED_DEMAND": 0.0}],
        set(), (), {100: 1.0}, {},
        automatic_tail=True, forecast_horizon_days=7, tail_threshold=10,
    )
    assert any(row["RETAIL_ID"] == 10 for row in result.allocation_rows)
