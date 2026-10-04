"""Pruebas de Kazuhira Engine (apply_avl_fill con candidate_mode="kazuhira"):
garantía total de cobertura de quiebres, con fallback de Duration/Lead Time
y dos toggles de bypass (presupuesto de tareas y capacidad de tienda)."""

from types import SimpleNamespace

import modelo_abasto as engine
from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={10: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1, 200: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 1000.0, 200: 1000.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 1000.0, (100, 10): 0.0, (200, 10): 0.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "S100"},
            200: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "S200"},
        },
        storage={},
        warnings=[],
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


def catalog_rows(*destinations, adu=1.0):
    return [
        {"WAREHOUSE_DESTINATION": d, "RETAIL_ID": 10, "ADU": adu}
        for d in destinations
    ]


CONFIG = engine.Config(origin_warehouses=(444,), max_tasks=100)


def run_kazuhira(result, rows, catalogs, config=CONFIG, **kwargs):
    defaults = dict(
        candidate_mode="kazuhira",
        excluded_keys=set(),
        duration_mode_by_store={100: 5.0, 200: 5.0},
        lead_time_mode_by_store={100: 3.0, 200: 3.0},
    )
    defaults.update(kwargs)
    return m.apply_avl_fill(
        result, rows, catalogs, config, set(), (), 1.0, **defaults
    )


# --- cobertura base --------------------------------------------------------

def test_covers_stockout_with_same_formula_as_no_fountain9():
    result = make_result()
    summary = run_kazuhira(result, catalog_rows(100, adu=2.0), make_catalogs())
    assert summary["units_added"] == 16  # 2.0 x (5+3)
    assert summary["cases_sent"] == 1


def test_labels_are_kazuhira_specific():
    result = make_result()
    run_kazuhira(result, catalog_rows(100, adu=2.0), make_catalogs())
    assert result.base_rows[-1]["TIPO_DE_CORTE"] == m.KAZUHIRA_CUT
    assert result.base_rows[-1]["REGLA_DEMANDA"] == m.KAZUHIRA_REGLA_DEMANDA
    assert result.allocation_rows[-1][m.PLANNING_REASON_COLUMN] == m.PLANNING_REASON_KAZUHIRA


def test_covers_regardless_of_fountain9_history():
    """Punto central: excluded_keys vacío => cubre aunque Fountain9 haya
    tenido (y recomendado) la tienda-SKU, mientras siga en quiebre."""
    result = make_result()
    summary = run_kazuhira(
        result, catalog_rows(100), make_catalogs(), excluded_keys=set()
    )
    assert summary["cases_sent"] == 1


def test_already_assigned_this_run_is_not_shipped_again():
    result = make_result(
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10, "QUANTITY": 5}
        ]
    )
    summary = run_kazuhira(result, catalog_rows(100), make_catalogs())
    assert summary["cases_sent"] == 0


def test_healthy_stock_is_not_covered():
    catalogs = make_catalogs(stock_base={(444, 10): 1000.0, (100, 10): 50.0})
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["cases_sent"] == 0


# --- fallback de Duration / Lead Time --------------------------------------

def test_fallback_used_when_store_has_no_own_duration_data():
    result = make_result()
    summary = run_kazuhira(
        result,
        catalog_rows(100, adu=1.0),
        make_catalogs(),
        duration_mode_by_store={},
        lead_time_mode_by_store={},
        fallback_duration=6.0,
        fallback_lead_time=4.0,
    )
    assert summary["units_added"] == 10  # 1.0 x (6+4)
    assert "promedio" in result.base_rows[-1]["DETALLE_MOTIVO"] or "país" in result.base_rows[-1]["DETALLE_MOTIVO"]


def test_no_fallback_provided_skips_like_no_fountain9():
    summary = run_kazuhira(
        make_result(),
        catalog_rows(100),
        make_catalogs(),
        duration_mode_by_store={},
        lead_time_mode_by_store={},
    )
    assert summary["cases_sent"] == 0
    assert summary["skipped_no_duration_data"] == 1


def test_no_fountain9_mode_ignores_fallback_still_skips():
    """El fallback es exclusivo de Kazuhira — Cobertura sin Fountain9 sigue
    saltándose tiendas sin dato propio."""
    summary = run_kazuhira(
        make_result(),
        catalog_rows(100),
        make_catalogs(),
        candidate_mode="no_fountain9_coverage",
        duration_mode_by_store={},
        lead_time_mode_by_store={},
        fallback_duration=6.0,
        fallback_lead_time=4.0,
    )
    assert summary["cases_sent"] == 0


# --- bypass de presupuesto de tareas ---------------------------------------

def test_respects_task_budget_by_default():
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    result = make_result(tasks_used=1)
    summary = run_kazuhira(result, catalog_rows(100), make_catalogs(), config)
    assert summary["cases_sent"] == 0


def test_ignore_task_budget_covers_even_when_exhausted():
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    result = make_result(tasks_used=1)
    summary = run_kazuhira(
        result, catalog_rows(100, 200), make_catalogs(), config,
        ignore_task_budget=True,
    )
    assert summary["cases_sent"] == 2
    assert result.tasks_used == 3  # excede el máximo de 1, a propósito


# --- bypass de capacidad de tienda -----------------------------------------

def test_respects_store_capacity_by_default():
    catalogs = make_catalogs(store_capacity={100: 0.5, 200: 1000.0})
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["cases_sent"] == 0
    assert summary["skipped_capacity"] == 1


def test_ignore_store_capacity_ships_full_target_anyway():
    catalogs = make_catalogs(store_capacity={100: 0.5, 200: 1000.0})
    result = make_result()
    summary = run_kazuhira(
        result, catalog_rows(100, adu=2.0), catalogs, ignore_store_capacity=True
    )
    assert summary["units_added"] == 16
    # La excepción queda visible en el reporte de capacidad:
    row = result.capacity_rows[0]
    assert row["M3_CONTABILIZADO_CAPACIDAD"] > row["CAPACIDAD_M3"]


def test_ignore_store_capacity_does_not_ignore_origin_stock():
    """Los bypass no inventan stock: sin stock en CEDIS no se manda nada."""
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    summary = run_kazuhira(
        make_result(), catalog_rows(100), catalogs,
        ignore_task_budget=True, ignore_store_capacity=True,
    )
    assert summary["cases_sent"] == 0
    assert summary["skipped_no_source_stock"] == 1


def test_bypass_flags_have_no_effect_on_other_modes():
    """Solo Kazuhira honra los bypass en la práctica porque es el único
    que los recibe de quien llama — pero si otro modo los recibiera, la
    firma no debe romper el modo base."""
    summary = m.apply_avl_fill(
        make_result(), catalog_rows(100), make_catalogs(), CONFIG, set(), (), 1.0,
        candidate_mode="stockout",
    )
    assert summary["mode"] == "stockout"


# --- atribución en tablas de breakdown --------------------------------------

def test_kazuhira_attributed_to_its_own_engine():
    assert m.attribute_engine(m.KAZUHIRA_CUT) == "Kazuhira"


def test_kazuhira_cut_registered_in_breakdown_order():
    assert m.KAZUHIRA_CUT in m.BREAKDOWN_ORDER


# --- barrido de universo con Kazuhira activo --------------------------------

def test_sweep_labels_remaining_stockout_as_post_kazuhira_when_active():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=True
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT


def test_sweep_keeps_sin_evaluar_label_when_kazuhira_inactive():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=False
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_UNCOVERED_CUT


def test_sweep_healthy_label_unaffected_by_kazuhira():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 20.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=True
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_HEALTHY_CUT


def test_post_kazuhira_cut_appears_in_cuts_detail():
    result = SimpleNamespace(
        base_rows=[{
            "WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10,
            "CANTIDAD_OBJETIVO": 0, "CANTIDAD_ASIGNADA": 0,
            "TIPO_DE_CORTE": m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT,
        }]
    )
    causales = {r["CAUSAL"] for r in m.build_cuts_detail_rows(result)}
    assert m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT in causales


# --- disparador por DOH (stock + incoming + asignado) ------------------------

def _stock(dest_stock, origin=1000.0):
    return make_catalogs(stock_base={(444, 10): origin, (100, 10): dest_stock})


def test_triggers_when_stock_positive_but_under_one_doh():
    # stock 0.5 con ADU 1 => 0.5 DOH < 1
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=1.0), _stock(0.5))
    assert summary["cases_sent"] == 1


def test_does_not_trigger_at_or_above_one_doh():
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=1.0), _stock(1.0))
    assert summary["cases_sent"] == 0
    assert summary["skipped_doh_sufficient"] == 1


def test_incoming_counts_toward_doh_and_can_suppress_trigger():
    catalogs = _stock(0.0)
    catalogs.incoming_stock[(100, 10)] = 2.0  # 2 DOH con ADU 1
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=1.0), catalogs)
    assert summary["cases_sent"] == 0


def test_insufficient_incoming_still_triggers_and_is_subtracted():
    catalogs = _stock(0.0)
    catalogs.incoming_stock[(100, 10)] = 0.4  # < 1 DOH
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=2.0), catalogs)
    # ADU 2 x (5+3) - 0.4 = 15.6 -> 16
    assert summary["units_added"] == 16


def test_already_assigned_units_count_as_position_not_exclusion():
    """Una unidad enviada por otro engine con ADU 5 deja 0.2 DOH: Kazuhira
    debe completar, no darse por servido."""
    result = make_result(allocation_rows=[{
        "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444,
        "RETAIL_ID": 10, "QUANTITY": 1,
    }])
    summary = run_kazuhira(result, catalog_rows(100, adu=5.0), _stock(0.0))
    assert summary["cases_sent"] == 1
    # 5 x (5+3) - 0 - 0 - 1 ya asignada = 39
    assert summary["units_added"] == 39


def test_missing_stock_row_is_treated_as_zero():
    catalogs = make_catalogs(stock_base={(444, 10): 1000.0})  # sin (100, 10)
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["cases_sent"] == 1
    assert summary["missing_stock_treated_as_zero"] == 1


def test_missing_stock_row_still_skipped_by_no_fountain9_mode():
    catalogs = make_catalogs(stock_base={(444, 10): 1000.0})
    summary = run_kazuhira(
        make_result(), catalog_rows(100), catalogs,
        candidate_mode="no_fountain9_coverage",
    )
    assert summary["cases_sent"] == 0
    assert summary["skipped_missing_stock"] == 1


# --- universo de tiendas: Fountain9 + SCHEDULE de hoy -------------------------

def test_allowed_destinations_restricts_kazuhira():
    summary = run_kazuhira(
        make_result(), catalog_rows(100, 200), make_catalogs(),
        allowed_destinations={100},
    )
    assert summary["cases_sent"] == 1
    assert summary["skipped_outside_universe"] == 1


def test_scheduled_destinations_today_uses_run_weekday_and_selected_origins():
    catalogs = make_catalogs(
        schedule_days={
            (100, 444): frozenset({"LUNES", "MARTES"}),
            (200, 444): frozenset({"MARTES"}),
            (300, 831): frozenset({"LUNES"}),  # origen no seleccionado
        },
        run_weekday_norm="LUNES",
    )
    assert m.scheduled_destinations_today(catalogs, (444,)) == {100}


def test_scheduled_destinations_ignores_the_schedule_block_toggle():
    catalogs = make_catalogs(
        schedule_days={(100, 444): frozenset({"LUNES"})},
        run_weekday_norm="LUNES",
        schedule_block_enabled=False,
    )
    assert m.scheduled_destinations_today(catalogs, (444,)) == {100}


def test_planned_store_universe_unions_fountain9_and_schedule():
    catalogs = make_catalogs(
        schedule_days={(200, 444): frozenset({"LUNES"})}, run_weekday_norm="LUNES"
    )
    universe = m.build_planned_store_universe(
        [(100, 10), (100, 11)], catalogs, (444,)
    )
    assert universe["stores"] == {100, 200}
    assert universe["from_fountain9"] == {100}
    assert universe["schedule_only"] == {200}


def test_sweep_restricted_to_planned_universe():
    catalogs = make_catalogs(stock_base={(100, 10): 0.0, (200, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100, 200), catalogs, set(), allowed_destinations={100}
    )
    assert [r["WAREHOUSE_DESTINATION"] for r in rows] == [100]
