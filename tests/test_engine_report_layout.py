"""Reporte por engine: cada engine con su panel, en orden de ejecución, y
Solidus como engine propio (agrupa sus 4 coberturas)."""

import re
from unittest.mock import MagicMock

import modules.les_enfants_terribles as m
from tests import test_e2e_kazuhira as e2e
from tests._streamlit_stub import install

install()

ENGINE_PANEL = re.compile(r'engine-panel (\w+)')
COVERAGE_LABELS = [
    "SOLIDUS · COBERTURA AVL",
    "SOLIDUS · BLINDAJE PREVENTIVO",
    "SOLIDUS · REFUERZO GOLDEN / INFALTABLE / ANCHOR",
    "SOLIDUS · COBERTURA SIN FOUNTAIN9",
]


class _Zero(dict):
    """Resumen de engine con cualquier clave en 0 (para forzar la sección)."""

    def get(self, key, default=0):
        return dict.get(self, key, default)

    def __missing__(self, key):
        return 0


def _fake_streamlit(calls):
    fake = MagicMock()
    fake.columns.side_effect = lambda spec, **kw: [
        MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))
    ]
    fake.tabs.side_effect = lambda labels, **kw: [MagicMock() for _ in labels]
    fake.button.return_value = False
    fake.toggle.return_value = False
    fake.checkbox.return_value = False
    fake.session_state = {}
    fake.text_area.side_effect = lambda label, value="", **kw: value   # como el widget real
    fake.markdown.side_effect = lambda *args, **kw: calls.append(args[0] if args else "")
    fake.expander.side_effect = lambda label, **kw: (
        calls.append("EXPANDER:" + label) or MagicMock()
    )
    return fake


def _render(run):
    calls: list[str] = []
    original = m.st
    m.st = _fake_streamlit(calls)
    try:
        m.render_results(run)
    finally:
        m.st = original
    return calls


def _sequence(calls):
    out = []
    for call in calls:
        if not isinstance(call, str):
            continue
        panel = ENGINE_PANEL.search(call)
        if panel:
            out.append("PANEL:" + panel.group(1))
            continue
        label = re.search(r'section-label">([^<]+)<', call)
        if label and ("SOLIDUS ·" in label.group(1) or label.group(1) == "RESUMEN POR ENGINE"):
            out.append(label.group(1))
    return out


def _run_with_everything_enabled():
    run = e2e._run()
    for key in ("avl", "preventive", "special_doh", "no_fountain9_coverage",
                "shalashaska", "liquid", "venom", "insumos"):
        run[key] = _Zero(run.get(key) or {}, enabled=True)
    return run


def test_every_engine_gets_its_panel_in_execution_order():
    sequence = _sequence(_render(_run_with_everything_enabled()))
    panels = [item.split(":")[1] for item in sequence if item.startswith("PANEL:")]
    assert panels == ["naked", "shalashaska", "solidus", "liquid", "venom", "kazuhira", "insumos"]


def test_solidus_panel_comes_first_and_groups_its_four_coverages():
    sequence = _sequence(_render(_run_with_everything_enabled()))
    start = sequence.index("PANEL:solidus")
    assert sequence[start + 1: start + 5] == COVERAGE_LABELS


def test_summary_table_precedes_all_engine_panels():
    sequence = _sequence(_render(_run_with_everything_enabled()))
    assert sequence.index("RESUMEN POR ENGINE") < sequence.index("PANEL:naked")


def test_each_panel_has_a_how_it_works_expander():
    calls = _render(_run_with_everything_enabled())
    expanders = [c for c in calls if isinstance(c, str) and c.startswith("EXPANDER:Cómo funciona")]
    assert [e.split()[-1] for e in expanders] == [
        "Naked", "Shalashaska", "Solidus", "Liquid", "Venom", "Kazuhira", "Insumos",
    ]


def test_solidus_panel_hidden_when_no_coverage_ran_but_summary_still_lists_it():
    run = e2e._run()                         # sin coberturas de Solidus prendidas
    calls = _render(run)
    assert "PANEL:solidus" not in _sequence(calls)
    solidus_row = next(
        r for r in run["engine_summary_rows"]
        if r["ENGINE"] == "Solidus" and r["COBERTURA"] == "Total"
    )
    assert solidus_row["ESTADO"] == "APAGADO"


# --- helpers ----------------------------------------------------------------------------

def test_engine_header_html_uses_engine_color_and_role():
    calls = []
    original = m.st
    m.st = _fake_streamlit(calls)
    try:
        m.render_engine_header("Solidus", [], False)
    finally:
        m.st = original
    panel = next(c for c in calls if "engine-panel" in c)
    assert "engine-panel solidus" in panel and "SOLIDUS" in panel
    assert m.ENGINE_INFO["Solidus"]["role"].split(",")[0] in panel


def test_engine_summary_table_hides_swa_column_when_swa_is_off():
    captured = {}
    original = m.render_capped_dataframe
    m.render_capped_dataframe = lambda rows, **kw: captured.update(rows=rows, **kw)
    try:
        rows = [{"ETAPA": "Etapa 1", "ENGINE": "Naked", "COBERTURA": "Total", "QUÉ HACE": "x",
                 "ESTADO": "ACTIVO", "CASOS": 1, "TAREAS": 1, "UNIDADES": 1, "SWA_GANADO": 0.5}]
        m.render_engine_summary_table(rows, swa_enabled=False)
        assert "SWA_GANADO" not in captured["rows"][0]
        m.render_engine_summary_table(rows, swa_enabled=True)
        assert captured["rows"][0]["SWA_GANADO"] == 0.5
    finally:
        m.render_capped_dataframe = original


def test_pdf_includes_the_engine_summary_with_solidus():
    try:
        import io
        import zipfile

        import pypdf
    except ImportError:          # pypdf es opcional en este entorno
        return
    run = e2e._run()
    with zipfile.ZipFile(run["zip"]) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".pdf"))
        text = "".join(
            page.extract_text() for page in pypdf.PdfReader(io.BytesIO(archive.read(name))).pages
        )
    assert "RESUMEN POR ENGINE" in text and "Solidus" in text and "Kazuhira" in text
