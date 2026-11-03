"""FOXHOUND — comando logístico y seguimiento de entregas DispatchTrack."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import csv
import html
import io
import math
import os
from pathlib import Path
import re
import unicodedata
import urllib.request
from typing import Any

import openpyxl
import streamlit as st

from mother_base_theme import render_system_stamp


MODULE_NAME = "FOXHOUND"
SHEET_NAME = "DISPATCH_TRACK"
TRANSFERS_SHEET_NAME = "TRANSFERS"
DIRECTIONS_SHEET_NAME = "DIRECCIONES"
STATUS_ORDER = ("Entregado", "No entregado", "Pendiente")
STATUS_COLORS = {"Entregado": "#d9ff3f", "No entregado": "#ff5a47", "Pendiente": "#5e7cff"}
REQUIRED_HEADERS = (
    "Orden", "Fecha ruta", "Identificador", "Nombre de conductor",
    "Nombre cliente", "CD de origen", "Estado",
    "Razón de la no entrega en tienda", "Tiempo en destino (minutos)", "Precio",
)


def _secret(name: str) -> str:
    try:
        values = st.secrets.to_dict() if hasattr(st.secrets, "to_dict") else st.secrets
    except Exception:
        values = {}

    def find(value: Any) -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).strip().upper() == name.upper() and item not in (None, ""):
                    return str(item).strip()
                nested = find(item)
                if nested:
                    return nested
        return ""

    return find(values) or os.environ.get(name, "").strip()


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"none", "nan", "null", "<na>"} else text


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if not (isinstance(value, float) and math.isnan(value)) else None
    text = _text(value).replace("$", "").replace(" ", "")
    if not text:
        return None
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _identifier(value: Any) -> str:
    """Normaliza IDs de Excel sin alterar el valor visible al usuario."""
    text = _text(value).replace(" ", "").upper()
    return text[:-2] if text.endswith(".0") else text


def _order_base(value: Any) -> str:
    return re.sub(r"-\d+$", "", _identifier(value))


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _status(value: Any) -> str:
    normalized = _key(value)
    if "no entreg" in normalized:
        return "No entregado"
    if "entreg" in normalized:
        return "Entregado"
    return "Pendiente"


def _reason(value: Any) -> str:
    normalized = _key(value)
    if not normalized:
        return "Sin motivo"
    if "cerrad" in normalized:
        return "Tienda cerrada"
    if "cancel" in normalized:
        return "Cancelación"
    if any(item in normalized for item in ("sin orden", "sin hoja", "hoja ni", "no traigo", "sin producto")):
        return "Sin orden / producto"
    if any(item in normalized for item in ("carg", "salio", "salió")):
        return "No se cargó en CD"
    return "Otro"


def _pretty_name(value: str) -> str:
    return " ".join(word.lower() if word.lower() in {"de", "del", "la", "las"} else word.capitalize() for word in value.split())


def normalize_drivers(rows: list[dict[str, Any]]) -> None:
    raw_keys = [_key(row["Nombre de conductor"]) for row in rows]
    unique = sorted({value for value in raw_keys if value})
    remap: dict[str, str] = {}
    for candidate in unique:
        words = candidate.split()
        longer = [other for other in unique if other != candidate and other.split()[:len(words)] == words]
        remap[candidate] = longer[0] if len(longer) == 1 else candidate
    variants: dict[str, Counter[str]] = {}
    for row, raw_key in zip(rows, raw_keys):
        final_key = remap.get(raw_key, "")
        if final_key:
            variants.setdefault(final_key, Counter())[_text(row["Nombre de conductor"])] += 1
        row["conductor"] = final_key
    frequency = Counter(row["conductor"] for row in rows if row["conductor"])
    for row in rows:
        normalized = row["conductor"]
        if normalized and frequency[normalized]:
            names = variants[normalized]
            display = max(names, key=lambda name: (names[name], len(name.split()), name))
            row["conductor"] = _pretty_name(display)
        else:
            row["conductor"] = "Sin capturar"


def prepare_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in records:
        row = {_text(key): _text(value) for key, value in source.items()}
        order = _identifier(row.get("Orden", ""))
        row["Orden"] = order
        row["orden_base"] = _order_base(order)
        row["fecha_ruta"] = _date(row.get("Fecha ruta"))
        row["Estado"] = _status(row.get("Estado"))
        delivered = row["Estado"] == "Entregado"
        row["min_en_tienda"] = _number(row.get("Tiempo en destino (minutos)")) if delivered else None
        row["valor_entregado"] = (_number(row.get("Precio")) or 0.0) if delivered else 0.0
        row["motivo"] = _reason(row.get("Razón de la no entrega en tienda")) if not delivered else ""
        rows.append(row)
    normalize_drivers(rows)
    return rows


def _records_from_sheet(sheet: Any, header_row: int) -> tuple[list[dict[str, Any]], list[str]]:
    iterator = sheet.iter_rows(values_only=True)
    for _ in range(header_row - 1):
        next(iterator, ())
    headers = [_text(value) for value in next(iterator, ())]
    positions = {header: index for index, header in enumerate(headers) if header}
    records: list[dict[str, Any]] = []
    for values in iterator:
        if any(value not in (None, "") for value in values):
            records.append({header: values[index] if index < len(values) else "" for header, index in positions.items()})
    return records, headers


def _find_header_row(sheet: Any, required: str, limit: int = 40) -> int:
    """TRANSFERS tiene metadatos Aleph antes de su encabezado real."""
    expected = _key(required)
    for row_number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
        if row_number > limit:
            break
        if expected in {_key(value) for value in values if _text(value)}:
            return row_number
    raise ValueError(f"No encontré el encabezado {required} en {sheet.title}.")


def prepare_transfers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for source in records:
        row = {_text(key): _text(value) for key, value in source.items()}
        transfer_id = _identifier(row.get("TRANSFER_ID"))
        if not transfer_id:
            continue
        row["TRANSFER_ID"] = transfer_id
        row["SAP_ID"] = _identifier(row.get("SAP_ID"))
        for field in ("ORDERED", "PICKED", "DELIVERED", "TOTAL_M3", "TOTAL_PESO"):
            row[field] = _number(row.get(field)) or 0.0
        prepared.append(row)
    return prepared


def prepare_directions(records: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    directions: dict[str, dict[str, str]] = {}
    for source in records:
        warehouse_id = _identifier(source.get("WAREHOUSE_ID"))
        if warehouse_id:
            directions[warehouse_id] = {
                "ciudad": _text(source.get("CITY")),
                "tienda_canonica": _text(source.get("WAREHOUSE_NAME")),
                "direccion_canonica": _text(source.get("ADDRES")),
            }
    return directions


def build_logistics_model(
    dispatch_rows: list[dict[str, Any]],
    transfer_rows: list[dict[str, Any]],
    directions: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enlaza DT con Aleph sin usar nombre/dirección como llave de decisión."""
    directions = directions or {}
    by_transfer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_sap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transfer in transfer_rows:
        by_transfer[_identifier(transfer.get("TRANSFER_ID"))].append(transfer)
        sap_id = _identifier(transfer.get("SAP_ID"))
        if sap_id:
            by_sap[sap_id].append(transfer)

    enriched: list[dict[str, Any]] = []
    for original in dispatch_rows:
        row = dict(original)
        order = _identifier(row.get("Orden"))
        candidates = by_sap.get(order, [])
        method = "SAP exacto" if candidates else "Sin match"
        if not candidates:
            candidates = by_transfer.get(order, [])
            method = "Transfer exacta" if candidates else "Sin match"
        if not candidates:
            candidates = by_transfer.get(_order_base(order), [])
            method = "Transfer partida" if candidates else "Sin match"
        if len(candidates) != 1:
            method = "Ambiguo" if candidates else "Sin match"
            row.update({
                "match_transfer": method,
                "transfer_id": "",
                "sap_id": "",
                "tienda_canonica": "",
                "direccion_canonica": "",
                "ciudad_destino": "",
            })
            enriched.append(row)
            continue
        transfer = candidates[0]
        direction = directions.get(_identifier(transfer.get("DESTINATION_WAREHOUSE_ID")), {})
        row.update({
            "match_transfer": method,
            "transfer_id": _identifier(transfer.get("TRANSFER_ID")),
            "sap_id": _identifier(transfer.get("SAP_ID")),
            "tienda_canonica": direction.get("tienda_canonica") or _text(transfer.get("DESTINATION_WAREHOUSE_NAME")),
            "direccion_canonica": direction.get("direccion_canonica"),
            "ciudad_destino": direction.get("ciudad") or _text(transfer.get("DESTINATION_CITY")),
            "ordered": _number(transfer.get("ORDERED")) or 0.0,
            "picked": _number(transfer.get("PICKED")) or 0.0,
            "delivered": _number(transfer.get("DELIVERED")) or 0.0,
        })
        enriched.append(row)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        if row.get("transfer_id"):
            grouped[row["transfer_id"]].append(row)
    transfers: list[dict[str, Any]] = []
    for transfer_id, legs in grouped.items():
        statuses = {leg["Estado"] for leg in legs}
        if statuses == {"Entregado"}:
            consolidated = "Entregado"
        elif "Entregado" in statuses:
            consolidated = "Parcial"
        elif "No entregado" in statuses:
            consolidated = "No entregado"
        else:
            consolidated = "Pendiente"
        drivers = sorted({leg["conductor"] for leg in legs if leg.get("conductor") and leg["conductor"] != "Sin capturar"})
        first = legs[0]
        transfers.append({
            "transfer_id": transfer_id,
            "sap_id": first.get("sap_id", ""),
            "órdenes DT": ", ".join(sorted({leg["Orden"] for leg in legs})),
            "partes DT": len(legs),
            "estado consolidado": consolidated,
            "conductor": drivers[0] if len(drivers) == 1 else ("Compartido" if drivers else "Sin capturar"),
            "tienda canónica": first.get("tienda_canonica", ""),
            "dirección canónica": first.get("direccion_canonica", ""),
            "ciudad": first.get("ciudad_destino", ""),
            "ordered": first.get("ordered", 0.0),
            "picked": first.get("picked", 0.0),
            "delivered": first.get("delivered", 0.0),
            "fill picking": (first.get("picked", 0.0) / first.get("ordered", 0.0)) if first.get("ordered", 0.0) else None,
            "fill entrega": (first.get("delivered", 0.0) / first.get("picked", 0.0)) if first.get("picked", 0.0) else None,
            "fill total": (first.get("delivered", 0.0) / first.get("ordered", 0.0)) if first.get("ordered", 0.0) else None,
        })
    return enriched, transfers


@st.cache_data(ttl=300, show_spinner=False)
def load_logistics_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, str]], list[str]]:
    """Carga una sola exportación de DATA_LOGISTICS para no duplicar memoria/red."""
    sheet_id = _secret("DATA_LOGISTICS_ID")
    if not sheet_id:
        raise ValueError("Falta DATA_LOGISTICS_ID en Secrets.")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    with urllib.request.urlopen(url, timeout=90) as response:
        raw = response.read()
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    try:
        missing_sheets = [name for name in (SHEET_NAME, TRANSFERS_SHEET_NAME) if name not in workbook.sheetnames]
        if missing_sheets:
            raise ValueError(f"DATA_LOGISTICS no contiene: {', '.join(missing_sheets)}.")
        records, headers = _records_from_sheet(workbook[SHEET_NAME], 1)
        positions = {header: index for index, header in enumerate(headers) if header}
        missing = [header for header in REQUIRED_HEADERS if header not in positions]
        if missing:
            raise ValueError(
                f"DISPATCH_TRACK no tiene las columnas requeridas: {', '.join(missing)}."
            )
        transfers_sheet = workbook[TRANSFERS_SHEET_NAME]
        transfer_records, _ = _records_from_sheet(
            transfers_sheet, _find_header_row(transfers_sheet, "TRANSFER_ID")
        )
        direction_records: list[dict[str, Any]] = []
        if DIRECTIONS_SHEET_NAME in workbook.sheetnames:
            direction_records, _ = _records_from_sheet(workbook[DIRECTIONS_SHEET_NAME], 1)
    finally:
        workbook.close()
    return prepare_rows(records), prepare_transfers(transfer_records), prepare_directions(direction_records), headers


def load_dispatch_track() -> tuple[list[dict[str, Any]], list[str]]:
    """Compatibilidad para pruebas y consumidores que sólo requieren DispatchTrack."""
    rows, _, _, headers = load_logistics_snapshot()
    return rows, headers


def _kpi(label: str, value: str, description: str, tone: str = "acid") -> str:
    return (
        f'<div class="foxhound-kpi {tone}"><div class="foxhound-kpi-label">{label}</div>'
        f'<div class="foxhound-kpi-value">{value}</div><div class="foxhound-kpi-description">{description}</div></div>'
    )


def _inject_foxhound_style() -> None:
    st.markdown(
        """
        <style>
        .foxhound-kpi { min-height: 132px; border:3px solid #111; box-shadow:5px 5px 0 #111; padding:13px 15px; margin:0 6px 16px 0; box-sizing:border-box; }
        .foxhound-kpi.acid { background:#d9ff3f; }.foxhound-kpi.coral { background:#ff5a47; }.foxhound-kpi.blue { background:#5e7cff; color:#fffdf7; }.foxhound-kpi.white { background:#fffdf7; }
        .foxhound-kpi-label { font-size:.68rem; font-weight:900; letter-spacing:.08em; }.foxhound-kpi-value { font-family:"Archivo Black",sans-serif; font-size:1.75rem; line-height:1; margin:12px 0 8px; }.foxhound-kpi-description { font-size:.65rem; font-weight:700; line-height:1.25; }
        .foxhound-note { border:2px solid #111; background:#e8edff; padding:12px 14px; margin:8px 0 18px; font-size:.78rem; font-weight:700; }
        .foxhound-chart { border:3px solid #111; box-shadow:5px 5px 0 #111; background:#fffdf7; padding:15px; margin:7px 6px 22px 0; }
        .foxhound-chart-title { font-family:"Archivo Black",sans-serif; font-size:.96rem; margin-bottom:13px; }
        .foxhound-legend { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px; font-size:.65rem; font-weight:800; }.foxhound-legend span { display:flex; align-items:center; gap:5px; }.foxhound-dot { width:10px; height:10px; border:1px solid #111; display:inline-block; }
        .foxhound-bar-row { display:grid; grid-template-columns:minmax(96px, 34%) 1fr 42px; gap:8px; align-items:center; margin:7px 0; font-size:.69rem; font-weight:700; }.foxhound-bar-label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.foxhound-bar-track { height:19px; background:#ece8dc; border:1px solid #111; display:flex; overflow:hidden; }.foxhound-bar-segment { height:100%; min-width:0; }.foxhound-bar-total { text-align:right; font-weight:900; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_stacked_bars(rows: list[dict[str, Any]], field: str, top: int, title: str) -> None:
    """Gráfica HTML sin depender del bundle dinámico Plotly de Streamlit."""
    counts: dict[str, Counter[str]] = {}
    for row in rows:
        label = _text(row.get(field)) or "Sin capturar"
        counts.setdefault(label, Counter())[row["Estado"]] += 1
    labels = sorted(counts, key=lambda item: (-sum(counts[item].values()), item))[:top]
    maximum = max((sum(counts[label].values()) for label in labels), default=1)
    legend = "".join(f'<span><i class="foxhound-dot" style="background:{STATUS_COLORS[status]}"></i>{status}</span>' for status in STATUS_ORDER)
    content = []
    for label in labels:
        total = sum(counts[label].values())
        segments = "".join(f'<i class="foxhound-bar-segment" style="background:{STATUS_COLORS[status]};width:{counts[label][status] / maximum * 100:.4f}%" title="{status}: {counts[label][status]}"></i>' for status in STATUS_ORDER if counts[label][status])
        content.append(f'<div class="foxhound-bar-row"><div class="foxhound-bar-label" title="{html.escape(label)}">{html.escape(label)}</div><div class="foxhound-bar-track">{segments}</div><div class="foxhound-bar-total">{total:,}</div></div>')
    st.markdown(f'<div class="foxhound-chart"><div class="foxhound-chart-title">{html.escape(title)}</div><div class="foxhound-legend">{legend}</div>{"".join(content) or "Sin datos."}</div>', unsafe_allow_html=True)


def _render_daily_bars(rows: list[dict[str, Any]]) -> None:
    counts: dict[date, Counter[str]] = {}
    for row in rows:
        if row["fecha_ruta"]:
            counts.setdefault(row["fecha_ruta"], Counter())[row["Estado"]] += 1
    labels = sorted(counts)
    mapped = [{"fecha": label.isoformat(), "Estado": status} for label in labels for status, amount in counts[label].items() for _ in range(amount)]
    _render_stacked_bars(mapped, "fecha", len(labels), "ÓRDENES POR DÍA DE RUTA")


def _csv_bytes(rows: list[dict[str, Any]], headers: list[str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _rate_label(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "—"


def driver_leaderboard(transfers: list[dict[str, Any]], minimum_transfers: int = 5) -> list[dict[str, Any]]:
    """Atribuye métricas Aleph sólo cuando una transferencia tiene un conductor único."""
    grouped: dict[str, dict[str, Any]] = {}
    for transfer in transfers:
        driver = _text(transfer.get("conductor"))
        if driver in {"", "Sin capturar", "Compartido"}:
            continue
        metric = grouped.setdefault(driver, {
            "conductor": driver, "transferencias": 0, "ordered": 0.0,
            "picked": 0.0, "delivered": 0.0, "entregadas": 0,
            "no entregadas": 0, "pendientes": 0,
        })
        metric["transferencias"] += 1
        for field in ("ordered", "picked", "delivered"):
            metric[field] += float(transfer.get(field, 0.0) or 0.0)
        status = transfer.get("estado consolidado")
        if status == "Entregado":
            metric["entregadas"] += 1
        elif status in {"No entregado", "Parcial"}:
            metric["no entregadas"] += 1
        else:
            metric["pendientes"] += 1
    result: list[dict[str, Any]] = []
    for metric in grouped.values():
        metric["fill entrega"] = _rate(metric["delivered"], metric["picked"])
        metric["fill total"] = _rate(metric["delivered"], metric["ordered"])
        metric["cumplimiento DT"] = _rate(metric["entregadas"], metric["entregadas"] + metric["no entregadas"])
        metric["elegible"] = metric["transferencias"] >= minimum_transfers
        result.append(metric)
    return sorted(result, key=lambda item: (item["fill entrega"] is None, -(item["fill entrega"] or 0), -item["transferencias"], item["conductor"]))


def _rank_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "Conductor": row["conductor"],
        "Transferencias": row["transferencias"],
        "Fill entrega": _rate_label(row["fill entrega"]),
        "Fill total": _rate_label(row["fill total"]),
        "Cumplimiento DT": _rate_label(row["cumplimiento DT"]),
        "Pendientes": row["pendientes"],
    } for row in rows]


def render() -> None:
    render_system_stamp("MODULE 03 / FOXHOUND")
    _inject_foxhound_style()
    st.markdown(
        '<section class="mb-hero"><span class="mb-kicker">MODULE / 03 · LOGISTICS COMMAND</span><h1>FOXHOUND.</h1><p>Seguimiento táctico de entregas, flota y cumplimiento de DispatchTrack.</p></section>',
        unsafe_allow_html=True,
    )
    try:
        raw_rows, transfer_rows, directions, source_headers = load_logistics_snapshot()
    except Exception as error:
        st.error(f"No se pudo cargar DISPATCH_TRACK / TRANSFERS desde DATA_LOGISTICS: {error}")
        return
    if not raw_rows:
        st.info("DISPATCH_TRACK no tiene órdenes para mostrar.")
        return

    cds = sorted({_text(row.get("CD de origen")) for row in raw_rows if _text(row.get("CD de origen"))})
    selected_cd = st.radio("Centro de distribución", ["Todos", *cds], horizontal=True, key="foxhound_cd")
    selected_rows = raw_rows if selected_cd == "Todos" else [row for row in raw_rows if _text(row.get("CD de origen")) == selected_cd]
    filtered, transfers = build_logistics_model(selected_rows, transfer_rows, directions)
    dates = [row["fecha_ruta"] for row in filtered if row["fecha_ruta"]]
    matched = [row for row in filtered if row.get("transfer_id")]
    unmatched = [row for row in filtered if not row.get("transfer_id")]
    split_legs = [row for row in matched if row["match_transfer"] == "Transfer partida"]
    st.markdown(
        f'<div class="foxhound-note">{len(filtered):,} eventos DispatchTrack · {len(transfers):,} transferencias canónicas · rutas del {min(dates).isoformat() if dates else "sin fecha"} al {max(dates).isoformat() if dates else "sin fecha"} · {len({_text(row.get("Identificador")) for row in filtered if _text(row.get("Identificador"))}):,} unidades.</div>',
        unsafe_allow_html=True,
    )

    delivered = sum(row["Estado"] == "Entregado" for row in filtered)
    not_delivered = sum(row["Estado"] == "No entregado" for row in filtered)
    pending = sum(row["Estado"] == "Pendiente" for row in filtered)
    drivers = {row["conductor"] for row in filtered if row["conductor"] != "Sin capturar"}
    minutes = sorted(row["min_en_tienda"] for row in filtered if row["min_en_tienda"] is not None)
    median = minutes[len(minutes) // 2] if minutes else None
    delivered_value = sum(float(row["valor_entregado"]) for row in filtered)
    ordered = sum(float(row.get("ordered", 0.0) or 0.0) for row in transfers)
    picked = sum(float(row.get("picked", 0.0) or 0.0) for row in transfers)
    delivered_units = sum(float(row.get("delivered", 0.0) or 0.0) for row in transfers)
    kpis = [
        ("TRAZABILIDAD ALEPH", f"{len(matched) / len(filtered):.1%}" if filtered else "—", f"{len(matched):,} matches seguros · {len(unmatched):,} sin match.", "acid"),
        ("FILL PICKING", _rate_label(_rate(picked, ordered)), "Unidades picked / ordered. Desempeño CEDIS.", "white"),
        ("FILL ENTREGA", _rate_label(_rate(delivered_units, picked)), "Unidades delivered / picked. Resultado logístico.", "acid"),
        ("FILL TOTAL", _rate_label(_rate(delivered_units, ordered)), "Unidades delivered / ordered de punta a punta.", "acid"),
        ("TASA DE ENTREGA DT", _rate_label(_rate(delivered, delivered + not_delivered)), "Eventos entregados sobre cierres de DispatchTrack.", "white"),
        ("NO ENTREGADAS", f"{not_delivered:,}", "Eventos cerrados sin entrega.", "coral"),
        ("PENDIENTES", f"{pending:,}", "No se castigan como no entrega hasta cierre.", "blue"),
        ("TIEMPO EN TIENDA", f"{round(median):,} min" if median is not None else "—", "Mediana de eventos entregados.", "white"),
    ]
    for start in range(0, len(kpis), 4):
        columns = st.columns(4)
        for column, (label, value, description, tone) in zip(columns, kpis[start:start + 4]):
            with column:
                st.markdown(_kpi(label, value, description, tone), unsafe_allow_html=True)

    st.markdown('<span class="section-label">DESEMPEÑO DE CONDUCTORES · TRANSFERENCIAS CON PROPIETARIO ÚNICO</span>', unsafe_allow_html=True)
    leaderboard = driver_leaderboard(transfers)
    eligible = [row for row in leaderboard if row["elegible"] and row["fill entrega"] is not None]
    shared = sum(1 for row in transfers if row["conductor"] == "Compartido")
    st.markdown(
        f'<div class="foxhound-note">El ranking exige al menos 5 transferencias y excluye {shared:,} transferencias compartidas, para no adjudicar dos veces el mismo fill rate.</div>',
        unsafe_allow_html=True,
    )
    best, worst = st.columns(2)
    with best:
        st.markdown('<span class="section-label">MEJOR FILL DE ENTREGA</span>', unsafe_allow_html=True)
        st.dataframe(_rank_view(eligible[:10]), use_container_width=True, hide_index=True)
    with worst:
        st.markdown('<span class="section-label">PEOR FILL DE ENTREGA</span>', unsafe_allow_html=True)
        st.dataframe(_rank_view(list(reversed(eligible[-10:]))), use_container_width=True, hide_index=True)

    st.markdown('<span class="section-label">ORDENES POR DÍA DE RUTA</span>', unsafe_allow_html=True)
    _render_daily_bars(filtered)
    first, second = st.columns(2)
    with first:
        _render_stacked_bars(filtered, "Identificador", 15, "CAMIONES · TOP 15")
    with second:
        driver_rows = [row for row in filtered if row["conductor"] != "Sin capturar"]
        _render_stacked_bars(driver_rows, "conductor", 24, "CONDUCTORES · TOP 24")

    no_delivery = [row for row in filtered if row["Estado"] == "No entregado"]
    third, fourth = st.columns(2)
    with third:
        _render_stacked_bars(no_delivery, "Nombre cliente", 10, "TIENDAS CON MÁS NO ENTREGAS")
    with fourth:
        reason_rows = [{"motivo": row["motivo"], "Estado": "Pendiente"} for row in no_delivery]
        _render_stacked_bars(reason_rows, "motivo", 10, "MOTIVOS DE NO ENTREGA")

    st.markdown('<span class="section-label">CONTROL DE TRAZABILIDAD Y EXCEPCIONES</span>', unsafe_allow_html=True)
    audit_left, audit_right = st.columns(2)
    with audit_left:
        st.markdown(f'<div class="foxhound-note"><b>Pedidos partidos:</b> {len(split_legs):,} eventos ligados por su orden base. El nombre o la dirección modificados por DispatchTrack no se usan para el match.</div>', unsafe_allow_html=True)
        split_transfers = [transfer for transfer in transfers if transfer["partes DT"] > 1]
        st.dataframe(split_transfers[:150], use_container_width=True, hide_index=True)
    with audit_right:
        st.markdown(f'<div class="foxhound-note"><b>Sin match:</b> {len(unmatched):,} eventos. Se mantienen separados hasta que Aleph exponga su TRANSFER_ID o SAP_ID; no se fuerza una coincidencia por tienda.</div>', unsafe_allow_html=True)
        unmatched_view = [{"Orden DT": row["Orden"], "Fecha ruta": row.get("fecha_ruta"), "Estado": row["Estado"], "Tienda DT": row.get("Nombre cliente", ""), "Conductor": row.get("conductor", "")} for row in unmatched]
        st.dataframe(unmatched_view[:150], use_container_width=True, hide_index=True)

    st.markdown('<span class="section-label">BUSCADOR DE EVENTOS DISPATCHTRACK</span>', unsafe_allow_html=True)
    query = st.text_input("Orden, tienda, camión, conductor o estado", key="foxhound_search")
    display_headers = ["Orden", "orden_base", "transfer_id", "match_transfer", "fecha_ruta", "Identificador", "conductor", "Nombre cliente", "tienda_canonica", "CD de origen", "Estado", "motivo"]
    view = sorted(filtered, key=lambda row: row["fecha_ruta"] or date.min, reverse=True)
    if query.strip():
        needle = _key(query)
        view = [row for row in view if needle in _key(" ".join(str(row.get(header, "")) for header in display_headers))]
    shown = view[:500]
    if len(view) > len(shown):
        st.caption(f"Mostrando 500 de {len(view):,} órdenes. Descarga el CSV para ver todas.")
    st.dataframe([{header: row.get(header, "") for header in display_headers} for row in shown], use_container_width=True, hide_index=True)
    st.download_button("DESCARGAR EVENTOS Y MATCHES (.CSV)", data=_csv_bytes(view, source_headers + ["orden_base", "conductor", "motivo", "match_transfer", "transfer_id", "sap_id", "tienda_canonica", "direccion_canonica", "ciudad_destino", "ordered", "picked", "delivered"]), file_name="FOXHOUND_eventos_matcheados.csv", mime="text/csv", use_container_width=True, key="foxhound_download")
    if st.button("← VOLVER A MOTHER BASE", key="foxhound_back_home"):
        st.session_state["mb_module"] = "MOTHER BASE"
        st.rerun()
