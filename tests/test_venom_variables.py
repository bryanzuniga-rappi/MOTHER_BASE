"""Venom: variables DDMRP, SKUs específicos por origen y tope de capacidad
propio (independiente del que usan los demás engines)."""

from datetime import date

import modelo_abasto as engine
import modules.les_enfants_terribles as m
from engines.venom_engine import compute_ddmrp_zones, apply_venom_engine
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes
from tests.test_e2e_kazuhira import _bulk_lines
from tests.test_venom_engine import make_catalogs, make_result

# ADU 2, lead time 5, stock destino 5, golden (100, 10):
# roja 7.5 · amarilla 17.5 · verde 22.5 · NFP = 5 - 10 = -5  =>  pide 28
CATALOG_LOOKUP = {(100, 10): {"adu": 2.0, "list_type": ""}}


def venom(catalogs=None, result=None, **overrides):
    catalogs = catalogs or make_catalogs()
    result = result or make_result()
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    kwargs = dict(
        venom_origins=(444,), venom_destinations=(100,), section_types={"IS_GOLDEN"},
        lead_time_days=5, consider_current_planning=True, catalog_lookup=CATALOG_LOOKUP,
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    kwargs.update(overrides)
    summary = apply_venom_engine(result, catalogs, config, **kwargs)
    sent = {(r["WAREHOUSE_DESTINATION"], r["RETAIL_ID"]): r["QUANTITY"] for r in result.allocation_rows}
    return summary, sent, result


def raises(**overrides):
    try:
        venom(**overrides)
    except ValueError:
        return True
    return False


# --- zonas -----------------------------------------------------------------------------------

def test_default_parameters_keep_the_current_behaviour():
    assert venom()[1][(100, 10)] == 28


def test_order_cycle_raises_the_green_zone():
    assert compute_ddmrp_zones(2, 5)["green_zone"] == 5
    assert compute_ddmrp_zones(2, 5, order_cycle_days=10)["green_zone"] == 20


def test_ltf_and_vf_resize_the_buffer():
    assert venom(ltf=1.0)[1][(100, 10)] == 40      # roja 15 · amarilla 10 · verde 10
    assert venom(vf=0.0)[1][(100, 10)] == 25       # roja 5 (sin seguridad)


def test_minimum_order_quantity_is_the_floor_of_the_green_zone():
    assert venom(min_green_units=10)[1][(100, 10)] == 33


def test_order_cycle_changes_the_quantity_through_the_green_zone():
    assert venom(order_cycle_days=10)[1][(100, 10)] == 43       # verde 20


# --- disparador ---------------------------------------------------------------------------------

def _with_stock(on_hand):
    return make_catalogs(stock_base={(444, 10): 100.0, (100, 10): on_hand, (444, 20): 50.0})


def test_trigger_zone_decides_when_to_reorder():
    # on-hand 22 => NFP 12: entre la roja (7.5) y la amarilla (17.5)
    c = _with_stock(22.0)
    assert venom(c, trigger_zone="yellow")[1][(100, 10)] == 11
    assert venom(c, trigger_zone="red")[1] == {}
    assert venom(c, trigger_zone="green")[1][(100, 10)] == 11


def test_green_trigger_always_tops_up_a_buffer_the_yellow_trigger_considers_healthy():
    c = _with_stock(30.0)                            # NFP 20: sobre la amarilla, bajo la verde
    assert venom(c, trigger_zone="yellow")[1] == {}
    assert venom(c, trigger_zone="green")[1][(100, 10)] == 3


# --- NFP -----------------------------------------------------------------------------------------

def test_qualified_demand_can_be_left_out_of_the_nfp():
    assert venom(subtract_lead_time_demand=False)[1][(100, 10)] == 18    # NFP = 5, no -5


def test_incoming_counts_as_on_order_when_enabled():
    c = make_catalogs(incoming_stock={(100, 10): 10.0})
    assert venom(c)[1][(100, 10)] == 28                                  # apagado (legado)
    assert venom(c, consider_incoming=True)[1][(100, 10)] == 18


def test_shipping_multiple_rounds_up():
    assert venom(shipping_multiple=5)[1][(100, 10)] == 30
    assert venom(shipping_multiple=7)[1][(100, 10)] == 28


def test_invalid_parameters_are_rejected():
    assert raises(ltf=0) and raises(ltf=1.5) and raises(vf=-0.1) and raises(vf=1.1)
    assert raises(order_cycle_days=-1) and raises(trigger_zone="blue") and raises(shipping_multiple=0)
    assert not raises()


def test_detail_reports_the_real_factors():
    _, _, result = venom(ltf=0.8, vf=0.2)
    detail = result.base_rows[0]["DETALLE_MOTIVO"]
    assert "LTF=0.8" in detail and "VF=0.2" in detail


# --- KVI -------------------------------------------------------------------------------------------

def test_kvi_is_a_section_type():
    c = make_catalogs(golden_products=set(), kvi_products={(100, 10)})
    assert venom(c, section_types={"IS_GOLDEN"})[1] == {}
    assert venom(c, section_types={"IS_KVI"})[1][(100, 10)] == 28


# --- SKUs específicos por origen --------------------------------------------------------------------

LOOKUP_20 = {(100, 10): {"adu": 2.0, "list_type": ""}, (100, 20): {"adu": 1.0, "list_type": ""}}


def test_manual_sku_is_evaluated_with_ddmrp_without_any_section_type():
    summary, sent, _ = venom(
        section_types=set(), catalog_lookup=LOOKUP_20,
        manual_skus_by_origin={444: {20}},
    )
    assert sent == {(100, 20): 17}            # ADU 1, LT 5 => 17
    assert summary["manual_pairs"] == 1


def test_manual_sku_is_supplied_only_from_the_origin_that_lists_it():
    c = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 5.0, (444, 20): 50.0, (831, 20): 50.0})
    _, sent, result = venom(
        c, venom_origins=(444, 831), section_types=set(), catalog_lookup=LOOKUP_20,
        manual_skus_by_origin={831: {20}},
    )
    assert sent == {(100, 20): 17}
    assert {r["WAREHOUSE_SOURCE"] for r in result.allocation_rows} == {831}


def test_manual_sku_listed_for_an_origin_without_stock_sends_nothing():
    c = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 5.0, (444, 20): 50.0, (831, 20): 0.0})
    summary, sent, _ = venom(
        c, venom_origins=(444, 831), section_types=set(), catalog_lookup=LOOKUP_20,
        manual_skus_by_origin={831: {20}},
    )
    assert sent == {} and summary["skipped_no_stock"] == 1


def test_manual_skus_add_to_the_section_universe_by_default():
    _, sent, _ = venom(catalog_lookup=LOOKUP_20, manual_skus_by_origin={444: {20}})
    assert set(sent) == {(100, 10), (100, 20)}


def test_only_manual_skus_ignores_the_section_types():
    _, sent, _ = venom(catalog_lookup=LOOKUP_20, manual_skus_by_origin={444: {20}}, only_manual_skus=True)
    assert set(sent) == {(100, 20)}


def test_manual_sku_without_adu_is_counted_not_silently_dropped():
    summary, sent, _ = venom(
        section_types=set(), manual_skus_by_origin={444: {20}},      # 20 no está en el catálogo
    )
    assert sent == {} and summary["skipped_no_adu"] == 1


def test_manual_skus_of_an_unused_origin_are_ignored():
    _, sent, _ = venom(
        section_types=set(), catalog_lookup=LOOKUP_20, manual_skus_by_origin={831: {20}},
    )                                                                 # Venom solo usa el 444
    assert sent == {}


# --- tope de capacidad propio --------------------------------------------------------------------------

def cap_catalogs(capacity):
    return make_catalogs(store_capacity={100: capacity})                # 0.01 m³ por unidad


def test_without_the_cap_venom_is_unconstrained():
    assert venom(cap_catalogs(0.1))[1][(100, 10)] == 28


def test_cap_limits_venom_to_the_store_capacity():
    summary, sent, _ = venom(cap_catalogs(0.1), cap_to_store_capacity=True)
    assert sent[(100, 10)] == 10                       # 0.1 m³ / 0.01 = 10 unidades
    assert summary["units_cut_by_capacity"] == 18


def test_cap_is_shared_across_venoms_own_lines_of_the_same_store():
    summary, sent, _ = venom(
        cap_catalogs(0.1), cap_to_store_capacity=True, section_types=set(),
        catalog_lookup=LOOKUP_20, manual_skus_by_origin={444: {10, 20}},
    )
    assert sum(sent.values()) == 10                    # el 2.º SKU ya no cabe
    assert summary["skipped_capacity_cap"] == 1


def test_venom_capacity_is_independent_from_what_other_engines_already_used():
    """Tienda con 10 de capacidad y 9 ya usados por otros engines: Venom puede
    usar sus propios 10 (no el 1 que sobra) y no toca el ledger compartido."""
    result = make_result(capacity_rows=[{
        "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_NAME": "T", "CITY": "CDMX",
        "CAPACIDAD_M3": 0.1, "M3_CONTABILIZADO_CAPACIDAD": 0.09,
        "M3_TOTAL_ASIGNADO_INCLUYE_GOLDEN": 0.09, "CAPACIDAD_CERRADA": False,
        "CAPACIDAD_SUPERADA_POR_LINEA": False,
    }])
    _, sent, result = venom(cap_catalogs(0.1), result=result, cap_to_store_capacity=True)
    assert sent[(100, 10)] == 10                       # no 1
    assert result.capacity_rows[0]["M3_CONTABILIZADO_CAPACIDAD"] == 0.09   # intacto


def test_cap_report_columns_show_venoms_own_ledger():
    _, _, result = venom(cap_catalogs(0.1), cap_to_store_capacity=True)
    row = result.base_rows[0]
    assert row["M3_CAPACIDAD_ANTES"] == 0 and abs(row["M3_CAPACIDAD_DESPUES"] - 0.1) < 1e-9
    assert row["PASA_CAPACIDAD"] is False and "Tope de capacidad propio" in row["DETALLE_MOTIVO"]


# --- Kazuhira solo ve el remanente de los demás engines ---------------------------------------------------

STORES = {100: "CDMX"}
SKUS = [10, 11, 12]


def pipeline(**overrides):
    kwargs = dict(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("plan.csv", build_plan_csv_bytes([(100, 10, 4)]))],
        database_bytes=build_workbook_bytes(STORES, SKUS, extra_rows={"CAP_RECIBO": [(100, 0.01)]}),
        origins=(444,), max_tasks=1000, run_date=date(2026, 10, 5),
        include_insumos=False, enable_closed_stores_rule=False, block_fruver_811=False,
        block_off_schedule_shipments=False, minimum_positive_quantity=4,
        include_venom_engine=True, venom_origins=(444,), venom_destinations=(100,),
        venom_section_types=frozenset(), venom_manual_skus_by_origin={444: {11}},
        include_kazuhira_engine=True,
    )
    kwargs.update(overrides)
    run = m.execute_planning(**kwargs)
    return {sku: qty for (_s, sku), qty in _bulk_lines(run).items()}, run


def test_kazuhira_sees_only_what_the_other_engines_left_not_what_venom_used():
    """Capacidad 5 unidades: Naked usa 4. Venom (con su tope) usa SUS 5 aparte;
    a Kazuhira le queda 1 unidad, no 0."""
    sent, run = pipeline(venom_cap_to_store_capacity=True)
    assert sent[10] == 4
    assert sent[11] == 5                      # los 5 propios de Venom, no el 1 que sobraba
    assert sent[12] == 1                      # Kazuhira: 5 - 4 (Naked), sin contar a Venom
    assert run["venom"]["cap_to_store_capacity"] is True


def test_without_the_venom_cap_kazuhira_is_not_affected_either():
    sent, _ = pipeline(venom_cap_to_store_capacity=False)
    assert sent[11] == 10 and sent[12] == 1   # Venom sin tope (zona verde 4 => 10); Kazuhira igual: 1


def test_pipeline_passes_venom_parameters_to_the_engine():
    _, run = pipeline(venom_ltf=0.8, venom_vf=0.2, venom_trigger_zone="green",
                      venom_shipping_multiple=2, venom_order_cycle_days=3.0)
    v = run["venom"]
    assert (v["ltf"], v["vf"], v["trigger_zone"], v["shipping_multiple"], v["order_cycle_days"]) == (
        0.8, 0.2, "green", 2, 3.0)


def test_parameters_text_summarizes_the_run():
    summary, _, _ = venom(ltf=0.8, vf=0.2, order_cycle_days=3.0, shipping_multiple=5,
                          cap_to_store_capacity=True, trigger_zone="green")
    text = m.venom_parameters_text(summary)
    for expected in ("Lead time 5 d", "LTF 0.8", "VF 0.2", "techo verde", "ciclo de pedido 3 d",
                     "múltiplo 5", "sin incoming", "tope de capacidad propio"):
        assert expected in text, expected
