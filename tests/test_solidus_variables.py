"""Solidus: Refuerzo por bucket (Infaltable, Golden, Anchor, KVI), cada uno con
su toggle y su DOH, y prioridad por SWA cuando falta capacidad."""

from datetime import date

import modules.les_enfants_terribles as m
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes
from tests.test_e2e_kazuhira import _bulk_lines

STORES = {100: "CDMX", 200: "CDMX"}
SKUS = [10, 11, 12, 13, 14]
# 10 Infaltable · 11 Golden · 12 Anchor · 13 KVI · 14 recomendado por Fountain9
BUCKET_SHEETS = {
    "GOLDEN_INFALTABLES_ANCHOR": [
        (100, 10, 1, 0, 0), (100, 11, 0, 1, 0), (100, 12, 0, 0, 1),
    ],
    "KVI": [(100, 13, 1)],
}


def run_planning(*, extra_rows=None, swa_values=None, plan=((100, 14, 5),), **overrides):
    kwargs = dict(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("plan.csv", build_plan_csv_bytes(list(plan)))],
        database_bytes=build_workbook_bytes(
            STORES, SKUS, extra_rows=extra_rows or BUCKET_SHEETS, swa_values=swa_values
        ),
        origins=(444,),
        max_tasks=1000,
        run_date=date(2026, 10, 5),
        include_insumos=False,
        enable_closed_stores_rule=False,
        block_fruver_811=False,
        block_off_schedule_shipments=False,
        include_special_doh_fill=True,
    )
    kwargs.update(overrides)
    return m.execute_planning(**kwargs)


def lines(run, store=100):
    return {sku: qty for (s_, sku), qty in _bulk_lines(run).items() if s_ == store}


# --- cada bucket con su toggle y su DOH --------------------------------------------------

def test_only_enabled_buckets_are_reinforced_each_with_its_own_doh():
    got = lines(run_planning(special_doh_targets={"INFALTABLE": 2.0, "GOLDEN": 5.0}))
    assert got[10] == 2 and got[11] == 5          # ADU 1, stock 0: ceil(1 * DOH)
    assert 12 not in got and 13 not in got        # Anchor y KVI apagados


def test_anchor_and_kvi_have_their_own_toggle_and_doh():
    got = lines(run_planning(special_doh_targets={"ANCHOR": 4.0, "KVI": 6.0}))
    assert got[12] == 4 and got[13] == 6
    assert 10 not in got and 11 not in got


def test_all_four_buckets_default_target_is_three():
    got = lines(run_planning(special_doh_targets={b: 3.0 for b in ("INFALTABLE", "GOLDEN", "ANCHOR", "KVI")}))
    assert [got[s] for s in (10, 11, 12, 13)] == [3, 3, 3, 3]


def test_overlapping_sku_uses_the_highest_enabled_doh():
    sheets = {"GOLDEN_INFALTABLES_ANCHOR": [(100, 10, 1, 1, 0)], "KVI": []}   # Infaltable y Golden
    got = lines(run_planning(extra_rows=sheets, special_doh_targets={"INFALTABLE": 2.0, "GOLDEN": 5.0}))
    assert got[10] == 5
    got = lines(run_planning(extra_rows=sheets, special_doh_targets={"INFALTABLE": 2.0}))
    assert got[10] == 2                           # Golden apagado: solo cuenta Infaltable


def test_no_bucket_enabled_means_no_reinforcement():
    run = run_planning(special_doh_targets={}, include_special_doh_fill=False)
    assert lines(run) == {14: 5}


def test_legacy_single_target_still_covers_infaltable_golden_anchor_but_not_kvi():
    got = lines(run_planning(special_doh_target=4.0))
    assert [got[s] for s in (10, 11, 12)] == [4, 4, 4] and 13 not in got


def test_fountain9_recommendation_is_never_modified_by_the_reinforcement():
    got = lines(run_planning(plan=((100, 10, 1),), special_doh_targets={"INFALTABLE": 9.0}))
    assert got[10] == 3        # solo Fountain9 (mínimo 3); un refuerzo a 9 DOH habría enviado 9


def test_summary_and_health_check_report_the_target_of_each_bucket():
    run = run_planning(special_doh_targets={"INFALTABLE": 2.0, "KVI": 6.0}, include_special_doh_fill=False)
    # sin Refuerzo corriendo, la verificación final sigue evaluando cada bucket con su DOH
    below = {r["RETAIL_ID"]: r["DOH_OBJETIVO"] for r in run["golden_health_check"]["below_target"]}
    assert below[10] == 2.0 and below[13] == 6.0 and 11 not in below
    assert run["kvi_universe_report"]["enabled"] is True
    assert run["kvi_universe_report"]["target_doh"] == 6.0
    assert run["golden_universe_report"]["enabled"] is True


def test_special_doh_text_names_each_bucket():
    assert m.special_doh_text({"doh_by_bucket": {"INFALTABLE": 3.0, "KVI": 5.0}}) == "Infaltable 3 DOH, KVI 5 DOH"
    assert m.special_doh_text({"doh": 3.0}) == "3 DOH"


# --- prioridad por SWA ---------------------------------------------------------------------

def _scarce_capacity_run(**overrides):
    """Capacidad para 2 unidades (0.004 m³): solo un SKU AVL cabe."""
    return run_planning(
        extra_rows={"CAP_RECIBO": [(100, 0.004)]},
        swa_values={(100, 10): 0.1, (100, 11): 0.9},
        plan=((200, 14, 1),), include_special_doh_fill=False,      # la recomendación va a otra tienda
        include_avl_fill=True, avl_doh=3.0, **overrides,
    )


def test_swa_priority_serves_the_highest_swa_first_when_capacity_is_short():
    got = lines(_scarce_capacity_run(solidus_swa_priority=True))
    assert 11 in got and 10 not in got


def test_without_swa_priority_the_default_order_applies():
    got = lines(_scarce_capacity_run(solidus_swa_priority=False))
    assert 10 in got and 11 not in got


def test_swa_priority_is_on_by_default():
    got = lines(_scarce_capacity_run())
    assert 11 in got and 10 not in got
