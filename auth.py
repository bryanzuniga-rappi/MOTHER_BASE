from __future__ import annotations

import hmac

import streamlit as st


PROFILE_BIG_BOSS = "BIG BOSS"
PROFILE_RAIDEN = "RAIDEN"


def initialize_auth_state() -> None:
    st.session_state.setdefault("mb_authenticated", False)
    st.session_state.setdefault("mb_profile", None)
    st.session_state.setdefault("mb_module", "MOTHER BASE")


def configured_big_boss_password() -> str:
    """Usa Streamlit Secrets cuando existe y conserva Admin como fallback."""
    try:
        return str(st.secrets.get("BIG_BOSS_PASSWORD", "Admin"))
    except Exception:
        return "Admin"


def login_big_boss(password: str) -> bool:
    if hmac.compare_digest(password, configured_big_boss_password()):
        st.session_state["mb_authenticated"] = True
        st.session_state["mb_profile"] = PROFILE_BIG_BOSS
        st.session_state["mb_module"] = "MOTHER BASE"
        return True
    return False


def login_raiden() -> None:
    st.session_state["mb_authenticated"] = True
    st.session_state["mb_profile"] = PROFILE_RAIDEN
    st.session_state["mb_module"] = "MOTHER BASE"


def logout() -> None:
    for key in (
        "mb_authenticated",
        "mb_profile",
        "mb_module",
        "last_run",
        "last_workspace",
    ):
        st.session_state.pop(key, None)
    initialize_auth_state()

