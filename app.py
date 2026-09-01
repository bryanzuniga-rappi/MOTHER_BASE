from __future__ import annotations

import streamlit as st

from auth import (
    initialize_auth_state,
    login_big_boss,
    login_raiden,
)
from mother_base_theme import inject_mother_base_theme, render_system_stamp


st.set_page_config(
    page_title="Mother Base | Supply Command",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)


MODULE_HOME = "MOTHER BASE"
MODULE_PLANNING = "LES ENFANTS TERRIBLES"
MODULE_REPORTS = "MILITAIRES SANS FRONTIÈRES"


def render_gateway() -> None:
    render_system_stamp("TACTICAL SUPPLY SYSTEM / ACCESS GATE")
    st.markdown(
        """
        <section class="mb-hero">
            <span class="mb-kicker">DIAMOND DOGS · SUPPLY COMMAND</span>
            <h1>WELCOME TO<br>MOTHER BASE.</h1>
            <p>Selecciona tu perfil para ingresar al centro de comando de Supply.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    big_boss_column, raiden_column = st.columns(2, gap="large")
    with big_boss_column:
        st.markdown(
            """
            <div class="mb-card active">
                <div class="mb-card-code">PROFILE / 01</div>
                <h3>BIG BOSS</h3>
                <p>Acceso completo al centro de comando. Requiere autenticación.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("big_boss_access", clear_on_submit=False):
            password = st.text_input(
                "Código de acceso",
                type="password",
                placeholder="••••••••",
            )
            submitted = st.form_submit_button(
                "INGRESAR COMO BIG BOSS →",
                use_container_width=True,
            )
        if submitted:
            if login_big_boss(password):
                st.rerun()
            st.error("Código de acceso incorrecto.")

    with raiden_column:
        st.markdown(
            """
            <div class="mb-card">
                <div class="mb-card-code">PROFILE / 02</div>
                <h3>RAIDEN</h3>
                <p>Acceso operativo sin contraseña. Por ahora tiene las mismas funciones.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("INGRESAR COMO RAIDEN →", use_container_width=True):
            login_raiden()
            st.rerun()


def render_home() -> None:
    profile = st.session_state.get("mb_profile", "OPERATIVE")
    render_system_stamp(f"ONLINE / {profile}")
    st.markdown(
        """
        <section class="mb-hero">
            <span class="mb-kicker">SUPPLY COMMAND CENTER</span>
            <h1>WELCOME TO<br>MOTHER BASE.</h1>
            <p>
                Planeación, ejecución e inteligencia de abasto reunidas en una sola base.
                Selecciona un módulo para iniciar la misión.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    planning_column, reporting_column = st.columns(2, gap="large")
    with planning_column:
        st.markdown(
            """
            <div class="mb-card active">
                <div class="mb-card-code">MODULE / 01 · OPERATIONAL</div>
                <h3>LES ENFANTS TERRIBLES</h3>
                <p>Naked, Solidus y Liquid Engines. Planeación táctica de transferencias.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("ABRIR PLANEACIÓN →", use_container_width=True):
            st.session_state["mb_module"] = MODULE_PLANNING
            st.rerun()
    with reporting_column:
        st.markdown(
            """
            <div class="mb-card wip">
                <div class="mb-card-code">MODULE / 02 · INTELLIGENCE</div>
                <h3>MILITAIRES SANS FRONTIÈRES</h3>
                <p>Reportes ejecutivos, históricos y seguimiento de misiones.</p>
                <div class="mb-wip">WORK IN PROGRESS</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("VER MÓDULO →", use_container_width=True):
            st.session_state["mb_module"] = MODULE_REPORTS
            st.rerun()


def main() -> None:
    inject_mother_base_theme()
    initialize_auth_state()
    if not st.session_state["mb_authenticated"]:
        render_gateway()
        return

    selected_module = st.session_state.get("mb_module", MODULE_HOME)
    if selected_module == MODULE_PLANNING:
        from modules.les_enfants_terribles import render

        render()
    elif selected_module == MODULE_REPORTS:
        from modules.militaires_sans_frontieres import render

        render()
    else:
        render_home()


if __name__ == "__main__":
    main()
