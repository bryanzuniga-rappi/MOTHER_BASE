"""Registro de engines: orden de ejecución, atribución por fila y resumen.

Solidus es un engine propio con 4 coberturas (AVL, Preventivo, Refuerzo,
Cobertura sin Fountain9); los mínimos (hardcode) pertenecen a Naked."""

import re
from pathlib import Path
from types import SimpleNamespace

import modules.les_enfants_terribles as m

ENGINE_ORDER = (
    "Naked", "Shalashaska", "Solidus", "Liquid", "Venom", "Kazuhira", "Insumos",
)


# --- registro ------------------------------------------------------------------

def test_engine_order_is_the_real_execution_order():
    assert m.ENGINE_ORDER == ENGINE_ORDER
    source = (Path(m.__file__)).read_text(encoding="utf-8")
    positions = [
        source.index(marker)
        for marker in (
            "engine.plan_transfers(", "= apply_shalashaska_engine(",
            "avl_summary = apply_avl_fill(", "= apply_liquid_engine(",
            "= apply_venom_engine(", "kazuhira_summary = apply_avl_fill(",
        )
    ]
    assert positions == sorted(positions)


def test_every_engine_has_complete_documentation():
    for name in m.ENGINE_ORDER:
        info = m.ENGINE_INFO[name]
        assert info["stage"] and info["role"] and info["position"], name
        assert len(info["how"]) >= 3, name
    for engine_name, coverages in m.COVERAGE_ORDER.items():
        assert set(m.ENGINE_INFO[engine_name]["coverages"]) == set(coverages)


def test_solidus_has_exactly_the_four_catalog_coverages():
    assert m.COVERAGE_ORDER["Solidus"] == (
        "AVL", "Preventivo", "Refuerzo Golden/Infaltable/Anchor",
        "Cobertura sin Fountain9",
    )


def test_every_planning_reason_is_mapped_to_an_engine():
    reasons = [
        value for name, value in vars(m).items()
        if re.fullmatch(r"PLANNING_REASON_[A-Z0-9_]+", name)
        and name not in ("PLANNING_REASON_COLUMN", "PLANNING_REASON_INSUMOS")
    ] + [m.SHALASHASKA_REASON, m.LIQUID_REASON, m.VENOM_REASON]
    missing = [r for r in reasons if r not in m.ENGINE_COVERAGE_BY_REASON]
    assert not missing, missing


def test_csv_reason_of_minimums_says_naked_not_solidus():
    assert "NAKED" in m.PLANNING_REASON_MANUAL_FORECAST_ZERO
    assert "SOLIDUS" not in m.PLANNING_REASON_MANUAL_FORECAST_ZERO


# --- atribución por fila ----------------------------------------------------------

def test_attribute_row_each_solidus_coverage():
    for cut, coverage in (
        ("ENVIADOS PARA CUBRIR AVL", "AVL"),
        ("ENVIADOS PARA PREVENIR QUIEBRE", "Preventivo"),
        (m.SPECIAL_DOH_CUT, "Refuerzo Golden/Infaltable/Anchor"),
        (m.NO_FOUNTAIN9_CUT, "Cobertura sin Fountain9"),
    ):
        assert m.attribute_row({"TIPO_DE_CORTE": cut}) == ("Solidus", coverage)


def test_attribute_row_hardcode_minimums_belong_to_naked():
    for rule in m.MANUAL_FORECAST_ZERO_RULES:
        row = {"TIPO_DE_CORTE": "OK MANUAL POR NET TRANSFER BAJO", "REGLA_DEMANDA": rule}
        assert m.attribute_row(row) == ("Naked", "Mínimos (hardcode)")
    natural = {"TIPO_DE_CORTE": "OK COMPLETO POR FOUNTAIN9", "REGLA_DEMANDA": "ROQ_FOUNTAIN9"}
    assert m.attribute_row(natural) == ("Naked", "Fountain9")


def test_attribute_row_other_engines_and_sweep_rows():
    assert m.attribute_row({"TIPO_DE_CORTE": m.SHALASHASKA_CUT})[0] == "Shalashaska"
    assert m.attribute_row({"TIPO_DE_CORTE": m.KAZUHIRA_CUT})[0] == "Kazuhira"
    sweep = {"TIPO_DE_CORTE": m.CATALOG_UNIVERSE_UNCOVERED_CUT, "REGLA_DEMANDA": m.CATALOG_UNIVERSE_UNCOVERED_REGLA}
    assert m.attribute_row(sweep)[0] == m.SWEEP_ONLY_ENGINE
    post = {"TIPO_DE_CORTE": m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT, "REGLA_DEMANDA": m.CATALOG_UNIVERSE_POST_KAZUHIRA_REGLA}
    assert m.attribute_row(post)[0] == "Kazuhira"


def test_annotate_base_rows_adds_engine_and_coverage():
    rows = [{"TIPO_DE_CORTE": "ENVIADOS PARA CUBRIR AVL"}, {"TIPO_DE_CORTE": "OK", "REGLA_DEMANDA": "X"}]
    m.annotate_base_rows_with_engine(rows)
    assert (rows[0]["ENGINE"], rows[0]["COBERTURA"]) == ("Solidus", "AVL")
    assert (rows[1]["ENGINE"], rows[1]["COBERTURA"]) == ("Naked", "Fountain9")


# --- resumen por engine ------------------------------------------------------------------

def _line(reason, qty):
    return {m.PLANNING_REASON_COLUMN: reason, "QUANTITY": qty}


def _base(cut, assigned, rule="ROQ", swa=0.0):
    return {"TIPO_DE_CORTE": cut, "REGLA_DEMANDA": rule, "CANTIDAD_ASIGNADA": assigned,
            "SWA_POTENTIAL_GAIN_COUNTRY": swa}


def _summary():
    result = SimpleNamespace(
        base_rows=[
            _base("OK", 10, swa=1.0),
            _base("OK MANUAL POR FORECAST Y STOCK EN CERO", 4, "HARDCODE_4_CERO_TOTAL", swa=0.5),
            _base("ENVIADOS PARA CUBRIR AVL", 6, swa=2.0),
            _base(m.SPECIAL_DOH_CUT, 3, swa=0.25),
            _base(m.SHALASHASKA_CUT, 7),
        ],
        allocation_rows=[
            _line(m.PLANNING_REASON_FOUNTAIN9, 10),
            _line(m.PLANNING_REASON_MANUAL_FORECAST_ZERO, 4),
            _line(m.PLANNING_REASON_AVL, 6), _line(m.PLANNING_REASON_AVL, 2),
            _line(m.PLANNING_REASON_SPECIAL_DOH, 3),
            _line(m.SHALASHASKA_REASON, 7),
        ],
    )
    rows = m.build_engine_summary_rows(result, {"lines_added": 5, "units_added": 900})
    return {(r["ENGINE"], r["COBERTURA"]): r for r in rows}, rows


def test_summary_lists_every_engine_in_execution_order():
    by_key, rows = _summary()
    order = []
    for row in rows:
        if row["ENGINE"] not in order:
            order.append(row["ENGINE"])
    assert tuple(order) == ENGINE_ORDER


def test_summary_solidus_total_is_the_sum_of_its_coverages():
    by_key, _ = _summary()
    total = by_key[("Solidus", "Total")]
    parts = [by_key[("Solidus", c)] for c in m.COVERAGE_ORDER["Solidus"]]
    for field in ("CASOS", "TAREAS", "UNIDADES", "SWA_GANADO"):
        assert total[field] == round(sum(p[field] for p in parts), 4)
    assert (total["CASOS"], total["TAREAS"], total["UNIDADES"]) == (2, 3, 11)
    assert by_key[("Solidus", "AVL")]["TAREAS"] == 2


def test_summary_naked_includes_minimums_and_counts_tasks_from_real_lines():
    by_key, _ = _summary()
    assert by_key[("Naked", "Total")]["TAREAS"] == 2
    assert by_key[("Naked", "Total")]["UNIDADES"] == 14
    assert by_key[("Naked", "Mínimos (hardcode)")]["CASOS"] == 1
    assert by_key[("Naked", "Mínimos (hardcode)")]["SWA_GANADO"] == 0.5


def test_summary_tasks_match_total_allocation_lines_and_insumos_has_none():
    by_key, rows = _summary()
    engine_rows = [r for r in rows if r["COBERTURA"] in ("Total", "—") and r["ENGINE"] != "Insumos"]
    assert sum(r["TAREAS"] for r in engine_rows) == 6
    insumos = by_key[("Insumos", "—")]
    assert (insumos["TAREAS"], insumos["CASOS"], insumos["UNIDADES"]) == (0, 5, 900)


def test_summary_status_reflects_enabled_flags():
    result = SimpleNamespace(base_rows=[], allocation_rows=[])
    enabled = {("Solidus", "AVL"): True, ("Solidus", "Preventivo"): False,
               ("Solidus", "Refuerzo Golden/Infaltable/Anchor"): False,
               ("Solidus", "Cobertura sin Fountain9"): False, ("Liquid", "—"): False}
    rows = {(r["ENGINE"], r["COBERTURA"]): r for r in m.build_engine_summary_rows(result, None, enabled)}
    assert rows[("Solidus", "Total")]["ESTADO"] == "ACTIVO"      # basta una cobertura
    assert rows[("Solidus", "Preventivo")]["ESTADO"] == "APAGADO"
    assert rows[("Liquid", "—")]["ESTADO"] == "APAGADO"
