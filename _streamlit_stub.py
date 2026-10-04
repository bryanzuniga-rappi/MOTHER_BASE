"""Stub mínimo de streamlit para poder importar les_enfants_terribles.py en
tests sin depender del paquete real. Solo cubre lo que se usa a nivel de
módulo (decoradores) y las llamadas que las funciones bajo prueba podrían
disparar; no reemplaza pruebas de interfaz.
"""

import sys
import types


def install() -> None:
    if "streamlit" in sys.modules and getattr(
        sys.modules["streamlit"], "_mother_base_stub", False
    ):
        return

    stub = types.ModuleType("streamlit")
    stub._mother_base_stub = True

    def _noop(*_args, **_kwargs):
        return None

    def _decorator_factory(*_args, **_kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    for name in (
        "toggle", "multiselect", "columns", "container", "markdown",
        "number_input", "text_area", "warning", "error", "success",
        "caption", "write", "text_input", "button", "spinner", "status",
        "progress", "dataframe", "expander", "info", "metric", "tabs",
        "selectbox", "checkbox", "file_uploader", "download_button",
        "set_page_config", "sidebar", "empty", "stop", "rerun", "form",
        "form_submit_button",
    ):
        setattr(stub, name, _noop)

    stub.cache_data = _decorator_factory
    stub.cache_resource = _decorator_factory
    stub.dialog = _decorator_factory
    stub.session_state = {}

    sys.modules["streamlit"] = stub
