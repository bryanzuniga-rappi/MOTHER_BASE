from __future__ import annotations

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
            --white: #fffdf7;
            --muted: #6f6b63;
        }

        html, body, [class*="css"] {
            font-family: "IBM Plex Mono", monospace;
            color: var(--ink);
        }

        .stApp {
            color: var(--ink) !important;
            background:
                linear-gradient(rgba(17,17,17,.055) 1px, transparent 1px),
                linear-gradient(90deg, rgba(17,17,17,.055) 1px, transparent 1px),
                var(--paper) !important;
            background-size: 28px 28px !important;
        }

        [data-testid="stHeader"] { background: transparent; }
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
