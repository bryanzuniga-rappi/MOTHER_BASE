"""Shalashaska: ciudades por origen, ROQ positivo mandante, categorías
sensibles y tope de evacuación."""

from datetime import date

import modules.les_enfants_terribles as m
from engines import shalashaska_engine as sh
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes
from tests.test_e2e_kazuhira import _bulk_lines

STORES = {100: "CDMX", 200: "Guadalajara", 300: "Monterrey"}
SKUS = [10, 11]
DAY = date(2026, 10, 5)
# (origen, sku, unidades en riesgo, valor, llegada, caducidad)
RISK = [(444, 10, 100, 500.0, date(2026, 9, 1), date(2026, 10, 12))]
SHARES = [(100, 0.4), (200, 0.3), (300, 0.3)]


def run_planning(plan, *, risk=RISK, categories=None, **overrides):
    extra = {"POR_MERMAR": risk, "SHARE_VENTAS": SHARES}
    kwargs = dict(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("plan.csv", build_plan_csv_bytes(plan))],
        database_bytes=build_workbook_bytes(STORES, SKUS, extra_rows=extra, categories=categories),
        origins=(444,),
        max_tasks=1000,
        run_date=DAY,
        include_insumos=False,
        enable_closed_stores_rule=False,
        block_fruver_811=False,
        block_off_schedule_shipments=False,
        include_shalashaska_engine=True,
    )
    kwargs.update(overrides)
    return m.execute_planning(**kwargs)


def shala_units(run, sku=10):
    """Unidades por tienda enviadas por Shalashaska (todo lo que excede a Naked)."""
    return {
        store: qty for (store, s_), qty in _bulk_lines(run).items() if s_ == sku
    }


NATURAL_PLAN = [(100, 11, 5), (200, 11, 5), (300, 11, 5)]      # ROQ positivo en las 3 tiendas


# --- ciudades --------------------------------------------------------------------------------

def test_forced_cities_follow_the_selected_origins():
    f = sh.shalashaska_forced_cities
    assert f((444,)) == {"CDMX"} and f((811, 831, 834)) == {"CDMX"}
    assert f((425,)) == {"GDL"}
    assert f((856,)) == {"MTY"} and f((49,)) == {"MTY"}
    assert f((444, 425, 856)) == {"CDMX", "GDL", "MTY"}
    assert f((999,)) == set()


def test_only_the_forced_city_receives_merma_by_default():
    run = run_planning(NATURAL_PLAN)
    got = shala_units(run)
    assert set(got) == {100}                       # origen 444 => solo CDMX
    assert run["shalashaska"]["allowed_cities"] == ["CDMX"]
    assert run["shalashaska"]["skipped_city_not_allowed"] >= 1


def test_extra_cities_open_the_route_to_them():
    got = shala_units(run_planning(NATURAL_PLAN, shalashaska_extra_cities=("Guadalajara",)))
    assert set(got) == {100, 200}


def test_extra_cities_are_matched_by_normalized_name():
    got = shala_units(run_planning(NATURAL_PLAN, shalashaska_extra_cities=("MONTERREY",)))
    assert set(got) == {100, 300}


# --- ROQ positivo mandante ---------------------------------------------------------------------

def test_store_with_only_a_hardcode_minimum_never_receives_merma():
    # 100: ROQ positivo; 200: solo mínimo por forecast cero (hardcode)
    plan = [(100, 11, 5), (200, 11, 0, 0, 0, 0)]
    run = run_planning(plan, shalashaska_extra_cities=("Guadalajara",))
    assert 200 not in shala_units(run) and 100 in shala_units(run)
    assert run["shalashaska"]["stores_without_positive_roq"] >= 1


def test_store_with_a_natural_line_still_qualifies_even_if_it_also_has_a_hardcode():
    plan = [(200, 11, 5), (200, 10, 0, 0, 0, 0)]       # una natural + un mínimo
    run = run_planning(plan, shalashaska_extra_cities=("Guadalajara",), risk=[(444, 11, 50, 100.0, date(2026, 9, 1), date(2026, 10, 12))])
    assert 200 in shala_units(run, sku=11)


# --- categorías sensibles ------------------------------------------------------------------------

def test_sensitive_category_is_not_evacuated_by_default():
    run = run_planning(NATURAL_PLAN, categories={10: "Huevo"})
    assert shala_units(run) == {}
    assert run["shalashaska"]["skipped_sensitive_category"] == 1
    assert run["shalashaska"]["units_sensitive_excluded"] == 100


def test_sensitive_category_can_be_allowed_from_codec():
    run = run_planning(NATURAL_PLAN, categories={10: "Huevo"}, shalashaska_allow_sensitive=True)
    assert 100 in shala_units(run)


def test_category_match_ignores_case_accents_and_plural():
    sens = frozenset({"HUEVO"})
    for name in ("Huevo", "HUEVO", "huevos", " Huevo "):
        assert sh.is_sensitive_category(name, sens), name
    for name in ("Lácteos y huevo", "Huevera", "", None, "Snacks"):
        assert not sh.is_sensitive_category(name, sens), name


def test_other_categories_are_unaffected():
    run = run_planning(NATURAL_PLAN, categories={10: "Snacks"})
    assert 100 in shala_units(run)


def test_missing_category_is_reported_not_silently_ignored():
    run = run_planning(NATURAL_PLAN, categories={10: ""})
    assert run["shalashaska"]["sensitive_unclassified"] == 1
    assert any("CATEGORY_NAME" in w for w in run["warnings"])


# --- tope de evacuación ------------------------------------------------------------------------

def test_default_evacuates_the_whole_merma():
    assert sum(shala_units(run_planning(NATURAL_PLAN)).values()) >= 100


def test_fraction_sends_only_that_share_of_the_merma():
    run = run_planning(NATURAL_PLAN, shalashaska_evacuation_fraction=0.8)
    s = run["shalashaska"]
    assert s["units_evacuated"] == 80
    assert s["units_held_back_by_fraction"] == 20
    assert s["evacuation_fraction"] == 0.8


def test_fraction_never_rounds_up_past_the_limit():
    risk = [(444, 10, 7, 50.0, date(2026, 9, 1), date(2026, 10, 12))]
    s = run_planning(NATURAL_PLAN, risk=risk, shalashaska_evacuation_fraction=0.8)["shalashaska"]
    assert s["units_evacuated"] == 5          # floor(7 * 0.8)


def test_invalid_fraction_is_rejected():
    for bad in (0, -0.1, 1.5):
        try:
            sh.apply_shalashaska_engine(None, None, None, [], {}, set(), (), {},
                                        run_date=DAY, target_doh=7.0, evacuation_fraction=bad)
        except ValueError:
            continue
        raise AssertionError(f"debía rechazar {bad}")
