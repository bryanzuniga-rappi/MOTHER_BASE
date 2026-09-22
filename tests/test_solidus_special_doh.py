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
    """SKU 20 no es Golden/Infaltable/Anchor -> no debe recibir refuerzo.
    Con el rediseño (universo desde GOLDEN_INFALTABLES_ANCHOR, no CATALOGO),
    SKU 20 ni siquiera entra al pool de candidatos."""
    catalogs = make_catalogs()  # solo (100,10) está en golden_products
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert all(row["RETAIL_ID"] != 20 for row in result.allocation_rows)


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


# --- Rediseño: universo desde GOLDEN_INFALTABLES_ANCHOR, on-top y cascada --

def test_special_doh_candidate_exists_without_catalogo_row():
    """Un SKU Golden en una tienda que NO tiene fila en CATALOGO para esa
    tienda debe seguir evaluándose (antes era invisible por completo)."""
    catalogs = make_catalogs(
        stock_base={(444, 30): 100.0, (100, 30): 2.0},
        golden_products={(100, 30)},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    # catalog_rows() no incluye el SKU 30 en absoluto.
    summary = m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    assert any(r["RETAIL_ID"] == 30 for r in result.allocation_rows)
    assert summary["special_candidates_no_adu"] == 1


def test_special_doh_on_top_over_prior_engine_assignment():
    """AVL ya mandó 2 unidades esta corrida (stock inicial 2 + AVL 2 = 4).
    Con ADU=1 y objetivo 10 DOH, el refuerzo debe mandar solo 6 (10-4), no
    10 de nuevo ni saltarse el caso por 'ya recibió algo'."""
    catalogs = make_catalogs()  # SKU 10 Golden, stock inicial 2, ADU=1
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result(
        allocation_rows=[
            {
                "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444,
                "RETAIL_ID": 10, "QUANTITY": 2,
            }
        ]
    )
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    refuerzo_rows = [
        r for r in result.allocation_rows
        if r["RETAIL_ID"] == 10 and r.get(m.PLANNING_REASON_COLUMN) == m.PLANNING_REASON_SPECIAL_DOH
    ]
    assert sum(r["QUANTITY"] for r in refuerzo_rows) == 6


def test_special_doh_never_touches_fountain9_recommended_even_with_prior_assignment():
    """Aunque AVL ya haya mandado algo, si Fountain9 SÍ pidió esa tienda-SKU
    (excluded_keys), el refuerzo nunca la toca — la señal de Fountain9 manda
    siempre sobre cualquier on-top."""
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result(
        allocation_rows=[
            {
                "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444,
                "RETAIL_ID": 10, "QUANTITY": 2,
            }
        ]
    )
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
        excluded_keys={(100, 10)},
    )
    refuerzo_rows = [
        r for r in result.allocation_rows
        if r.get(m.PLANNING_REASON_COLUMN) == m.PLANNING_REASON_SPECIAL_DOH
    ]
    assert refuerzo_rows == []


def test_special_doh_uses_city_average_adu_when_own_missing():
    """SKU 40 en tienda 100 no tiene ADU propio, pero la tienda 200 (misma
    ciudad) sí tiene ADU=2.0 para ese SKU -> debe usarse ese promedio."""
    catalogs = make_catalogs(
        stock_base={(444, 40): 100.0, (100, 40): 0.0, (200, 40): 5.0},
        store_capacity={100: 100.0, 200: 100.0},
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
            200: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE2"},
        },
        golden_products={(100, 40)},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    rows_with_city_mirror = catalog_rows() + [
        {"WAREHOUSE_DESTINATION": 200, "RETAIL_ID": 40, "ADU": 2.0},
    ]
    m.apply_avl_fill(
        result, rows_with_city_mirror, catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    refuerzo_rows = [r for r in result.allocation_rows if r["RETAIL_ID"] == 40]
    assert refuerzo_rows, "debió usar el ADU promedio de la ciudad"
    # objetivo = ceil(2.0 * 10) = 20; posición inicial = 0 -> manda 20
    assert sum(r["QUANTITY"] for r in refuerzo_rows) == 20


def test_special_doh_no_adu_anywhere_falls_back_to_minimum_3():
    """Ninguna tienda de ninguna ciudad tiene ADU para el SKU -> mínimo
    operativo de 3 unidades, sin piso de DOH."""
    catalogs = make_catalogs(
        stock_base={(444, 50): 100.0, (100, 50): 0.0},
        golden_products={(100, 50)},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    refuerzo_rows = [r for r in result.allocation_rows if r["RETAIL_ID"] == 50]
    assert sum(r["QUANTITY"] for r in refuerzo_rows) == 3


def test_special_doh_no_adu_minimum_3_accounts_for_prior_assignment():
    """Mismo caso sin ADU, pero ya se le asignó 1 unidad antes -> el mínimo
    de 3 se completa con solo 2 más, no 3 de nuevo."""
    catalogs = make_catalogs(
        stock_base={(444, 50): 100.0, (100, 50): 0.0},
        golden_products={(100, 50)},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result(
        allocation_rows=[
            {
                "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444,
                "RETAIL_ID": 50, "QUANTITY": 1,
            }
        ]
    )
    m.apply_avl_fill(
        result, catalog_rows(), catalogs, config, set(), (), 10.0,
        candidate_mode="special_doh",
    )
    refuerzo_rows = [
        r for r in result.allocation_rows
        if r["RETAIL_ID"] == 50 and r.get(m.PLANNING_REASON_COLUMN) == m.PLANNING_REASON_SPECIAL_DOH
    ]
    assert sum(r["QUANTITY"] for r in refuerzo_rows) == 2


def test_avl_stockout_mode_still_uses_only_own_catalogo_adu_when_present():
    """Regresión: AVL/Preventivo siguen funcionando igual cuando el ADU
    propio existe — la cascada no debe alterar el caso normal."""
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 0.0})
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    m.apply_avl_fill(
        result, catalog_rows(adu_10=2.0), catalogs, config, set(), (), 5.0,
        candidate_mode="stockout",
    )
    avl_rows = [r for r in result.allocation_rows if r["RETAIL_ID"] == 10]
    assert sum(r["QUANTITY"] for r in avl_rows) == 10  # ceil(2.0*5)=10


def test_resolve_adu_with_city_fallback_direct():
    catalogs = make_catalogs(
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "A"},
            200: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "B"},
            300: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "C"},
        },
    )
    rows = [
        {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 99, "ADU": 0.0},  # sin propio
        {"WAREHOUSE_DESTINATION": 200, "RETAIL_ID": 99, "ADU": 4.0},
        {"WAREHOUSE_DESTINATION": 300, "RETAIL_ID": 99, "ADU": 100.0},  # otra ciudad
    ]
    resolved, source = m.resolve_adu_with_city_fallback(rows, catalogs)
    assert resolved[(100, 99)] == 4.0  # promedio de CDMX (solo la 200 aporta)
    assert source[(100, 99)] == "PROMEDIO_CIUDAD"
    assert resolved[(200, 99)] == 4.0
    assert source[(200, 99)] == "PROPIO"
    assert resolved[(300, 99)] == 100.0
    assert source[(300, 99)] == "PROPIO"


# --- Check de salud post-corrida (punto D) --------------------------------

def test_health_check_flags_store_below_target_doh():
    catalogs = make_catalogs(
        stock_base={(100, 10): 5.0},  # solo 5 unidades, ADU=1 -> 5 DOH
        golden_products={(100, 10)},
    )
    result = make_result()
    check = m.build_golden_infaltable_anchor_health_check(
        result, catalogs, 10.0, catalog_rows()
    )
    assert check["enabled"] is True
    assert check["checked"] == 1
    assert len(check["below_target"]) == 1
    row = check["below_target"][0]
    assert row["WAREHOUSE_DESTINATION"] == 100
    assert row["RETAIL_ID"] == 10
    assert row["DOH_FINAL"] == 5.0
    assert row["UNIDADES_FALTANTES"] == 5  # (10-5)*1


def test_health_check_accounts_for_allocations_from_any_engine():
    """Si Shalashaska/Liquid/Venom ya mandaron algo después, el check debe
    verlo reflejado en la posición final — no solo el stock inicial."""
    catalogs = make_catalogs(
        stock_base={(100, 10): 5.0},
        golden_products={(100, 10)},
    )
    result = make_result(
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10, "QUANTITY": 5},
        ]
    )
    check = m.build_golden_infaltable_anchor_health_check(
        result, catalogs, 10.0, catalog_rows()
    )
    # posición final = 5 (inicial) + 5 (asignado) = 10 -> DOH=10, ya no baja
    assert check["below_target"] == []


def test_health_check_passes_when_at_or_above_target():
    catalogs = make_catalogs(
        stock_base={(100, 10): 50.0},  # ADU=1 -> 50 DOH, muy por encima de 10
        golden_products={(100, 10)},
    )
    result = make_result()
    check = m.build_golden_infaltable_anchor_health_check(
        result, catalogs, 10.0, catalog_rows()
    )
    assert check["below_target"] == []


def test_health_check_skips_combinations_without_any_adu():
    catalogs = make_catalogs(
        stock_base={(100, 60): 1.0},
        golden_products={(100, 60)},
    )
    result = make_result()
    # SKU 60 no aparece en catalog_rows() ni en ninguna tienda -> sin ADU.
    check = m.build_golden_infaltable_anchor_health_check(
        result, catalogs, 10.0, catalog_rows()
    )
    assert check["no_adu"] == 1
    assert check["below_target"] == []


def test_health_check_disabled_when_no_golden_infaltable_anchor_universe():
    catalogs = make_catalogs(golden_products=set())
    result = make_result()
    check = m.build_golden_infaltable_anchor_health_check(
        result, catalogs, 10.0, catalog_rows()
    )
    assert check["enabled"] is False
    assert check["checked"] == 0
