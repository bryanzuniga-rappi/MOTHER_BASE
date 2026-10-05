"""Ejecuta render() de CODEC completo con un Streamlit simulado.

Cada control devuelve su valor por defecto (o el que se le fuerce por etiqueta),
el clic de "Ejecutar" se simula y execute_planning se reemplaza por un espía que
valida los argumentos contra su firma real. Sirve para cazar nombres mal
conectados entre la UI y el motor, que la compilación no detecta."""

import datetime
import inspect
from unittest.mock import MagicMock

import modules.les_enfants_terribles as m
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes


class StopRender(Exception):
    """Equivale a st.stop() / st.rerun()."""


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeStreamlit:
    def __init__(self, overrides=None, force_toggles=None):
        self.overrides = overrides or {}
        self.force_toggles = force_toggles
        self.session_state = {}
        self.labels: list[tuple[str, str]] = []
        self.errors: list[str] = []
        self.cards: dict[str, dict] = {}

    # --- controles ---------------------------------------------------------------
    def _value(self, kind, label, default):
        self.labels.append((kind, label))
        return self.overrides.get(label, default)

    def toggle(self, label, value=False, **kw):
        forced = self.force_toggles if self.force_toggles is not None else value
        return self._value("toggle", label, forced)

    checkbox = toggle

    def number_input(self, label, min_value=None, max_value=None, value=None, **kw):
        return self._value("number_input", label, value if value is not None else min_value)

    def selectbox(self, label, options=(), index=0, **kw):
        options = list(options)
        return self._value("selectbox", label, options[index] if options else None)

    def multiselect(self, label, options=(), default=None, **kw):
        return self._value("multiselect", label, list(default or []))

    def text_area(self, label, value="", **kw):
        return self._value("text_area", label, value)

    text_input = text_area

    def file_uploader(self, label, accept_multiple_files=False, **kw):
        default = [] if accept_multiple_files else None
        return self._value("file_uploader", label, default)

    def button(self, label, **kw):
        return self._value("button", label, False)

    download_button = button

    def date_input(self, label, value=None, **kw):
        return self._value("date_input", label, value or datetime.date(2026, 10, 5))

    # --- layout --------------------------------------------------------------------
    def columns(self, spec, **kw):
        return [_Ctx() for _ in range(spec if isinstance(spec, int) else len(spec))]

    def tabs(self, labels, **kw):
        return [_Ctx() for _ in labels]

    def container(self, *a, **k):
        return _Ctx()

    expander = container
    status = container
    spinner = container

    def stop(self):
        raise StopRender("st.stop")

    def rerun(self):
        raise StopRender("st.rerun")

    def error(self, message, *a, **k):
        self.errors.append(str(message))

    def __getattr__(self, name):          # markdown, caption, info, warning, write, ...
        return MagicMock()


def run_codec(overrides=None, *, force_toggles=None, pending_run=True):
    """Devuelve (kwargs capturados de execute_planning o None, FakeStreamlit)."""
    fake = FakeStreamlit(overrides, force_toggles)
    plan = FakeUpload("plan.csv", build_plan_csv_bytes([(100, 10, 5)]))
    base_overrides = {
        "Orígenes (en orden de prioridad)": [811],
        "Archivos de planeación de Fountain9 (.csv)": [plan],
    }
    fake.overrides = {**base_overrides, **fake.overrides}
    if pending_run:
        fake.session_state["mb_run_confirmed"] = True
    for key in ("naked", "shalashaska", "solidus", "liquid", "venom", "kazuhira"):
        fake.session_state[f"mb_engine_{key}_enabled"] = True

    workbook_bytes = build_workbook_bytes({100: "CDMX"}, [10])
    state = {
        "workbook_bytes": workbook_bytes,
        # La base sintética no trae todas las hojas reales: se declara sana para
        # que el flujo llegue a execute_planning.
        "health": {**m.inspect_database(workbook_bytes), "online": True},
        "city_labels": {"CDMX": "Ciudad de México", "Guadalajara": "Guadalajara", "Monterrey": "Monterrey"},
        "store_labels": {100: "100 · Tienda", 200: "200 · Otra"},
        "error": "",
    }
    captured: dict = {}
    real_execute = m.execute_planning
    signature = inspect.signature(real_execute)

    def spy(**kwargs):
        signature.bind(**kwargs)            # TypeError si la UI manda un nombre que no existe
        captured.update(kwargs)
        return {}

    originals = {n: getattr(m, n) for n in ("st", "execute_planning", "load_database_resource",
                                            "render_action_card", "render_results", "render_database_health")}
    m.st = fake
    m.execute_planning = spy
    m.load_database_resource = lambda: state
    def card_spy(**kw):
        fake.cards[kw["key"]] = kw
        return False

    m.render_action_card = card_spy
    m.render_results = lambda run: None
    m.render_database_health = lambda health: None
    try:
        try:
            m.render()
        except StopRender:
            pass
    finally:
        for name, value in originals.items():
            setattr(m, name, value)
    return (captured or None), fake
