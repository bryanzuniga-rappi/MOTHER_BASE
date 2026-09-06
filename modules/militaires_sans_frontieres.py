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
import polars as pl
import plotly.graph_objects as go
import streamlit as st

from mother_base_theme import render_system_stamp

# --- NUEVO ORIGEN DE DATOS ---
DATA_DASHBOARD_SPREADSHEET_ID = "174wMJVmpXdeWEOmn4pamlsDaNcIF0ltE1sJjbUpMKsQ"

# --- PALETA OBLIGATORIA (Brutalismo táctico de Mother Base) ---
INK = "#111111"
ACID = "#D4FF2A"
BLUE = "#5B7CFA"
CORAL = "#FF5A4A"
ORANGE = "#FFB000"
WHITE = "#FFFDF7"
BG = "#F2EFE6"

# --- Umbrales de semáforo operativo ---
AVL_HEALTHY, AVL_WARNING = 95.0, 90.0
SWA_HEALTHY, SWA_WARNING = 90.0, 80.0

HISTORY_WINDOWS = {"7 DÍAS": 7, "14 DÍAS": 14, "28 DÍAS": 28}


# ---------------------------------------------------------------------------
# Capa de datos
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
# Visual & Charts (Estricto Mother Base)
# ---------------------------------------------------------------------------

def _inject_style() -> None:
    st.markdown(
        f"""
        <style>
        /* Forzar fondo base */
        .stApp {{ background-color: {BG} !important; }}

        /* Contenedores nativos y filtros */
        .st-key-msf_filters [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-msf_history [data-testid="stVerticalBlockBorderWrapper"] {{
            background: {WHITE} !important;
            border: 3px solid {INK} !important;
            border-radius: 10px !important;
            box-shadow: 7px 7px 0 {INK} !important;
            padding: 10px;
        }}

        .msf-note {{
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.78rem;
            color: {INK};
            opacity: 0.8;
            margin: 6px 0 4px 0;
            text-align: left;
        }}

        /* Tarjetas HTML Brutalistas */
        .mb-card-solid {{
            background: {WHITE};
            border: 3px solid {INK};
            box-shadow: 7px 7px 0 {INK};
            padding: 20px;
            margin-bottom: 20px;
            color: {INK};
            text-align: left;
        }}
        .mb-card-solid:hover {{
            transform: translate(-2px, -2px);
            box-shadow: 9px 9px 0 {INK};
            transition: all 0.15s ease;
        }}

        /* KPIs */
        .msf-kpi-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
        .msf-kpi {{ 
            position: relative; flex: 1 1 220px; 
            background: {WHITE};
            border: 3px solid {INK};
            box-shadow: 6px 6px 0 {INK};
            padding: 20px;
            text-align: left;
        }}
        .msf-kpi-label {{
            display: block;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 12px;
            color: {INK};
        }}
        .msf-kpi-value {{
            font-family: "Archivo Black", sans-serif;
            font-size: 2.6rem;
            line-height: 1;
            color: {INK};
        }}
        .kpi-acid .msf-kpi-value {{ color: {ACID}; -webkit-text-stroke: 1px {INK}; }}
        .kpi-blue .msf-kpi-value {{ color: {BLUE}; -webkit-text-stroke: 1px {INK}; }}

        /* Tooltips */
        .msf-kpi[data-tip]::after {{
            content: attr(data-tip);
            position: absolute;
            left: 0;
            top: calc(100% + 8px);
            z-index: 20;
            width: max-content;
            max-width: 280px;
            background: {INK};
            color: {WHITE};
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.75rem;
            padding: 10px;
            border: 2px solid {INK};
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transition: opacity 0.15s ease, visibility 0.15s ease;
        }}
        .msf-kpi[data-tip]:hover::after {{
            opacity: 1;
            visibility: visible;
            transition-delay: 1s;
        }}

        /* Tablas operativas */
        table.msf-table {{
            width: 100%;
            border-collapse: collapse;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.8rem;
            text-align: left;
        }}
        table.msf-table th {{
            background: {INK};
            color: {WHITE};
            text-transform: uppercase;
            padding: 10px;
            border: 2px solid {INK};
        }}
        table.msf-table td {{
            background: {WHITE};
            color: {INK};
            padding: 10px;
            border: 2px solid {INK};
            font-weight: 600;
        }}
        
        /* Badges & Chips */
        .msf-badge {{
            display: inline-block;
            font-family: "IBM Plex Mono", monospace;
            font-weight: 900;
            padding: 2px 8px;
            border: 2px solid {INK};
            font-size: 0.7rem;
            color: {INK};
        }}
        .bg-ok {{ background: {ACID}; }}
        .bg-warn {{ background: {ORANGE}; }}
        .bg-crit {{ background: {CORAL}; }}
        .bg-blue {{ background: {BLUE}; }}

        .msf-error-card {{
            background: {CORAL};
            border: 3px solid {INK};
            box-shadow: 7px 7px 0 {INK};
            padding: 20px;
            font-family: "IBM Plex Mono", monospace;
            font-weight: 700;
            color: {INK};
            margin-bottom: 16px;
            text-align: left;
        }}
        
        /* Títulos H3 */
        h3 {{
            font-family: "Archivo Black", sans-serif !important;
            text-transform: uppercase;
            color: {INK} !important;
            margin-top: 2rem !important;
            margin-bottom: 1rem !important;
            text-align: left !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _status(value: float, healthy: float, warning: float) -> tuple[str, str]:
    if value >= healthy: return "SANO", "bg-ok"
    if value >= warning: return "RIESGO", "bg-warn"
    return "CRÍTICO", "bg-crit"

def _kpi_card(label: str, value: str, tooltip: str, color_class: str) -> str:
    return (
        f'<div class="msf-kpi {color_class}" data-tip="{html.escape(tooltip)}">'
        f'<span class="msf-kpi-label">{html.escape(label)}</span>'
        f'<span class="msf-kpi-value">{html.escape(value)}</span>'
        f"</div>"
    )

# --- Gráficos Plotly Brutalistas ---
def _build_waterfall(current_data, overall_swa):
    """Calcula el peso de la caída de SWA por ciudad (proxy) para el bridge."""
    city_swa = {}
    for row in current_data:
        city = str(row.get("CITY") or "").strip()
        val = _number(row.get("SWA_CITY"))
        if city and val > 0 and city not in city_swa:
            city_swa[city] = val
            
    if not city_swa or overall_swa >= 100:
        return None
        
    sorted_cities = sorted(city_swa.items(), key=lambda x: x[1])
    total_drop = 100.0 - overall_swa
    
    gaps = {c: 100.0 - v for c, v in sorted_cities}
    sum_gaps = sum(gaps.values())
    impacts = {c: (g / sum_gaps) * total_drop for c, g in gaps.items()} if sum_gaps > 0 else {}
    
    top_4 = list(impacts.items())[:4]
    others_impact = sum(v for k, v in list(impacts.items())[4:])
    
    x, y, measure, text = ["SWA IDEAL"], [100.0], ["absolute"], ["100%"]
    
    for c, imp in top_4:
        x.append(c)
        y.append(-imp)
        measure.append("relative")
        text.append(f"-{imp:.1f}%")
        
    if others_impact > 0:
        x.append("OTROS")
        y.append(-others_impact)
        measure.append("relative")
        text.append(f"-{others_impact:.1f}%")
        
    x.append("SWA ACTUAL")
    y.append(overall_swa)
    measure.append("total")
    text.append(f"{overall_swa:.1f}%")
    
    fig = go.Figure(go.Waterfall(
        name="SWA Bridge", orientation="v", measure=measure, x=x, y=y,
        textposition="outside", text=text,
        connector={"line": {"color": INK, "width": 3}},
        decreasing={"marker": {"color": CORAL, "line": {"color": INK, "width": 3}}},
        increasing={"marker": {"color": ACID, "line": {"color": INK, "width": 3}}},
        totals={"marker": {"color": BLUE, "line": {"color": INK, "width": 3}}}
    ))
    
    fig.update_layout(
        font_family="IBM Plex Mono", font_color=INK,
        plot_bgcolor=WHITE, paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=20, r=20, t=20, b=20),
        yaxis=dict(range=[min(overall_swa - 5, 50), 105], showgrid=True, gridcolor='rgba(17,17,17,0.1)', zeroline=False),
        xaxis=dict(showgrid=False, linecolor=INK, linewidth=3),
        shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color=INK, width=3))]
    )
    return fig

def _build_trend(trend_window):
    # Usando POLARS en lugar de Pandas
    df = pl.DataFrame(trend_window)
    fig = go.Figure()
    
    # Extraemos a listas de Python para que Plotly no tenga conflictos de tipos
    fechas = df["FECHA"].to_list()
    avl_vals = df["AVL"].to_list()
    swa_vals = df["SWA"].to_list()
    
    fig.add_trace(go.Scatter(
        x=fechas, y=avl_vals, name="AVL", mode='lines+markers',
        line=dict(color=ACID, width=4), marker=dict(size=8, color=ACID, line=dict(width=2, color=INK))
    ))
    fig.add_trace(go.Scatter(
        x=fechas, y=swa_vals, name="SWA", mode='lines+markers',
        line=dict(color=BLUE, width=4), marker=dict(size=8, color=BLUE, line=dict(width=2, color=INK))
    ))
    
    fig.update_layout(
        font_family="IBM Plex Mono", font_color=INK,
        plot_bgcolor=WHITE, paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=True, gridcolor='rgba(17,17,17,0.1)', linecolor=INK, linewidth=3),
        yaxis=dict(showgrid=True, gridcolor='rgba(17,17,17,0.1)', linecolor=INK, linewidth=3),
        shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color=INK, width=3))]
    )
    return fig


# ---------------------------------------------------------------------------
# Render principal (Centro de Mando 360)
# ---------------------------------------------------------------------------

def render() -> None:
    render_system_stamp("MODULE 02 / INTELLIGENCE")
    _inject_style()

    st.markdown(
        """
        <section class="mb-hero" style="text-align: left;">
            <span class="msf-badge bg-ok" style="margin-bottom:10px;">MILITAIRES SANS FRONTIÈRES</span>
            <h1 style="font-family: 'Archivo Black', sans-serif; font-size: 3.5rem; color: #111111; line-height: 1; margin: 0 0 10px 0;">NETWORK<br>PERFORMANCE.</h1>
            <p style="font-family: 'IBM Plex Mono', monospace; font-size: 1rem; color: #111111; max-width: 600px;">Control táctico de disponibilidad (AVL), impacto de quiebres (SWA) y planes de acción para la red operativa.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.spinner("SINCRONIZANDO INTELIGENCIA DE RED…"):
        try:
            current, history = _load_metrics(_fetch_dashboard())
        except Exception as exc:
            st.markdown(f'<div class="msf-error-card">⚠ {html.escape(str(exc))}</div>', unsafe_allow_html=True)
            if st.button("REINTENTAR SINCRONIZACIÓN", key="msf_refresh_error"):
                _fetch_dashboard.clear(); _load_metrics.clear(); st.rerun()
            return

    if not current or not history:
        st.markdown('<div class="msf-error-card">⚠ DATA_DASHBOARD sin datos.</div>', unsafe_allow_html=True)
        return

    # --- FILTROS TÁCTICOS ---
    with st.container(border=True, key="msf_filters"):
        col1, col2, col3, col4 = st.columns([1.5, 1.5, 1.2, 1])
        cities = sorted({str(row["CITY"]).strip() for row in current if row.get("CITY")})
        selected_city = col1.selectbox("ZONA OPERATIVA", ["TODAS"] + cities)

        bucket_options = sorted({str(row["BUCKET_TYPE"]).strip() for row in history if row.get("BUCKET_TYPE")})
        selected_bucket = col2.selectbox("CATÁLOGO / BUCKET", bucket_options, index=bucket_options.index("GENERAL") if "GENERAL" in bucket_options else 0)
        window_label = col3.selectbox("VENTANA HISTÓRICA", list(HISTORY_WINDOWS.keys()), index=2)

        col4.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        if col4.button("ACTUALIZAR", key="msf_refresh_filters", use_container_width=True):
            _fetch_dashboard.clear(); _load_metrics.clear(); st.rerun()

    # Data Scoping
    scope = [row for row in current if selected_city == "TODAS" or str(row["CITY"]).strip() == selected_city]
    if not scope:
        st.warning("No hay datos para esta combinación.")
        return
        
    first = current[0]
    if selected_city == "TODAS":
        avl, swa = _number(first["AVL_COUNTRY"]), _number(first["SWA_COUNTRY"])
    else:
        city_row = next((row for row in scope if row.get("AVL_CITY") is not None), scope[0])
        avl, swa = _number(city_row["AVL_CITY"]), _number(city_row["SWA_CITY"])
    warehouses_medidos = len({row["WAREHOUSE_ID"] for row in scope})

    # --- SITUACIÓN ACTUAL ---
    st.markdown("### SITUACIÓN ACTUAL")
    st.markdown(
        f'<div class="msf-kpi-row">'
        f'{_kpi_card("AVL ACTUAL", f"{avl:.2f}%", "Available: % de SKUs del catálogo con inventario.", "kpi-acid")}'
        f'{_kpi_card("SWA ACTUAL", f"{swa:.2f}%", "Stockout-Weighted Availability: disponibilidad ponderada por relevancia.", "kpi-blue")}'
        f'{_kpi_card("NODOS ACTIVOS", f"{warehouses_medidos:,}", "Número de almacenes reportando inventario.", "")}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # --- ANÁLISIS 360 (CHARTS) ---
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.markdown("### ANÁLISIS DE BRECHA (SWA)")
        if selected_city == "TODAS":
            fig_waterfall = _build_waterfall(current, swa)
            if fig_waterfall:
                st.plotly_chart(fig_waterfall, use_container_width=True, config={'displayModeBar': False})
            else:
                st.markdown('<div class="mb-card-solid">Red SWA al 100% o sin datos suficientes.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="mb-card-solid"><p class="msf-note">El análisis de cascada (Bridge) opera a nivel país. Selecciona "TODAS" en Zona Operativa.</p></div>', unsafe_allow_html=True)

    with col_chart2:
        st.markdown("### TENDENCIA HISTÓRICA")
        rows = [r for r in history if str(r["BUCKET_TYPE"]).strip() == selected_bucket and (selected_city == "TODAS" or str(r["CITY"]).strip() == selected_city)]
        by_day = defaultdict(list)
        for r in rows: by_day[r["MAIN_DATE"]].append(r)
        
        trend = []
        for day, items in sorted(by_day.items(), key=lambda item: item[0]):
            trend.append({
                "FECHA": day,
                "AVL": round(sum(_number(x["AVL"]) for x in items) / len(items), 2),
                "SWA": round(sum(_number(x["SWA"]) for x in items) / len(items), 2)
            })
        trend_window = trend[-HISTORY_WINDOWS[window_label]:]
        
        if trend_window:
            st.plotly_chart(_build_trend(trend_window), use_container_width=True, config={'displayModeBar': False})
        else:
            st.markdown('<div class="mb-card-solid">Sin datos históricos.</div>', unsafe_allow_html=True)

    # --- LECTURA OPERATIVA ---
    latest_day = max(by_day) if by_day else None
    detail = []
    if latest_day is not None:
        for row in by_day[latest_day]:
            detail.append({
                "CIUDAD": str(row["CITY"] or "—"),
                "WAREHOUSE": str(row["WAREHOUSE_NAME"] or "—"),
                "AVL": _number(row["AVL"]),
                "SWA": _number(row["SWA"]),
                "SKUS": int(_number(row.get("SKUS_IN_BL")))
            })
        detail.sort(key=lambda r: (r["SWA"], r["AVL"]))

    st.markdown("### PUNTOS CRÍTICOS (TOP 10)")
    if detail:
        rows_html = []
        for r in detail[:10]:
            avl_label, avl_class = _status(r["AVL"], AVL_HEALTHY, AVL_WARNING)
            swa_label, swa_class = _status(r["SWA"], SWA_HEALTHY, SWA_WARNING)
            rows_html.append(
                f"<tr>"
                f"<td>{html.escape(r['CIUDAD'])}</td>"
                f"<td>{html.escape(r['WAREHOUSE'])}</td>"
                f"<td>{r['AVL']:.1f}% <span class='msf-badge {avl_class}'>{avl_label}</span></td>"
                f"<td>{r['SWA']:.1f}% <span class='msf-badge {swa_class}'>{swa_label}</span></td>"
                f"<td>{r['SKUS']:,}</td>"
                f"</tr>"
            )
        table_html = (
            f'<div class="mb-card-solid" style="padding:0;">'
            f"<table class='msf-table'>"
            f"<thead><tr><th>Ciudad</th><th>Warehouse</th><th>AVL</th><th>SWA</th><th>SKUs Backlog</th></tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
            f"</div>"
        )
        st.markdown(table_html, unsafe_allow_html=True)

    # --- INSIGHTS Y PLANES DE ACCIÓN AUTOMATIZADOS ---
    st.markdown("### INTELIGENCIA Y PLANES DE ACCIÓN")
    plans = []
    
    # 1. Alerta de Caída General
    if len(trend) >= 2:
        delta_swa = trend[-1]["SWA"] - trend[0]["SWA"]
        if delta_swa < -1.5:
            plans.append(f"🔴 <b>ALERTA DE TENDENCIA:</b> El SWA ha caído <span class='msf-badge bg-crit'>{abs(delta_swa):.1f} pts</span> en la ventana actual. <b>ACCIÓN:</b> Revisar inbounds pendientes y mermas en centros de distribución clave.")
        elif delta_swa > 1.5:
            plans.append(f"🟢 <b>RECUPERACIÓN:</b> El SWA subió <span class='msf-badge bg-ok'>{delta_swa:.1f} pts</span>. Consolidar el fill-rate actual.")

    # 2. Análisis del peor Warehouse
    if detail:
        worst = detail[0]
        if worst["SWA"] < SWA_WARNING:
            plans.append(f"⚡ <b>FOCO ROJO:</b> {worst['WAREHOUSE']} ({worst['CIUDAD']}) tiene un SWA crítico de <span class='msf-badge bg-crit'>{worst['SWA']:.1f}%</span>. <b>ACCIÓN:</b> Ejecutar cross-docking urgente para el top 20% de SKUs generadores de venta.")

    # 3. Desalineación Long-tail vs Top-sellers (AVL alto, SWA bajo)
    for r in detail[:5]:
        if r["AVL"] >= AVL_HEALTHY and r["SWA"] < SWA_WARNING:
            plans.append(f"🔍 <b>DESALINEACIÓN DE INVENTARIO:</b> En {r['WAREHOUSE']}, el AVL es sano ({r['AVL']:.1f}%) pero el SWA es pobre ({r['SWA']:.1f}%). <b>ACCIÓN:</b> Depurar el catálogo local; hay exceso de inventario inmovilizado de baja rotación, mientras que los top sellers están en quiebre (stockout).")
            break

    if not plans:
        plans.append("🛡️ <b>RED ESTABLE:</b> Los KPIs se mantienen en rangos operativos. Mantener monitoreo de desviaciones.")

    cards = "".join(f'<div class="mb-card-solid" style="margin-bottom:10px; font-size: 0.9rem;">{p}</div>' for p in plans)
    st.markdown(cards, unsafe_allow_html=True)
