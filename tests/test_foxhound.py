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


def test_foxhound_matches_sap_transfer_and_split_without_using_store_name():
    dispatch = foxhound.prepare_rows([
        {"Orden": "4600000001.0", "Estado": "Entregado", "Nombre de conductor": "Ana", "Nombre cliente": "Nombre cambiado"},
        {"Orden": "164596-1", "Estado": "Pendiente", "Nombre de conductor": "Ana", "Nombre cliente": "Nombre cambiado-1"},
        {"Orden": "999999", "Estado": "Pendiente", "Nombre de conductor": "Ana"},
    ])
    transfers = foxhound.prepare_transfers([{
        "TRANSFER_ID": "164596", "SAP_ID": "4600000001", "ORDERED": 10,
        "PICKED": 9, "DELIVERED": 8, "DESTINATION_WAREHOUSE_ID": "820",
        "DESTINATION_WAREHOUSE_NAME": "Nombre Aleph",
    }])
    directions = foxhound.prepare_directions([{
        "WAREHOUSE_ID": "820", "WAREHOUSE_NAME": "Nombre canónico", "ADDRES": "Dirección canónica", "CITY": "CDMX",
    }])

    events, canonical = foxhound.build_logistics_model(dispatch, transfers, directions)

    assert [event["match_transfer"] for event in events] == ["SAP exacto", "Transfer partida", "Sin match"]
    assert canonical[0]["partes DT"] == 2
    assert canonical[0]["tienda canónica"] == "Nombre canónico"
    assert canonical[0]["estado consolidado"] == "Parcial"


def test_foxhound_driver_fill_rate_counts_transfer_once_and_excludes_shared():
    transfers = [
        {"conductor": "Ana", "ordered": 10, "picked": 10, "delivered": 9, "estado consolidado": "Entregado"},
        {"conductor": "Ana", "ordered": 20, "picked": 20, "delivered": 10, "estado consolidado": "No entregado"},
        {"conductor": "Compartido", "ordered": 100, "picked": 100, "delivered": 100, "estado consolidado": "Entregado"},
    ]
    ranking = foxhound.driver_leaderboard(transfers, minimum_transfers=2)

    assert len(ranking) == 1
    assert ranking[0]["conductor"] == "Ana"
    assert ranking[0]["fill entrega"] == 19 / 30
    assert ranking[0]["elegible"] is True


def test_foxhound_identifies_sla_and_operational_risk():
    rows = foxhound.prepare_rows([
        {
            "Orden": "1", "Estado": "Entregado", "Nombre de conductor": "Ana",
            "Fecha estimada": "2026-11-03 10:00:00", "Fecha Llegada": "2026-11-03 09:30:00",
            "Asignado a vehículo": "1", "En ruta": "1",
        },
        {"Orden": "2", "Estado": "Pendiente", "Nombre de conductor": "", "Asignado a vehículo": "0"},
        {"Orden": "3", "Estado": "No entregado", "Nombre de conductor": "Ana"},
    ])

    assert rows[0]["a_tiempo"] is True
    assert rows[1]["riesgo_operativo"] == "Pendiente sin unidad"
    assert rows[2]["riesgo_operativo"] == "No entregada"


def test_foxhound_route_summary_uses_max_km_once_per_route():
    rows = foxhound.prepare_rows([
        {"Orden": "1", "Estado": "Entregado", "Identificador ruta": "Ruta 1", "Identificador": "Unidad 1", "KM de planner": 50, "Distancia recorrida de la ruta": 60, "Nombre de conductor": "Ana"},
        {"Orden": "2", "Estado": "No entregado", "Identificador ruta": "Ruta 1", "Identificador": "Unidad 1", "KM de planner": 50, "Distancia recorrida de la ruta": 60, "Nombre de conductor": "Ana"},
    ])
    summary = foxhound.route_summary(rows)

    assert summary[0]["Paradas"] == 2
    assert summary[0]["KM planeados"] == 50
    assert summary[0]["KM reales"] == 60


def test_foxhound_consolidates_split_dispatch_orders_and_scores_driver_quality():
    rows = foxhound.prepare_rows([
        {"Orden": "162000-1", "Estado": "Entregado", "Nombre de conductor": "Ana", "Fecha ruta": "2026-11-03", "Fecha estimada": "2026-11-03 10:00:00", "Fecha Llegada": "2026-11-03 09:00:00"},
        {"Orden": "162000-2", "Estado": "Entregado", "Nombre de conductor": "Ana", "Fecha ruta": "2026-11-03", "Fecha estimada": "2026-11-03 10:00:00", "Fecha Llegada": "2026-11-03 09:01:00"},
        {"Orden": "162001", "Estado": "No entregado", "Nombre de conductor": "Beto", "Fecha ruta": "2026-11-03"},
    ])
    logical = foxhound.dispatch_consolidated(rows)
    split = next(row for row in logical if row["pedido lógico"] == "162000")
    quality = foxhound.driver_quality_leaderboard(logical, minimum_orders=1)

    assert len(logical) == 2
    assert split["partes"] == 2 and split["estado"] == "Entregada" and split["a tiempo"] is True
    assert quality[0]["Conductor"] == "Ana"
    assert quality[0]["Calidad OTIF"] == 1.0
