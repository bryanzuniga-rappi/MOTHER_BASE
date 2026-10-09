"""Mother Base — punto de entrada de Streamlit.

Flujo: login (auth.py) → inicio → módulo elegido (Les Enfants Terribles o
Militaires Sans Frontières). Avisa si la instalación está desordenada
(modules/install_check.py).
"""

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


def render_required_google_oauth() -> bool:
    """Gate obligatorio visible antes del selector de perfil."""
    from modules.militaires_sans_frontieres import (
        build_oauth_authorization_url,
        configured_oauth_refresh_token,
        exchange_oauth_code_for_tokens,
        oauth_is_configured,
    )

    st.markdown('<span class="section-label">AUTORIZACIÓN OBLIGATORIA</span>', unsafe_allow_html=True)
    st.subheader("Conecta Google antes de entrar a MOTHER BASE")
    st.caption("Este permiso habilita Drive y Gmail para subir resultados y enviar únicamente el enlace por correo.")
    refresh_token = configured_oauth_refresh_token()
    if refresh_token:
        st.success("OAuth configurado: Drive y Gmail autorizados.")
        return True
    if not oauth_is_configured():
        st.error(
            "Configura DATA_DASHBOARD_OAUTH_CLIENT_ID, "
            "DATA_DASHBOARD_OAUTH_CLIENT_SECRET y "
            "DATA_DASHBOARD_OAUTH_REDIRECT_URI en Secrets."
        )
        return False
    oauth_code = st.query_params.get("code")
    if oauth_code:
        if st.button("Completar conexión OAuth", key="gateway_oauth_exchange"):
            try:
                tokens = exchange_oauth_code_for_tokens(oauth_code)
                token = tokens.get("refresh_token")
                if token:
                    st.success("Copia este refresh token en Secrets como DATA_DASHBOARD_OAUTH_REFRESH_TOKEN y recarga la app.")
                    st.code(token, language=None)
                else:
                    st.error("Google no devolvió refresh token; revoca el acceso anterior y vuelve a autorizar.")
            except RuntimeError as error:
                st.error(str(error))
    else:
        st.link_button("Autorizar Drive y Gmail", build_oauth_authorization_url())
    return False


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
            "Desbloquear acceso →",
            use_container_width=True,
        )
    if submitted:
        if login_big_boss(password):
            st.rerun()
        st.error("Código de acceso incorrecto.")


def render_gateway() -> None:
    if not render_required_google_oauth():
        return
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
                "Acceso operativo sin contraseña. Solidus y Liquid Engine "
                "quedan bloqueados, y no puede bloquear ciudades protegidas."
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


def render_installation_warnings() -> None:
    """Avisa (sin detener la app) si hay archivos desordenados o viejos."""
    try:
        from pathlib import Path

        from modules.install_check import installation_problems

        problems = installation_problems(Path(__file__).resolve().parent)
    except Exception:  # el chequeo nunca debe tumbar la app
        return
    if problems:
        st.error(
            "⚠️ Instalación incompleta o desordenada — la app puede estar "
            "ejecutando código viejo:\n\n"
            + "\n".join(f"- {problem}" for problem in problems)
        )


def main() -> None:
    inject_mother_base_theme()
    initialize_auth_state()
    if not st.session_state["mb_authenticated"]:
        render_gateway()
        return
    render_installation_warnings()

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
