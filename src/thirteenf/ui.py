"""Shared presentation for the research workspace."""

import streamlit as st


def apply_theme() -> None:
    st.markdown("""
<style>
.stApp { background: #f4f7fb; }
.block-container { max-width: 1480px; padding-top: 2.5rem; padding-bottom: 3rem; }
h1, h2, h3 { letter-spacing: -.035em; }
h1 { font-weight: 750 !important; }
[data-testid="stSidebar"] { border-right: 1px solid #dce4ee; }
[data-testid="stSidebar"] [role="radiogroup"] { gap: .35rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    padding: .65rem .8rem; border-radius: 10px; width: 100%;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #e1ecef; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: #d8eeeb; color: #075c55; font-weight: 650;
}
[data-testid="stMetric"] {
    background: white; padding: 1.15rem 1.3rem; border: 1px solid #e1e7ef;
    border-radius: 14px; box-shadow: 0 3px 12px #152b4510;
}
[data-testid="stMetricValue"] { font-size: clamp(1.2rem, 2vw, 2rem); color: #15334c; }
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"], [data-testid="stExpander"] {
    background: white; border-radius: 14px; border: 1px solid #e1e7ef; overflow: hidden;
}
.stButton button, .stDownloadButton button { border-radius: 9px; min-height: 2.6rem; }
.research-hero {
    background: linear-gradient(110deg, #12283f, #164e59); color: white;
    padding: 2rem; border-radius: 18px; margin: .5rem 0 1.5rem;
}
.research-hero h2 { color: white; margin: 0 0 .5rem; font-size: 1.8rem; }
.research-hero p { color: #d5e6ed; margin: 0; max-width: 760px; }
.eyebrow { color: #0b776e; font-size: .75rem; font-weight: 700; letter-spacing: .14em; }
@media (max-width: 640px) {
    .block-container { padding: 1.5rem 1rem; }
    .research-hero { padding: 1.35rem; }
    [data-testid="stMetric"] { padding: .8rem; }
}
</style>
""", unsafe_allow_html=True)


def page_header(title: str, description: str) -> None:
    st.markdown('<div class="eyebrow">13F / RESEARCH WORKSPACE</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(description)
