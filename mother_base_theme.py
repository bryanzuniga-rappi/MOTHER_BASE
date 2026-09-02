from __future__ import annotations

# Mother Base theme build 2026-09-02.15 — Engine alignment emitted with each card.

import streamlit as st


def inject_mother_base_theme() -> None:
    """Extiende sin sustituir la paleta brutalista del Transfer Planner."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');

        :root {
            --ink: #111111;
            --paper: #f2efe6;
            --acid: #d9ff3f;
            --coral: #ff5a47;
            --blue: #5e7cff;
            --orange: #ffb000;
            --white: #fffdf7;
            --muted: #6f6b63;
        }

        html,
        body,
        #root {
            background-color: #f2efe6 !important;
            color: #111111 !important;
            color-scheme: light !important;
        }

        html, body, [class*="css"] {
            font-family: "IBM Plex Mono", monospace;
            color: #111111 !important;
        }

        .stApp,
        [data-testid="stApp"],
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        section.main,
        .main {
            color: #111111 !important;
            background-color: #f2efe6 !important;
        }

        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            background-image:
                linear-gradient(rgba(17,17,17,.055) 1px, transparent 1px),
                linear-gradient(90deg, rgba(17,17,17,.055) 1px, transparent 1px) !important;
            background-size: 28px 28px !important;
        }

        [data-testid="stMainBlockContainer"],
        .block-container {
            background-color: transparent !important;
        }

        [data-testid="stHeader"] { background: transparent !important; }
        [data-testid="stSidebar"] { display: none; }
        [data-testid="stToolbar"], #MainMenu, footer { visibility: hidden; }
        .block-container { max-width: 1440px; padding: 2rem 3rem 4rem; }

        h1, h2, h3, h4, p, label,
        [data-testid="stMarkdownContainer"],
        [data-testid="stWidgetLabel"] {
            color: var(--ink);
        }

        h1, h2, h3 {
            font-family: "Archivo Black", sans-serif !important;
            letter-spacing: -.035em;
        }

        .mb-scanline {
            height: 6px;
            margin: 8px 0 22px;
            background: repeating-linear-gradient(
                90deg,
                var(--ink) 0 18px,
                transparent 18px 25px
            );
        }

        .mb-hero {
            position: relative;
            overflow: hidden;
            padding: 34px 38px;
            margin: 6px 10px 32px 0;
            border: 4px solid var(--ink);
            box-shadow: 10px 10px 0 var(--ink);
            background: var(--coral);
        }

        .mb-hero::after {
            content: "MOTHER BASE";
            position: absolute;
            right: -38px;
            top: 38px;
            transform: rotate(8deg);
            border: 3px solid var(--ink);
            background: var(--acid);
            color: var(--ink);
            padding: 8px 48px;
            font-weight: 900;
            letter-spacing: .08em;
        }

        .mb-kicker {
            display: inline-block;
            border: 3px solid var(--ink);
            padding: 5px 9px;
            color: var(--ink);
            background: var(--white);
            font-weight: 900;
            letter-spacing: .08em;
        }

        .mb-hero h1 {
            position: relative;
            z-index: 1;
            max-width: 1000px;
            margin: 20px 0 8px;
            color: var(--ink) !important;
            font-size: clamp(44px, 8vw, 92px);
            line-height: .88;
        }

        .mb-hero p {
            position: relative;
            z-index: 1;
            max-width: 760px;
            color: var(--ink) !important;
            font-size: 15px;
            font-weight: 700;
        }

        .mb-card {
            min-height: 190px;
            padding: 23px;
            margin: 0 7px 18px 0;
            border: 3px solid var(--ink);
            box-shadow: 7px 7px 0 var(--ink);
            background: var(--white);
            color: var(--ink);
        }

        .mb-card.active { background: var(--acid); }
        .mb-card.wip { background: var(--blue); color: var(--white); }
        .mb-card h3 { margin: 9px 0; color: inherit !important; }
        .mb-card p { color: inherit !important; font-weight: 600; }
        .mb-card-code { color: inherit; font-size: 12px; font-weight: 900; }
        .mb-wip {
            display: inline-block;
            padding: 4px 7px;
            border: 2px solid var(--ink);
            color: var(--ink);
            background: var(--coral);
            font-weight: 900;
        }

        .engine-panel {
            border: 3px solid var(--ink);
            box-shadow: 6px 6px 0 var(--ink);
            padding: 18px 20px;
            margin: 8px 7px 22px 0;
            background: var(--white);
        }
        .engine-panel.naked { background: var(--acid); }
        .engine-panel.solidus { background: var(--blue); color: var(--white); }
        .engine-panel.liquid { background: var(--coral); }
        .engine-panel.shalashaska { background: var(--orange); }
        .engine-panel h4, .engine-panel p { color: inherit !important; }

        div.stButton > button,
        div.stDownloadButton > button,
        div[data-testid="stFormSubmitButton"] > button {
            min-height: 50px;
            border: 3px solid var(--ink) !important;
            border-radius: 0 !important;
            box-shadow: 5px 5px 0 var(--ink) !important;
            color: var(--ink) !important;
            background: var(--acid) !important;
            font-family: "IBM Plex Mono", monospace !important;
            font-weight: 900 !important;
            text-transform: uppercase;
        }

        div.stButton > button:hover,
        div.stDownloadButton > button:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            color: var(--ink) !important;
            background: var(--acid) !important;
            transform: translate(3px, 3px);
            box-shadow: 2px 2px 0 var(--ink) !important;
        }

        [data-testid="stMetric"],
        [data-testid="stFileUploader"],
        [data-testid="stExpander"],
        [data-testid="stVerticalBlockBorderWrapper"] {
            color: var(--ink) !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stForm"],
        [data-testid="stExpander"] {
            background-color: var(--white) !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: #c9c5bb !important;
            border-radius: 10px !important;
        }

        .st-key-mission_control_shared,
        .st-key-engine_naked_module,
        .st-key-engine_solidus_module,
        .st-key-engine_shalashaska_module,
        .st-key-engine_liquid_module,
        .st-key-mission_control_shared > div,
        .st-key-engine_naked_module > div,
        .st-key-engine_solidus_module > div,
        .st-key-engine_shalashaska_module > div,
        .st-key-engine_liquid_module > div,
        .st-key-mission_control_shared [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-engine_naked_module [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-engine_solidus_module [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-engine_shalashaska_module [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-engine_liquid_module [data-testid="stVerticalBlockBorderWrapper"] {
            background: #fffdf7 !important;
            background-color: #fffdf7 !important;
        }

        .mission-control-marker {
            display: none !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"]:has(.mission-control-marker),
        .st-key-mission_control_shared [data-testid="stVerticalBlockBorderWrapper"] {
            background: #fffdf7 !important;
            background-color: #fffdf7 !important;
            border: 3px solid #111111 !important;
            border-radius: 10px !important;
            box-shadow: 7px 7px 0 #111111 !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"]:has(.mission-control-marker)
        [data-testid="stVerticalBlock"],
        .st-key-mission_control_shared [data-testid="stVerticalBlock"] {
            background: #fffdf7 !important;
            background-color: #fffdf7 !important;
        }

        [data-testid="stFileUploaderDropzone"],
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        [data-testid="stNumberInput"] input,
        textarea {
            color: var(--ink) !important;
            background: var(--white) !important;
            border-radius: 0 !important;
        }

        [data-testid="stAlert"] {
            color: var(--ink) !important;
            border: 3px solid var(--ink);
            border-radius: 0;
        }

        @media (max-width: 800px) {
            .block-container { padding: 1rem 1rem 3rem; }
            .mb-hero { padding: 24px 20px; }
            .mb-hero::after { display: none; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_system_stamp(label: str) -> None:
    st.markdown(
        f'<span class="mb-kicker">{label}</span><div class="mb-scanline"></div>',
        unsafe_allow_html=True,
    )


def render_action_card(
    *,
    key: str,
    eyebrow: str,
    title: str,
    description: str,
    active: bool = False,
    tone: str = "acid",
    status: str | None = None,
    min_height: int = 178,
    help_text: str | None = None,
) -> bool:
    """Renderiza una tarjeta completa como botón nativo de Streamlit."""
    tone_colors = {
        "acid": ("#d9ff3f", "#111111"),
        "coral": ("#ff5a47", "#111111"),
        "blue": ("#5e7cff", "#fffdf7"),
        "orange": ("#ffb000", "#111111"),
        "white": ("#fffdf7", "#111111"),
    }
    active_background, active_foreground = tone_colors.get(
        tone, tone_colors["acid"]
    )
    background = active_background if active else "#fffdf7"
    foreground = active_foreground if active else "#111111"
    badge_background = "#fffdf7" if active else "#111111"
    badge_foreground = "#111111" if active else "#fffdf7"
    css_key = "".join(
        character if character.isalnum() or character in {"_", "-"} else "-"
        for character in key
    )
    engine_alignment_css = ""
    if key.startswith("engine_") and key.endswith("_card"):
        engine_alignment_css = f"""
        .st-key-{css_key} button {{
            justify-content: flex-start !important;
            text-align: left !important;
        }}

        .st-key-{css_key} button > *,
        .st-key-{css_key} button > * > *,
        .st-key-{css_key} button [data-testid="stMarkdownContainer"] {{
            width: 100% !important;
            max-width: none !important;
            min-width: 0 !important;
            flex-grow: 1 !important;
            align-self: stretch !important;
            margin-inline: 0 !important;
            text-align: left !important;
        }}

        .st-key-{css_key} button [data-testid="stMarkdownContainer"] p {{
            width: 100% !important;
            max-width: none !important;
            margin-inline: 0 !important;
            text-align: left !important;
        }}
        """
    st.markdown(
        f"""
        <style>
        .st-key-{css_key} div.stButton > button,
        .st-key-{css_key} [data-testid="stButton"] > button,
        .st-key-{css_key} [data-testid="stButton"] button,
        .st-key-{css_key} button {{
            display: flex !important;
            width: 100% !important;
            min-height: {int(min_height)}px !important;
            align-items: flex-start !important;
            justify-content: flex-start !important;
            padding: 20px 22px !important;
            border: 3px solid #111111 !important;
            border-radius: 10px !important;
            box-shadow: 6px 6px 0 #111111 !important;
            color: {foreground} !important;
            background: {background} !important;
            background-color: {background} !important;
            text-align: left !important;
            text-transform: none !important;
        }}

        .st-key-{css_key} div.stButton > button:hover,
        .st-key-{css_key} div.stButton > button:focus,
        .st-key-{css_key} div.stButton > button:active,
        .st-key-{css_key} [data-testid="stButton"] button:hover,
        .st-key-{css_key} [data-testid="stButton"] button:focus,
        .st-key-{css_key} [data-testid="stButton"] button:active,
        .st-key-{css_key} button:hover,
        .st-key-{css_key} button:focus,
        .st-key-{css_key} button:active {{
            color: {foreground} !important;
            background: {background} !important;
            background-color: {background} !important;
            border-color: #111111 !important;
        }}

        .st-key-{css_key} div.stButton > button p,
        .st-key-{css_key} [data-testid="stButton"] button p,
        .st-key-{css_key} button p {{
            width: 100% !important;
            margin: 0 !important;
            color: inherit !important;
            white-space: pre-line !important;
            text-align: left !important;
            font-size: .77rem !important;
            font-weight: 700 !important;
            line-height: 1.45 !important;
        }}

        .st-key-{css_key} div.stButton > button strong,
        .st-key-{css_key} [data-testid="stButton"] button strong,
        .st-key-{css_key} button strong {{
            display: block !important;
            margin: 7px 0 9px !important;
            color: inherit !important;
            font-family: "Archivo Black", sans-serif !important;
            font-size: clamp(1.25rem, 2.5vw, 2rem) !important;
            line-height: 1 !important;
            letter-spacing: -.035em !important;
        }}

        .st-key-{css_key} div.stButton > button code,
        .st-key-{css_key} [data-testid="stButton"] button code,
        .st-key-{css_key} button code {{
            display: inline-block !important;
            margin-top: 11px !important;
            padding: 4px 7px !important;
            border: 2px solid #111111 !important;
            border-radius: 0 !important;
            color: {badge_foreground} !important;
            background: {badge_background} !important;
            font-family: "IBM Plex Mono", monospace !important;
            font-size: .67rem !important;
            font-weight: 900 !important;
        }}

        {engine_alignment_css}
        </style>
        """,
        unsafe_allow_html=True,
    )
    label = f"{eyebrow}\n\n**{title}**\n\n{description}"
    if status:
        label += f"\n\n`{status}`"
    return st.button(
        label,
        key=key,
        use_container_width=True,
        help=help_text,
    )
