from __future__ import annotations

import streamlit as st


def inject_mother_base_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Black+Ops+One&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');

        :root {
            --mb-black: #080b09;
            --mb-panel: #111713;
            --mb-panel-2: #182019;
            --mb-line: #8fa68b;
            --mb-green: #c8ff3d;
            --mb-red: #ff493d;
            --mb-paper: #e9eadf;
            --mb-muted: #9ba49a;
        }

        html, body, [class*="css"] {
            font-family: "IBM Plex Mono", monospace;
        }

        .stApp {
            color: var(--mb-paper);
            background:
                linear-gradient(rgba(143,166,139,.08) 1px, transparent 1px),
                linear-gradient(90deg, rgba(143,166,139,.08) 1px, transparent 1px),
                radial-gradient(circle at 80% 10%, rgba(200,255,61,.07), transparent 28%),
                var(--mb-black);
            background-size: 28px 28px, 28px 28px, auto, auto;
        }

        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stSidebar"] {
            background: #0b100c;
            border-right: 2px solid var(--mb-line);
        }

        h1, h2, h3 {
            font-family: "Black Ops One", "IBM Plex Mono", monospace !important;
            letter-spacing: .04em;
        }

        .mb-scanline {
            height: 5px;
            margin: 8px 0 22px;
            background: repeating-linear-gradient(
                90deg,
                var(--mb-green) 0 18px,
                transparent 18px 25px
            );
        }

        .mb-hero {
            position: relative;
            overflow: hidden;
            padding: 38px 42px;
            border: 2px solid var(--mb-line);
            box-shadow: 9px 9px 0 #000;
            background: linear-gradient(135deg, #151d16, #090d0a 70%);
        }

        .mb-hero::after {
            content: "MB";
            position: absolute;
            right: 24px;
            top: -34px;
            color: rgba(200,255,61,.06);
            font: 190px/1 "Black Ops One", monospace;
        }

        .mb-kicker {
            display: inline-block;
            padding: 5px 9px;
            color: var(--mb-black);
            background: var(--mb-green);
            font-weight: 800;
            letter-spacing: .12em;
        }

        .mb-hero h1 {
            position: relative;
            z-index: 1;
            margin: 20px 0 8px;
            color: var(--mb-paper);
            font-size: clamp(44px, 8vw, 92px);
            line-height: .9;
        }

        .mb-hero p {
            position: relative;
            z-index: 1;
            max-width: 720px;
            color: var(--mb-muted);
            font-size: 15px;
        }

        .mb-card {
            min-height: 190px;
            padding: 23px;
            border: 2px solid var(--mb-line);
            box-shadow: 7px 7px 0 #000;
            background: var(--mb-panel);
        }

        .mb-card.active { border-color: var(--mb-green); }
        .mb-card.wip { border-color: var(--mb-red); }
        .mb-card h3 { margin: 9px 0; color: var(--mb-paper); }
        .mb-card p { color: var(--mb-muted); }
        .mb-card-code { color: var(--mb-green); font-size: 12px; font-weight: 700; }
        .mb-wip { color: var(--mb-red); font-weight: 800; }

        .mb-profile {
            padding: 14px;
            margin-bottom: 15px;
            border: 1px solid var(--mb-line);
            background: var(--mb-panel);
        }

        .mb-profile strong { color: var(--mb-green); }

        div.stButton > button,
        div.stDownloadButton > button,
        div[data-testid="stFormSubmitButton"] > button {
            min-height: 45px;
            border: 2px solid var(--mb-line) !important;
            border-radius: 0 !important;
            box-shadow: 5px 5px 0 #000 !important;
            color: var(--mb-paper) !important;
            background: var(--mb-panel-2) !important;
            font-family: "IBM Plex Mono", monospace !important;
            font-weight: 800 !important;
            text-transform: uppercase;
        }

        div.stButton > button:hover,
        div.stDownloadButton > button:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            border-color: var(--mb-green) !important;
            color: var(--mb-black) !important;
            background: var(--mb-green) !important;
            transform: translate(-2px, -2px);
            box-shadow: 7px 7px 0 #000 !important;
        }

        [data-testid="stMetric"] {
            border: 1px solid var(--mb-line);
            padding: 15px;
            background: var(--mb-panel);
        }

        [data-testid="stFileUploaderDropzone"],
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        [data-testid="stNumberInput"] input,
        textarea {
            border-radius: 0 !important;
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

