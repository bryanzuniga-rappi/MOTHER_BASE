"""Estándar de etiquetas de controles (toggles, campos, botones, expanders).

Reglas: sentence case (sin TODO EN MAYÚSCULAS), sin guiones bajos, sin
separadores "—" ni "·" (los calificadores van entre paréntesis) y "opcional"
solo entre paréntesis. Ver README, "Estilo de comentarios y documentación"."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_FILES = [
    "app.py",
    "modules/les_enfants_terribles.py",
    "modules/militaires_sans_frontieres.py",
]
WIDGETS = {
    "toggle", "checkbox", "number_input", "text_input", "text_area",
    "multiselect", "selectbox", "radio", "slider", "button",
    "form_submit_button", "file_uploader", "expander", "download_button",
    "date_input",
}


def widget_labels():
    for rel in UI_FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in WIDGETS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            label = node.args[0].value.strip()
            if label:
                yield rel, node.lineno, label


def _is_all_caps(label: str) -> bool:
    letters = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", label)
    return len(letters) > 3 and letters == letters.upper()


def test_there_are_labels_to_check():
    assert len(list(widget_labels())) >= 50


def test_no_underscores_in_labels():
    bad = [x for x in widget_labels() if "_" in x[2]]
    assert not bad, bad


def test_no_all_caps_labels():
    bad = [x for x in widget_labels() if _is_all_caps(x[2])]
    assert not bad, bad


def test_qualifiers_use_parentheses_not_dashes_or_dots():
    bad = [x for x in widget_labels() if " — " in x[2] or " · " in x[2]]
    assert not bad, bad


def test_optional_marker_is_always_in_parentheses():
    bad = [
        x for x in widget_labels()
        if re.search(r"opcional", x[2], re.I) and "opcional)" not in x[2]
    ]
    assert not bad, bad


def test_download_button_label_hides_file_label_underscores():
    """file_label alimenta el nombre del archivo (con guiones bajos) pero la
    etiqueta visible del botón no debe mostrarlos."""
    from tests._streamlit_stub import install

    install()
    import modules.les_enfants_terribles as m

    labels = []
    original = m.st.download_button
    m.st.download_button = lambda label, **kwargs: labels.append((label, kwargs))
    try:
        m.render_capped_dataframe(
            [{"a": 1}], key="k", offer_download=True, file_label="cortes_por_motivo"
        )
    finally:
        m.st.download_button = original
    label, kwargs = labels[0]
    assert label == "Descargar cortes por motivo completo (.csv)"
    assert kwargs["file_name"] == "cortes_por_motivo.csv"
