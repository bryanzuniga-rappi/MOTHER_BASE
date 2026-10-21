"""Militaires Sans Frontières — cascarón de planeación Excel."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

import openpyxl
import streamlit as st

from mother_base_theme import render_system_stamp


def _inject_style() -> None:
    st.markdown("""
    <style>
    .msf-shell { border: 3px solid #111; background: #fffdf5; padding: 28px;
      box-shadow: 8px 8px 0 #111; margin-bottom: 28px; }
    .msf-label { display:inline-block; background:#5f7cff; color:#111;
      border:3px solid #111; padding:8px 12px; font-weight:800;
      letter-spacing:.08em; }
    .msf-note { border:2px solid #111; background:#e8edff; padding:14px;
      margin-top:16px; }
    </style>
    """, unsafe_allow_html=True)


def _excel_inventory(uploaded_file) -> list[dict[str, object]]:
    """Lee solo metadatos en modo read-only para mantener bajo el uso de RAM."""
    raw = uploaded_file.getvalue()
    workbook = openpyxl.load_workbook(
        io.BytesIO(raw), read_only=True, data_only=True, keep_links=False
    )
    rows: list[dict[str, object]] = []
    try:
        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            rows.append({
                "ARCHIVO": Path(uploaded_file.name).name,
                "HOJA": sheet_name,
                "FILAS_ESTIMADAS": sheet.max_row or 0,
                "COLUMNAS_ESTIMADAS": sheet.max_column or 0,
            })
    finally:
        workbook.close()
        del raw
    return rows


def _build_csv(uploaded_files) -> bytes:
    output = io.StringIO(newline="")
    fieldnames = ["ARCHIVO", "HOJA", "FILAS_ESTIMADAS", "COLUMNAS_ESTIMADAS"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for uploaded_file in uploaded_files:
        for row in _excel_inventory(uploaded_file):
            writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def render() -> None:
    render_system_stamp("MODULE 02 / MILITAIRES SANS FRONTIÈRES")
    _inject_style()
    st.markdown("""
    <section class="mb-hero">
        <span class="mb-kicker">MODULE / 02 · INTELLIGENCE</span>
        <h1>MILITAIRES SANS<br>FRONTIÈRES.</h1>
        <p>Base de trabajo para cargar Exceles, ejecutar una planeación y producir un CSV.</p>
    </section>
    """, unsafe_allow_html=True)

    st.markdown('<div class="msf-shell">', unsafe_allow_html=True)
    st.markdown('<span class="msf-label">CARGA DE ENTRADAS</span>', unsafe_allow_html=True)
    st.write("")
    uploaded_files = st.file_uploader(
        "Exceles de entrada", type=["xlsx", "xlsm"], accept_multiple_files=True,
        key="msf_excel_inputs",
        help="Puedes cargar uno o varios archivos .xlsx o .xlsm. Las reglas de transformación se agregarán después.",
    )
    if uploaded_files:
        st.caption(f"{len(uploaded_files)} archivo(s) listo(s) para procesar.")
        st.dataframe(
            [{"ARCHIVO": file.name, "TAMAÑO_MB": round(file.size / 1024 / 1024, 2)} for file in uploaded_files],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("Carga al menos un Excel para habilitar la planeación.")

    run = st.button(
        "EJECUTAR PLANEACIÓN →", type="primary", use_container_width=True,
        disabled=not uploaded_files, key="msf_run_excel_shell",
    )
    st.markdown(
        '<div class="msf-note">Esta primera versión solo inspecciona las hojas y genera un CSV de control. Las reglas de negocio se incorporarán sobre este flujo.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if run:
        with st.spinner("Leyendo Exceles y preparando la salida…"):
            try:
                csv_bytes = _build_csv(uploaded_files)
            except Exception as exc:
                st.error(f"No se pudo leer uno de los Exceles: {exc}")
                return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.success("Cascarón ejecutado correctamente. CSV generado.")
        st.download_button(
            "DESCARGAR CSV →", data=csv_bytes,
            file_name=f"MSF_PLANEACION_{timestamp}.csv", mime="text/csv",
            use_container_width=True, key="msf_download_shell_csv",
        )

    if st.button("← Volver a Mother Base", key="msf_back_home"):
        st.session_state["mb_module"] = "MOTHER BASE"
        st.rerun()
