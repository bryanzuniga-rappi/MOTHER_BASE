from __future__ import annotations

import streamlit as st

from mother_base_theme import render_system_stamp


def render() -> None:
    render_system_stamp("MODULE 02 / INTELLIGENCE")
    st.markdown(
        """
        <section class="mb-hero">
            <span class="mb-kicker">MILITAIRES SANS FRONTIÈRES</span>
            <h1>REPORTING<br>COMMAND.</h1>
            <p>
                Repositorio ejecutivo de misiones, cumplimiento, inventario y
                desempeño de la red. El módulo está reservado para la siguiente fase.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### WORK IN PROGRESS")
    st.info(
        "La arquitectura ya reconoce este módulo, pero todavía no almacena un "
        "histórico persistente de planeaciones."
    )

