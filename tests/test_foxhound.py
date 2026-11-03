"""Regresiones de limpieza y métricas básicas de FOXHOUND."""

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

from modules import foxhound  # noqa: E402


def test_foxhound_prepares_dispatchtrack_statuses_and_delivery_fields():
    rows = foxhound.prepare_rows([
        {"Orden": "164596-1", "Fecha ruta": "2026-11-03", "Estado": "Entregado", "Tiempo en destino (minutos)": "37.1", "Precio": "35089.8", "Nombre de conductor": "Omar", "Razón de la no entrega en tienda": "", "CD de origen": "City Park"},
        {"Orden": "164597", "Fecha ruta": "2026-11-03", "Estado": "No entregado", "Tiempo en destino (minutos)": "40", "Precio": "20", "Nombre de conductor": "Omar Palma", "Razón de la no entrega en tienda": "Tienda cerrada", "CD de origen": "CEDA"},
    ])
    assert rows[0]["orden_base"] == "164596"
    assert rows[0]["min_en_tienda"] == 37.1 and rows[0]["valor_entregado"] == 35089.8
    assert rows[1]["motivo"] == "Tienda cerrada" and rows[1]["valor_entregado"] == 0
    assert rows[0]["conductor"] == "Omar Palma"


def test_foxhound_reason_categories():
    assert foxhound._reason("No se cargó en CD") == "No se cargó en CD"
    assert foxhound._reason("cancelación del cliente") == "Cancelación"
    assert foxhound._reason("") == "Sin motivo"
