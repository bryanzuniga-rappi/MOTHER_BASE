"""FOXHOUND — comando logístico y seguimiento de entregas DispatchTrack."""

from __future__ import annotations

from collections import Counter
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
        order = row.get("Orden", "")
        if order.endswith(".0"):
            order = order[:-2]
        row["Orden"] = order
        row["orden_base"] = re.sub(r"-\d+$", "", order)
        row["fecha_ruta"] = _date(row.get("Fecha ruta"))
        row["Estado"] = _status(row.get("Estado"))
        delivered = row["Estado"] == "Entregado"
        row["min_en_tienda"] = _number(row.get("Tiempo en destino (minutos)")) if delivered else None
        row["valor_entregado"] = (_number(row.get("Precio")) or 0.0) if delivered else 0.0
        row["motivo"] = _reason(row.get("Razón de la no entrega en tienda")) if not delivered else ""
        rows.append(row)
    normalize_drivers(rows)
    return rows


@st.cache_data(ttl=300, show_spinner=False)
def load_dispatch_track() -> tuple[list[dict[str, Any]], list[str]]:
    sheet_id = _secret("DATA_LOGISTICS_ID")
    if not sheet_id:
        raise ValueError("Falta DATA_LOGISTICS_ID en Secrets.")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    with urllib.request.urlopen(url, timeout=90) as response:
        raw = response.read()
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise ValueError(f"DATA_LOGISTICS no contiene la hoja {SHEET_NAME}.")
        sheet = workbook[SHEET_NAME]
        iterator = sheet.iter_rows(values_only=True)
        headers = [_text(value) for value in next(iterator, ())]
        positions = {header: index for index, header in enumerate(headers) if header}
        missing = [header for header in REQUIRED_HEADERS if header not in positions]
        if missing:
            raise ValueError(
                f"DISPATCH_TRACK no tiene las columnas requeridas: {', '.join(missing)}."
            )
        records = []
        for values in iterator:
            if not any(value not in (None, "") for value in values):
                continue
            records.append({header: values[index] if index < len(values) else "" for header, index in positions.items()})
    finally:
        workbook.close()
    return prepare_rows(records), headers


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


def render() -> None:
    render_system_stamp("MODULE 03 / FOXHOUND")
    _inject_foxhound_style()
    st.markdown(
        '<section class="mb-hero"><span class="mb-kicker">MODULE / 03 · LOGISTICS COMMAND</span><h1>FOXHOUND.</h1><p>Seguimiento táctico de entregas, flota y cumplimiento de DispatchTrack.</p></section>',
        unsafe_allow_html=True,
    )
    try:
        rows, source_headers = load_dispatch_track()
    except Exception as error:
        st.error(f"No se pudo cargar DISPATCH_TRACK desde DATA_LOGISTICS: {error}")
        return
    if not rows:
        st.info("DISPATCH_TRACK no tiene órdenes para mostrar.")
        return

    cds = sorted({_text(row.get("CD de origen")) for row in rows if _text(row.get("CD de origen"))})
    selected_cd = st.radio("Centro de distribución", ["Todos", *cds], horizontal=True, key="foxhound_cd")
    filtered = rows if selected_cd == "Todos" else [row for row in rows if _text(row.get("CD de origen")) == selected_cd]
    dates = [row["fecha_ruta"] for row in filtered if row["fecha_ruta"]]
    st.markdown(
        f'<div class="foxhound-note">{len(filtered):,} órdenes · rutas del {min(dates).isoformat() if dates else "sin fecha"} al {max(dates).isoformat() if dates else "sin fecha"} · {len({_text(row.get("Identificador")) for row in filtered if _text(row.get("Identificador"))}):,} unidades.</div>',
        unsafe_allow_html=True,
    )

    delivered = sum(row["Estado"] == "Entregado" for row in filtered)
    not_delivered = sum(row["Estado"] == "No entregado" for row in filtered)
    pending = sum(row["Estado"] == "Pendiente" for row in filtered)
    drivers = {row["conductor"] for row in filtered if row["conductor"] != "Sin capturar"}
    minutes = sorted(row["min_en_tienda"] for row in filtered if row["min_en_tienda"] is not None)
    median = minutes[len(minutes) // 2] if minutes else None
    delivered_value = sum(float(row["valor_entregado"]) for row in filtered)
    kpis = [
        ("TASA DE ENTREGA", f"{delivered / (delivered + not_delivered):.1%}" if delivered + not_delivered else "—", "Entregadas sobre entregadas + no entregadas.", "acid"),
        ("ENTREGADAS", f"{delivered:,}", "Órdenes finalizadas correctamente.", "acid"),
        ("NO ENTREGADAS", f"{not_delivered:,}", "Requieren revisión operativa.", "coral"),
        ("PENDIENTES", f"{pending:,}", "No se consideran en la tasa de entrega.", "blue"),
        ("CONDUCTORES", f"{len(drivers):,}", "Distintos, sin registros sin capturar.", "white"),
        ("MEDIANA EN TIENDA", f"{round(median):,} min" if median is not None else "—", "Sólo órdenes entregadas.", "white"),
        ("VALOR ENTREGADO", f"${delivered_value / 1_000_000:,.1f} M", "Precio de órdenes entregadas.", "acid"),
    ]
    for start in range(0, len(kpis), 4):
        columns = st.columns(4)
        for column, (label, value, description, tone) in zip(columns, kpis[start:start + 4]):
            with column:
                st.markdown(_kpi(label, value, description, tone), unsafe_allow_html=True)

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

    st.markdown('<span class="section-label">BUSCADOR DE ÓRDENES</span>', unsafe_allow_html=True)
    query = st.text_input("Orden, tienda, camión, conductor o estado", key="foxhound_search")
    display_headers = ["Orden", "orden_base", "fecha_ruta", "Identificador", "conductor", "Nombre cliente", "CD de origen", "Estado", "motivo"]
    view = sorted(filtered, key=lambda row: row["fecha_ruta"] or date.min, reverse=True)
    if query.strip():
        needle = _key(query)
        view = [row for row in view if needle in _key(" ".join(str(row.get(header, "")) for header in display_headers))]
    shown = view[:500]
    if len(view) > len(shown):
        st.caption(f"Mostrando 500 de {len(view):,} órdenes. Descarga el CSV para ver todas.")
    st.dataframe([{header: row.get(header, "") for header in display_headers} for row in shown], use_container_width=True, hide_index=True)
    st.download_button("DESCARGAR ÓRDENES FILTRADAS (.CSV)", data=_csv_bytes(view, source_headers + ["orden_base", "conductor", "motivo"]), file_name="FOXHOUND_ordenes.csv", mime="text/csv", use_container_width=True, key="foxhound_download")
    if st.button("← VOLVER A MOTHER BASE", key="foxhound_back_home"):
        st.session_state["mb_module"] = "MOTHER BASE"
        st.rerun()
