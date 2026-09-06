"""Dashboard de comando AVL/SWA para Militaires Sans Frontières (Mother Base)."""

from __future__ import annotations

from collections import defaultdict
import html
import io
import re
import urllib.error
import urllib.request
import zipfile

import openpyxl
import streamlit as st

from mother_base_theme import render_system_stamp

DATA_DASHBOARD_SPREADSHEET_ID = "174wMJVmpXdeWEOmn4pamlsDaNcIF0ltE1sJjbUpMKsQ"

# --- Mismos valores de mother_base_theme.py (:root). No hardcodear otros hex aquí. ---
INK = "#111111"
ACID = "#d9ff3f"
BLUE = "#5e7cff"
CORAL = "#ff5a47"
ORANGE = "#ffb000"
WHITE = "#fffdf7"

# --- Umbrales de semáforo operativo. Ajustar si Supply define un SLA distinto. ---
AVL_HEALTHY, AVL_WARNING = 95.0, 90.0
SWA_HEALTHY, SWA_WARNING = 90.0, 80.0

HISTORY_WINDOWS = {"7 DÍAS": 7, "14 DÍAS": 14, "28 DÍAS": 28}


# ---------------------------------------------------------------------------
# Capa de datos (misma lógica del módulo original, sin cambios funcionales)
# ---------------------------------------------------------------------------

def _header(value: object) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().upper())


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_dashboard() -> bytes:
    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{DATA_DASHBOARD_SPREADSHEET_ID}/export?format=xlsx"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MotherBase/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            "No pude leer DATA_DASHBOARD. Confirma que el Sheet sea público para lectura."
        ) from exc
    if not payload or not zipfile.is_zipfile(io.BytesIO(payload)):
        raise RuntimeError("DATA_DASHBOARD no devolvió un archivo Excel válido.")
    return payload


def _records(workbook, sheet_name: str, required: set[str]):
    if sheet_name not in workbook.sheetnames:
        raise ValueError(f"Falta la hoja {sheet_name!r} en DATA_DASHBOARD.")
    ws = workbook[sheet_name]
    positions = None
    header_row = None
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, max_col=45, values_only=True), 1):
        found = {_header(value): col for col, value in enumerate(row) if _header(value)}
        if required.issubset(found):
            positions, header_row = found, idx
            break
    if positions is None:
        raise ValueError(f"{sheet_name}: no encontré encabezados {sorted(required)}.")
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        record = {name: row[index] if index < len(row) else None for name, index in positions.items()}
        if any(value is not None and str(value).strip() for value in record.values()):
            yield record


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@st.cache_data(ttl=300, show_spinner=False)
def _load_metrics(payload: bytes) -> tuple[list[dict], list[dict]]:
    wb = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    try:
        current = list(_records(
            wb, "CURRENT_DATE",
            {"CITY", "WAREHOUSE_ID", "AVL_COUNTRY", "SWA_COUNTRY", "AVL_CITY", "SWA_CITY", "AVL_WH", "SWA_WH"},
        ))
        history = list(_records(
            wb, "28D",
            {"MAIN_DATE", "CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "BUCKET_TYPE", "AVL", "SWA"},
        ))
    finally:
        wb.close()
    return current, history


# ---------------------------------------------------------------------------
# Capa visual — reutiliza .mb-card / .engine-panel / .mb-wip de mother_base_theme
# y solo agrega lo que ese archivo todavía no cubre (KPIs con tooltip, tabla con
# semáforo, tarjetas de insight y los contenedores nativos con key para filtros
# e histórico).
# ---------------------------------------------------------------------------

def _inject_style() -> None:
    st.markdown(
        """
        <style>
        /* Contenedores nativos con widgets reales: mismo tratamiento que
           .st-key-mission_control_shared en mother_base_theme.py (radio 10px,
           no 0 — ese radio solo aplica a las tarjetas HTML crudas). */
        .st-key-msf_filters [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-msf_history [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--white, #fffdf7) !important;
            border: 3px solid var(--ink, #111111) !important;
            border-radius: 10px !important;
            box-shadow: 7px 7px 0 var(--ink, #111111) !important;
        }

        .msf-note {
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.78rem;
            color: var(--ink, #111111);
            opacity: 0.65;
            margin: 6px 0 4px 0;
        }

        /* --- KPIs: .engine-panel ya trae borde/sombra/tono; solo se agrega
           la tipografía de label/valor y el tooltip con retraso de 1s. --- */
        .msf-kpi-row { display: flex; gap: 16px; flex-wrap: wrap; }
        .msf-kpi { position: relative; flex: 1 1 220px; }
        .msf-kpi-label {
            display: block;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .msf-kpi-value {
            font-family: "Archivo Black", sans-serif;
            font-size: 2.1rem;
            line-height: 1;
        }
        .msf-kpi[data-tip]::after {
            content: attr(data-tip);
            position: absolute;
            left: 0;
            top: calc(100% + 8px);
            z-index: 20;
            width: max-content;
            max-width: 260px;
            background: var(--ink, #111111);
            color: var(--white, #fffdf7);
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.72rem;
            line-height: 1.35;
            padding: 8px 10px;
            border: 2px solid var(--ink, #111111);
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transition: opacity 0.15s ease, visibility 0.15s ease;
        }
        .msf-kpi[data-tip]:hover::after {
            opacity: 1;
            visibility: visible;
            transition-delay: 1s;
        }

        /* --- Tabla operativa. Sin precedente en el tema base: se construye
           siguiendo su lenguaje (mono, bordes gruesos, sin blur). --- */
        table.msf-table {
            width: 100%;
            border-collapse: collapse;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.78rem;
            table-layout: fixed;
        }
        table.msf-table th {
            background: var(--ink, #111111);
            color: var(--white, #fffdf7);
            text-align: left;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 8px 10px;
            border: 2px solid var(--ink, #111111);
        }
        table.msf-table td {
            background: var(--white, #fffdf7);
            color: var(--ink, #111111);
            padding: 7px 10px;
            border: 2px solid var(--ink, #111111);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        /* Chip de estado con las mismas proporciones que .mb-wip. */
        .msf-badge {
            display: inline-block;
            font-family: "IBM Plex Mono", monospace;
            font-weight: 900;
            padding: 2px 6px;
            border: 2px solid var(--ink, #111111);
            font-size: 0.7rem;
        }
        .msf-badge--ok { background: var(--acid, #d9ff3f); }
        .msf-badge--warn { background: var(--orange, #ffb000); }
        .msf-badge--crit { background: var(--coral, #ff5a47); }

        .msf-insight-row { display: flex; gap: 16px; flex-wrap: wrap; }
        .msf-insight-row .mb-card {
            flex: 1 1 260px;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.85rem;
            font-weight: 600;
        }
        .msf-chip {
            display: inline-block;
            font-weight: 900;
            padding: 1px 6px;
            border: 2px solid var(--ink, #111111);
        }
        .msf-chip--ok { background: var(--acid, #d9ff3f); }
        .msf-chip--warn { background: var(--orange, #ffb000); }
        .msf-chip--crit { background: var(--coral, #ff5a47); }

        .msf-error-card {
            background: var(--coral, #ff5a47);
            border: 3px solid var(--ink, #111111);
            box-shadow: 7px 7px 0 var(--ink, #111111);
            padding: 18px 20px;
            font-family: "IBM Plex Mono", monospace;
            font-weight: 700;
            color: var(--ink, #111111);
            margin-bottom: 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _status(value: float, healthy: float, warning: float) -> tuple[str, str]:
    """Devuelve (etiqueta, clase_css) para un valor donde más alto es mejor."""
    if value >= healthy:
        return "SANO", "msf-badge--ok"
    if value >= warning:
        return "RIESGO", "msf-badge--warn"
    return "CRÍTICO", "msf-badge--crit"


def _kpi_card(label: str, value: str, tooltip: str, tone_class: str) -> str:
    return (
        f'<div class="engine-panel {tone_class} msf-kpi" data-tip="{html.escape(tooltip)}">'
        f'<span class="msf-kpi-label">{html.escape(label)}</span>'
        f'<span class="msf-kpi-value">{html.escape(value)}</span>'
        f"</div>"
    )


def _render_error(message: str) -> None:
    st.markdown(f'<div class="msf-error-card">⚠ {html.escape(message)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Render principal
# ---------------------------------------------------------------------------

def render() -> None:
    render_system_stamp("MODULE 02 / INTELLIGENCE")
    _inject_style()

    st.markdown(
        """
        <section class="mb-hero">
            <span class="mb-kicker">MILITAIRES SANS FRONTIÈRES</span>
            <span class="mb-wip" style="margin-left:10px;">WORK IN PROGRESS</span>
            <h1>NETWORK<br>PERFORMANCE.</h1>
            <p>Control de AVL, SWA y desempeño histórico de la red.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.spinner("SINCRONIZANDO INTELIGENCIA DE RED…"):
        try:
            current, history = _load_metrics(_fetch_dashboard())
        except Exception as exc:  # noqa: BLE001 — se muestra el error tal cual al operador
            _render_error(str(exc))
            if st.button("ACTUALIZAR INTELIGENCIA", key="msf_refresh_error"):
                _fetch_dashboard.clear()
                _load_metrics.clear()
                st.rerun()
            return

    if not current or not history:
        _render_error("DATA_DASHBOARD no contiene filas suficientes para construir el dashboard.")
        return

    # --- Barra de filtros: contenedor nativo con key, no HTML crudo, para que
    # los widgets queden realmente dentro de la tarjeta (ver nota de revisión). ---
    with st.container(border=True, key="msf_filters"):
        f_city, f_bucket, f_window, f_action = st.columns([1.4, 1.4, 1.2, 1])

        cities = sorted({str(row["CITY"]).strip() for row in current if row.get("CITY")})
        selected_city = f_city.selectbox("CIUDAD", ["TODAS"] + cities)

        bucket_options = sorted({str(row["BUCKET_TYPE"]).strip() for row in history if row.get("BUCKET_TYPE")})
        selected_bucket = f_bucket.selectbox(
            "CATÁLOGO / BUCKET",
            bucket_options,
            index=bucket_options.index("GENERAL") if "GENERAL" in bucket_options else 0,
        )

        window_label = f_window.selectbox("VENTANA HISTÓRICA", list(HISTORY_WINDOWS.keys()), index=2)

        f_action.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        if f_action.button("ACTUALIZAR INTELIGENCIA", key="msf_refresh_filters"):
            _fetch_dashboard.clear()
            _load_metrics.clear()
            st.rerun()

        st.markdown(
            '<p class="msf-note">EL BUCKET SOLO APLICA A LA EVOLUCIÓN HISTÓRICA Y A LA LECTURA OPERATIVA: '
            "CURRENT_DATE NO DESGLOSA AVL/SWA POR CATÁLOGO.</p>",
            unsafe_allow_html=True,
        )

    scope = [row for row in current if selected_city == "TODAS" or str(row["CITY"]).strip() == selected_city]
    first = current[0]
    if selected_city == "TODAS":
        avl = _number(first["AVL_COUNTRY"])
        swa = _number(first["SWA_COUNTRY"])
    else:
        city_row = next((row for row in scope if row.get("AVL_CITY") is not None), scope[0])
        avl, swa = _number(city_row["AVL_CITY"]), _number(city_row["SWA_CITY"])

    warehouses_medidos = len({row["WAREHOUSE_ID"] for row in scope})

    # --- Situación actual ---
    st.markdown("### SITUACIÓN ACTUAL")
    kpi_html = (
        '<div class="msf-kpi-row">'
        + _kpi_card(
            "AVL ACTUAL", f"{avl:.2f}%",
            "Available: % de SKUs del catálogo con inventario disponible en el corte más reciente.",
            "naked",
        )
        + _kpi_card(
            "SWA ACTUAL", f"{swa:.2f}%",
            "Stockout-Weighted Availability: disponibilidad ponderada por relevancia/venta del SKU.",
            "solidus",
        )
        + _kpi_card(
            "WAREHOUSES MEDIDOS", f"{warehouses_medidos:,}",
            "Número de warehouses con datos en el corte actual, dentro del filtro de ciudad seleccionado.",
            "",
        )
        + "</div>"
    )
    st.markdown(kpi_html, unsafe_allow_html=True)

    # --- Evolución histórica ---
    rows = [
        row for row in history
        if str(row["BUCKET_TYPE"]).strip() == selected_bucket
        and (selected_city == "TODAS" or str(row["CITY"]).strip() == selected_city)
    ]
    by_day: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[row["MAIN_DATE"]].append(row)

    trend = []
    for day, items in sorted(by_day.items(), key=lambda item: item[0]):
        trend.append({
            "FECHA": day,
            "AVL": round(sum(_number(x["AVL"]) for x in items) / len(items), 2),
            "SWA": round(sum(_number(x["SWA"]) for x in items) / len(items), 2),
        })

    window_days = HISTORY_WINDOWS[window_label]
    trend_window = trend[-window_days:]

    st.markdown("### EVOLUCIÓN HISTÓRICA")
    with st.container(border=True, key="msf_history"):
        if trend_window:
            st.line_chart(trend_window, x="FECHA", y=["AVL", "SWA"], color=[ACID, BLUE], height=280)
            st.dataframe(trend_window, use_container_width=True, hide_index=True)
        else:
            st.markdown(
                '<p class="msf-note">SIN DATOS HISTÓRICOS PARA ESTE CATÁLOGO/CIUDAD EN LA VENTANA SELECCIONADA.</p>',
                unsafe_allow_html=True,
            )

    # --- Lectura operativa ---
    latest_day = max(by_day) if by_day else None
    detail: list[dict] = []
    if latest_day is not None:
        for row in by_day[latest_day]:
            row_avl, row_swa = _number(row["AVL"]), _number(row["SWA"])
            detail.append({
                "CIUDAD": str(row["CITY"] or "—"),
                "WAREHOUSE": str(row["WAREHOUSE_NAME"] or "—"),
                "AVL": row_avl,
                "SWA": row_swa,
                "SKUS": int(_number(row.get("SKUS_IN_BL"))),
            })
        detail.sort(key=lambda r: (r["SWA"], r["AVL"]))

    st.markdown("### LECTURA OPERATIVA")
    if detail:
        rows_html = []
        for r in detail[:15]:
            avl_label, avl_class = _status(r["AVL"], AVL_HEALTHY, AVL_WARNING)
            swa_label, swa_class = _status(r["SWA"], SWA_HEALTHY, SWA_WARNING)
            rows_html.append(
                "<tr>"
                f"<td>{html.escape(r['CIUDAD'])}</td>"
                f"<td>{html.escape(r['WAREHOUSE'])}</td>"
                f"<td>{r['AVL']:.1f}% <span class='msf-badge {avl_class}'>{avl_label}</span></td>"
                f"<td>{r['SWA']:.1f}% <span class='msf-badge {swa_class}'>{swa_label}</span></td>"
                f"<td>{r['SKUS']:,}</td>"
                "</tr>"
            )
        table_html = (
            '<div class="mb-card" style="min-height:auto;">'
            "<table class='msf-table'><colgroup>"
            "<col style='width:20%'><col style='width:34%'><col style='width:20%'>"
            "<col style='width:20%'><col style='width:6%'></colgroup>"
            "<thead><tr><th>Ciudad</th><th>Warehouse</th><th>AVL</th><th>SWA</th><th>SKUs</th></tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
            '<p class="msf-note">TOP 15 TIENDAS CON MAYOR OPORTUNIDAD · CORTE MÁS RECIENTE DEL CATÁLOGO SELECCIONADO.</p>'
            "</div>"
        )
        st.markdown(table_html, unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="mb-card" style="min-height:auto;">'
            '<p class="msf-note">SIN TIENDAS PARA MOSTRAR CON LOS FILTROS ACTUALES.</p>'
            "</div>",
            unsafe_allow_html=True,
        )

    # --- Insights ---
    st.markdown("### INSIGHTS")
    insights: list[str] = []

    city_swa: dict[str, float] = {}
    for row in current:
        city = str(row.get("CITY") or "").strip()
        if city and city not in city_swa and row.get("SWA_CITY") is not None:
            city_swa[city] = _number(row["SWA_CITY"])
    if len(city_swa) > 1:
        worst_city, worst_value = min(city_swa.items(), key=lambda kv: kv[1])
        insights.append(
            f'<span class="msf-chip msf-chip--crit">{html.escape(worst_city)}</span> concentra la mayor '
            f"oportunidad de recuperación de SWA ({worst_value:.1f}%)."
        )

    below_avl = sum(1 for row in scope if _number(row.get("AVL_WH")) < AVL_WARNING)
    if scope:
        chip_tone = "msf-chip--crit" if below_avl > 0 else "msf-chip--ok"
        insights.append(
            f'<span class="msf-chip {chip_tone}">{below_avl}</span> warehouse(s) están debajo del umbral '
            f"de AVL ({AVL_WARNING:.0f}%)."
        )

    if len(trend) >= 2:
        delta_avl = trend[-1]["AVL"] - trend[0]["AVL"]
        delta_swa = trend[-1]["SWA"] - trend[0]["SWA"]
        avl_tone = "msf-chip--ok" if delta_avl >= 0 else "msf-chip--crit"
        swa_tone = "msf-chip--ok" if delta_swa >= 0 else "msf-chip--crit"
        arrow_avl = "▲" if delta_avl >= 0 else "▼"
        arrow_swa = "▲" if delta_swa >= 0 else "▼"
        insights.append(
            f"En la ventana de {window_label.lower()}, AVL se movió "
            f'<span class="msf-chip {avl_tone}">{arrow_avl} {abs(delta_avl):.1f} pts</span> y SWA '
            f'<span class="msf-chip {swa_tone}">{arrow_swa} {abs(delta_swa):.1f} pts</span>.'
        )

    if insights:
        cards = "".join(f'<div class="mb-card">{text}</div>' for text in insights)
        st.markdown(f'<div class="msf-insight-row">{cards}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="mb-card" style="min-height:auto;">'
            '<p class="msf-note">SIN DATOS SUFICIENTES PARA GENERAR INSIGHTS CON LOS FILTROS ACTUALES.</p>'
            "</div>",
            unsafe_allow_html=True,
        )
