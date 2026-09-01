from __future__ import annotations

import streamlit as st

from auth import (
    initialize_auth_state,
    login_big_boss,
    login_raiden,
)
from mother_base_theme import (
    inject_mother_base_theme,
    render_action_card,
    render_system_stamp,
)


st.set_page_config(
    page_title="Mother Base | Supply Command",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)


MODULE_HOME = "MOTHER BASE"
MODULE_PLANNING = "LES ENFANTS TERRIBLES"
MODULE_REPORTS = "MILITAIRES SANS FRONTIÈRES"


@st.dialog("BIG BOSS · ACCESS CONTROL", width="small")
def render_big_boss_authentication() -> None:
    st.caption("Ingresa el código de acceso para desbloquear Mother Base.")
    with st.form("big_boss_access", clear_on_submit=False):
        password = st.text_input(
            "Código de acceso",
            type="password",
            placeholder="••••••••",
        )
        submitted = st.form_submit_button(
            "DESBLOQUEAR ACCESO →",
            use_container_width=True,
        )
    if submitted:
        if login_big_boss(password):
            st.rerun()
        st.error("Código de acceso incorrecto.")


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
        if render_action_card(
            key="profile_big_boss",
            eyebrow="PROFILE / 01 · FULL ACCESS",
            title="BIG BOSS",
            description=(
                "Acceso completo al centro de comando. Haz clic en esta tarjeta "
                "para autenticarte."
            ),
            active=True,
            tone="acid",
        ):
            render_big_boss_authentication()

    with raiden_column:
        if render_action_card(
            key="profile_raiden",
            eyebrow="PROFILE / 02 · OPERATIVE ACCESS",
            title="RAIDEN",
            description=(
                "Acceso operativo sin contraseña. Por ahora tiene las mismas "
                "funciones."
            ),
            active=False,
            tone="white",
        ):
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
        if render_action_card(
            key="module_planning",
            eyebrow="MODULE / 01 · OPERATIONAL",
            title="LES ENFANTS TERRIBLES",
            description=(
                "Naked, Solidus y Liquid Engines. Planeación táctica de "
                "transferencias."
            ),
            active=True,
            tone="acid",
        ):
            st.session_state["mb_module"] = MODULE_PLANNING
            st.rerun()
    with reporting_column:
        if render_action_card(
            key="module_reporting",
            eyebrow="MODULE / 02 · INTELLIGENCE",
            title="MILITAIRES SANS FRONTIÈRES",
            description="Reportes ejecutivos, históricos y seguimiento de misiones.",
            active=True,
            tone="blue",
            status="WORK IN PROGRESS",
        ):
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
