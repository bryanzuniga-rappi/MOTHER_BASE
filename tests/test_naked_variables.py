"""Variables de Naked: reglas de hardcode individuales, umbrales de net
transfer, piso mínimo y columnas adicionales de MOV."""

from datetime import date

import modules.les_enfants_terribles as m
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes
from tests.test_e2e_kazuhira import _bulk_lines

STORES = {100: "CDMX"}
SKUS = [10, 11]

# (tienda, sku, mov, demanda, opening, net_transfer)
ZERO_TOTAL = (100, 10, 0, 0, 0, 0)            # forecast y opening en cero
BELOW_DEMAND = (100, 10, 0, 5, 0, 0)          # opening < demanda
LOW_NET_TRANSFER = (100, 10, 0, 2, 5, 0)      # net transfer bajo, stock bajo


def run_planning(plan_rows, *, extra_mov_column=None, **overrides):
    kwargs = dict(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("plan.csv", build_plan_csv_bytes(plan_rows, extra_mov_column))],
        database_bytes=build_workbook_bytes(STORES, SKUS),
        origins=(444,),
        max_tasks=1000,
        run_date=date(2026, 10, 5),
        include_insumos=False,
        enable_closed_stores_rule=False,
        block_fruver_811=False,
        block_off_schedule_shipments=False,
        minimum_positive_quantity=4,
    )
    kwargs.update(overrides)
    return m.execute_planning(**kwargs)


def sent(run, key=(100, 10)):
    return _bulk_lines(run).get(key, 0)


# --- 3 reglas de hardcode por separado ---------------------------------------------------

def test_each_hardcode_rule_sends_the_minimum_by_default():
    for row in (ZERO_TOTAL, BELOW_DEMAND, LOW_NET_TRANSFER):
        assert sent(run_planning([row])) == 4, row


def test_zero_total_rule_toggle():
    assert sent(run_planning([ZERO_TOTAL], hardcode_zero_total=False)) == 0
    assert sent(run_planning([BELOW_DEMAND], hardcode_zero_total=False)) == 4   # las otras siguen


def test_inventory_below_demand_rule_toggle():
    assert sent(run_planning([BELOW_DEMAND], hardcode_inventory_below_demand=False)) == 0
    assert sent(run_planning([ZERO_TOTAL], hardcode_inventory_below_demand=False)) == 4


def test_low_net_transfer_rule_toggle():
    assert sent(run_planning([LOW_NET_TRANSFER], hardcode_low_net_transfer=False)) == 0
    assert sent(run_planning([ZERO_TOTAL], hardcode_low_net_transfer=False)) == 4


def test_master_toggle_off_disables_all_three_including_net_transfer():
    """Antes la regla de net transfer se escapaba del toggle maestro."""
    for row in (ZERO_TOTAL, BELOW_DEMAND, LOW_NET_TRANSFER):
        assert sent(run_planning([row], cover_fountain9_hardcodes=False)) == 0, row


# --- umbrales de la regla de net transfer ---------------------------------------------------

def test_net_transfer_threshold_is_configurable():
    high_net = (100, 10, 0, 2, 5, 5)
    assert sent(run_planning([high_net])) == 0                         # 5 > 3
    assert sent(run_planning([high_net], net_transfer_max=5.0)) == 4   # 5 <= 5


def test_destination_stock_threshold_is_configurable():
    run = run_planning([LOW_NET_TRANSFER], destination_stock_below=0.0)   # stock 0 < 0: no
    assert sent(run) == 0


# --- piso mínimo ---------------------------------------------------------------------------------

def test_small_positive_roq_is_raised_to_the_minimum_by_default():
    assert sent(run_planning([(100, 10, 1)])) == 4


def test_small_positive_roq_is_kept_when_the_floor_is_off():
    assert sent(run_planning([(100, 10, 1)], raise_small_roq_to_minimum=False)) == 1
    assert sent(run_planning([(100, 10, 6)], raise_small_roq_to_minimum=False)) == 6


def test_floor_toggle_does_not_change_the_hardcode_minimums():
    assert sent(run_planning([ZERO_TOTAL], raise_small_roq_to_minimum=False)) == 4


# --- columnas adicionales de MOV --------------------------------------------------------------

def test_extra_mov_columns_raise_the_effective_mov():
    column = m.MOV_MAX_OPTIONAL_COLUMNS[0]
    rows = [(100, 10, 2, 2, 0, 0, 9)]                       # MOV 2, columna extra 9
    on = sent(run_planning(rows, extra_mov_column=column, raise_small_roq_to_minimum=False))
    off = sent(run_planning(rows, extra_mov_column=column, raise_small_roq_to_minimum=False,
                            use_extra_mov_columns=False))
    assert (on, off) == (9, 2)


def test_summary_marks_minimums_off_when_all_three_rules_are_off():
    run = run_planning(
        [ZERO_TOTAL], hardcode_zero_total=False, hardcode_inventory_below_demand=False,
        hardcode_low_net_transfer=False,
    )
    row = next(r for r in run["engine_summary_rows"]
               if (r["ENGINE"], r["COBERTURA"]) == ("Naked", "Mínimos (hardcode)"))
    assert row["ESTADO"] == "APAGADO"
