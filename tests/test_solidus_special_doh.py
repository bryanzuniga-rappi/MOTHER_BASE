"""Pruebas del refuerzo de Golden/Infaltable/Anchor en Solidus (apply_avl_fill
con candidate_mode='special_doh')."""

from types import SimpleNamespace

import modelo_abasto as engine
from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={10: 1.0, 20: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 100.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 100.0, (444, 20): 100.0, (100, 10): 2.0, (100, 20): 2.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
        },
        storage={},
        warnings=[],
        golden_products={(100, 10)},  # SKU 10 es Golden en la tienda 100
    )
    base.update(overrides)
    return engine.Catalogs(**base)


def make_result(**overrides) -> SimpleNamespace:
    base = dict(
        base_rows=[], allocation_rows=[], capacity_rows=[], tasks_used=0,
        max_tasks=100, warnings=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def catalog_rows(adu_10=1.0, adu_20=1.0):
    return [
        {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "ADU": adu_10},
        {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 20, "ADU": adu_20},
    ]


def test_special_doh_tops_up_golden_product_below_target():
    """SKU 10 (Golden) tiene 2 unidades, ADU=1 -> 2 DOH. Objetivo 10 DOH."""
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    golden_rows = [r for r in result.allocation_rows if r["RETAIL_ID"] == 10]
    assert golden_rows, "debió enviar refuerzo al SKU Golden"
    assert sum(r["QUANTITY"] for r in golden_rows) == 8  # (1*10) - 2
    assert summary["special_candidates"] == 1
    assert summary["cases_sent"] == 1


def test_special_doh_ignores_non_special_products():
    """SKU 20 no es Golden/Infaltable/Anchor -> no debe recibir refuerzo."""
    catalogs = make_catalogs()  # solo (100,10) está en golden_products
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert all(row["RETAIL_ID"] != 20 for row in result.allocation_rows)
    assert summary["skipped_not_special"] == 1


def test_special_doh_skips_when_already_above_target():
    """Si el DOH actual ya alcanza el objetivo, no se envía nada."""
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 50.0})
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert result.allocation_rows == []
    assert summary["skipped_doh_sufficient"] == 1


def test_special_doh_no_forced_minimum_of_three():
    """A diferencia de AVL/preventivo, no hay mínimo forzado de 3 unidades."""
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 9.0})
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    # ADU=1, objetivo 10 DOH -> falta exactamente 1 unidad (menor al mínimo
    # de 3 que sí aplica en AVL/preventivo).
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert sum(r["QUANTITY"] for r in result.allocation_rows) == 1


def test_special_doh_respects_independent_target_from_avl_doh():
    """El DOH de este modo es independiente del que usan AVL/preventivo."""
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)

    result_low = make_result()
    m.apply_avl_fill(
        result_low, catalog_rows(), catalogs, config, set(), (), 3.0,
        candidate_mode="special_doh",
    )
    units_low = sum(r["QUANTITY"] for r in result_low.allocation_rows)

    result_high = make_result()
    m.apply_avl_fill(
        result_high, catalog_rows(), catalogs, config, set(), (), 21.0,
        candidate_mode="special_doh",
    )
    units_high = sum(r["QUANTITY"] for r in result_high.allocation_rows)

    assert units_high > units_low


def test_special_doh_reason_and_cut_labels():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert result.allocation_rows[0]["PLANNING_REASON"] == m.PLANNING_REASON_SPECIAL_DOH
    assert result.base_rows[0]["TIPO_DE_CORTE"] == m.SPECIAL_DOH_CUT
    assert result.base_rows[0]["REGLA_DEMANDA"] == "REFUERZO_ESPECIALES_DOH"
    assert m.SPECIAL_DOH_CUT in m.BREAKDOWN_ORDER


def test_special_doh_respects_infaltable_and_anchor_flags_too():
    catalogs = make_catalogs(
        golden_products=set(),
        infaltable_products={(100, 10)},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert any(r["RETAIL_ID"] == 10 for r in result.allocation_rows)

    catalogs2 = make_catalogs(golden_products=set(), anchor_products={(100, 10)})
    result2 = make_result()
    m.apply_avl_fill(
        result2, catalog_rows(), catalogs2, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert any(r["RETAIL_ID"] == 10 for r in result2.allocation_rows)


def test_special_doh_respects_already_served_keys():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
        excluded_keys={(100, 10)},
    )
    assert result.allocation_rows == []
    assert summary["skipped_already_served"] == 1


def test_invalid_candidate_mode_still_raises():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    try:
        m.apply_avl_fill(
            result, catalog_rows(), catalogs, config, set(), (), 10.0,
            candidate_mode="not_a_real_mode",
        )
    except ValueError as exc:
        assert "inválido" in str(exc)
    else:
        raise AssertionError("debía lanzar ValueError con un modo inválido")
