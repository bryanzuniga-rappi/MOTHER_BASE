"""Dashboard mínimo de desempeño AVL/SWA para Militaires Sans Frontières."""

from __future__ import annotations

from collections import defaultdict
import io
import re
import urllib.error
import urllib.request
import zipfile

import openpyxl
import streamlit as st

from mother_base_theme import render_system_stamp


DATA_DASHBOARD_SPREADSHEET_ID = "174wMJVmpXdeWEOmn4pamlsDaNcIF0ltE1sJjbUpMKsQ"


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
        current = list(_records(wb, "CURRENT_DATE", {"CITY", "WAREHOUSE_ID", "AVL_COUNTRY", "SWA_COUNTRY", "AVL_CITY", "SWA_CITY", "AVL_WH", "SWA_WH"}))
        history = list(_records(wb, "28D", {"MAIN_DATE", "CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "BUCKET_TYPE", "AVL", "SWA"}))
    finally:
        wb.close()
    return current, history


def render() -> None:
    render_system_stamp("MODULE 02 / INTELLIGENCE")
    st.markdown(
        """
        <section class="mb-hero">
            <span class="mb-kicker">MILITAIRES SANS FRONTIÈRES</span>
            <h1>NETWORK<br>PERFORMANCE.</h1>
            <p>Control de AVL y SWA actual e histórico de la red.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    try:
        current, history = _load_metrics(_fetch_dashboard())
    except Exception as exc:
        st.error(str(exc))
        if st.button("ACTUALIZAR DATA_DASHBOARD"):
            _fetch_dashboard.clear()
            _load_metrics.clear()
            st.rerun()
        return

    if not current or not history:
        st.warning("DATA_DASHBOARD no contiene filas suficientes para construir el dashboard.")
        return

    first = current[0]
    cities = sorted({str(row["CITY"]).strip() for row in current if row.get("CITY")})
    selected_city = st.selectbox("Ciudad", ["TODAS"] + cities)
    scope = [row for row in current if selected_city == "TODAS" or str(row["CITY"]).strip() == selected_city]
    if selected_city == "TODAS":
        avl = _number(first["AVL_COUNTRY"])
        swa = _number(first["SWA_COUNTRY"])
    else:
        city_row = next((row for row in scope if row.get("AVL_CITY") is not None), scope[0])
        avl, swa = _number(city_row["AVL_CITY"]), _number(city_row["SWA_CITY"])

    bucket_options = sorted({str(row["BUCKET_TYPE"]).strip() for row in history if row.get("BUCKET_TYPE")})
    selected_bucket = st.selectbox("Catálogo", bucket_options, index=bucket_options.index("GENERAL") if "GENERAL" in bucket_options else 0)
    st.markdown("### SITUACIÓN ACTUAL")
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("AVL ACTUAL", f"{avl:.2f}%")
    kpi2.metric("SWA ACTUAL", f"{swa:.2f}%")
    kpi3.metric("WAREHOUSES MEDIDOS", f"{len({row['WAREHOUSE_ID'] for row in scope}):,}")

    rows = [row for row in history if str(row["BUCKET_TYPE"]).strip() == selected_bucket and (selected_city == "TODAS" or str(row["CITY"]).strip() == selected_city)]
    by_day: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[row["MAIN_DATE"]].append(row)
    trend = []
    for day, items in sorted(by_day.items(), key=lambda item: item[0]):
        trend.append({"FECHA": day, "AVL": round(sum(_number(x["AVL"]) for x in items) / len(items), 2), "SWA": round(sum(_number(x["SWA"]) for x in items) / len(items), 2)})

    st.markdown("### HISTÓRICO")
    if trend:
        st.line_chart(trend, x="FECHA", y=["AVL", "SWA"], color=["#D4FF2A", "#5B7CFA"])
        st.dataframe(trend[-28:], use_container_width=True, hide_index=True)

    latest_day = max(by_day) if by_day else None
    if latest_day is not None:
        store_rows = [row for row in by_day[latest_day]]
        detail = sorted(({"CIUDAD": row["CITY"], "WAREHOUSE": row["WAREHOUSE_NAME"], "AVL": _number(row["AVL"]), "SWA": _number(row["SWA"]), "SKUS": int(_number(row.get("SKUS_IN_BL")))} for row in store_rows), key=lambda row: (row["SWA"], row["AVL"]))
        st.markdown("### ÚLTIMO CORTE · TIENDAS CON MAYOR OPORTUNIDAD")
        st.dataframe(detail[:30], use_container_width=True, hide_index=True)

    if st.button("ACTUALIZAR DATA_DASHBOARD"):
        _fetch_dashboard.clear()
        _load_metrics.clear()
        st.rerun()
