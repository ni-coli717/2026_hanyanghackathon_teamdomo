from __future__ import annotations

import html
import math
from pathlib import Path

import pandas as pd

from .risk import LEVEL_COLORS, wind_name


CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
:root{--bg:#F7F9FB;--ink:#1B2A38;--blue:#1F5C8B;--teal:#2E8B74;--line:#DCE4E9;}
html,body,[class*="css"],.stApp{font-family:Pretendard,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);}
.stApp{background:linear-gradient(180deg,#F7F9FB 0%,#F3F6F8 100%)}
.block-container{max-width:1240px;padding-top:1.25rem;padding-bottom:3rem}
[data-testid="stHeader"]{background:rgba(247,249,251,.88);backdrop-filter:blur(10px)}
[data-baseweb="tab-list"]{gap:.3rem;background:#EAF0F4;padding:.35rem;border-radius:14px;position:sticky;top:3.2rem;z-index:20}
[data-baseweb="tab"]{height:44px;border-radius:10px;padding:0 1rem;font-weight:700}
[aria-selected="true"]{background:white!important;color:#1F5C8B!important;box-shadow:0 2px 10px rgba(27,42,56,.08)}
div[role="radiogroup"]{display:flex;gap:.3rem;background:#EAF0F4;padding:.35rem;border-radius:14px;position:sticky;top:3.2rem;z-index:20;overflow-x:auto}div[role="radiogroup"] label{background:transparent;padding:.45rem .8rem;border-radius:10px;white-space:nowrap}div[role="radiogroup"] label:has(input:checked){background:white;box-shadow:0 2px 10px rgba(27,42,56,.08);color:#1F5C8B}
.sample-banner{position:relative;background:#FFF5E7;border:1px solid #E8C58D;border-left:5px solid #D99A3C;padding:.7rem 1rem;border-radius:12px;margin:.4rem 0 1rem;font-size:.9rem;font-weight:700}
.hero{display:grid;grid-template-columns:1.25fr .75fr;gap:1.2rem;background:white;border:1px solid var(--line);border-radius:18px;padding:1.7rem;box-shadow:0 8px 28px rgba(31,92,139,.07);overflow:hidden}
.eyebrow{color:var(--teal);font-weight:800;letter-spacing:.08em;font-size:.78rem}.hero h1{font-size:2.25rem;margin:.35rem 0 .2rem;letter-spacing:-.04em}.subtitle{color:#647684;font-size:.88rem}.hero-copy{color:#485C6B;line-height:1.65;margin-top:1rem;max-width:620px}
.card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.9rem;margin:1rem 0}.card{background:white;border:1px solid var(--line);border-radius:12px;padding:1rem;box-shadow:0 3px 14px rgba(27,42,56,.045)}
.card-label{color:#71818C;font-size:.78rem;font-weight:700;margin-bottom:.45rem}.card-value{font-size:1.45rem;font-weight:850;line-height:1.2;font-variant-numeric:tabular-nums}.card-note{color:#71818C;font-size:.8rem;margin-top:.45rem;line-height:1.45}.badge{display:inline-flex;align-items:center;gap:.25rem;padding:.25rem .52rem;border-radius:999px;font-size:.72rem;font-weight:800;color:white;vertical-align:middle}.badge.soft{background:#E7EEF3;color:#465A68}.badge.sample{background:#D99A3C}.hatched{background-color:#EEF1F3;background-image:repeating-linear-gradient(135deg,transparent,transparent 5px,rgba(106,120,130,.22) 5px,rgba(106,120,130,.22) 7px)}
.section-head{margin:1.5rem 0 .65rem}.section-head h2{font-size:1.22rem;margin:0}.section-head p{color:#6B7D89;margin:.25rem 0 0;font-size:.86rem}.mini-note{padding:.7rem .85rem;background:#EDF4F3;border-left:3px solid var(--teal);border-radius:8px;color:#395B56;font-size:.84rem}
.risk-low{border-top:4px solid #3D8B5F}.risk-medium{border-top:4px solid #D99A3C}.risk-high{border-top:4px solid #C0563B}.risk-hold{border-top:4px solid #9AA5AE}
.compass-wrap{display:flex;justify-content:center;align-items:center;min-height:270px}.compass-svg{width:min(100%,290px);height:auto;filter:drop-shadow(0 8px 14px rgba(31,92,139,.08))}
.wordmark{display:flex;gap:.7rem;align-items:center}.wordmark img{width:38px}.wordmark strong{font-size:1.05rem}.wordmark small{display:block;color:#71818C}
div[data-testid="stForm"]{background:white;border:1px solid var(--line);border-radius:14px;padding:1rem}div[data-testid="stFormSubmitButton"] button,.stButton button{min-height:46px;border-radius:10px;font-weight:750}.record-shell button{min-height:56px}
div[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:12px;overflow:hidden}
@media(max-width:760px){.block-container{padding:.65rem}.hero{grid-template-columns:1fr;padding:1.1rem}.hero h1{font-size:1.8rem}.card-grid{grid-template-columns:1fr}.compass-wrap{min-height:220px}[data-baseweb="tab"]{padding:0 .65rem;font-size:.78rem}.record-shell [data-testid="stHorizontalBlock"]{flex-direction:column}.record-shell button{min-height:56px;width:100%}}
</style>
"""


def logo_wordmark() -> str:
    svg = Path("assets/logo.svg").read_text(encoding="utf-8")
    import base64
    encoded = base64.b64encode(svg.encode()).decode()
    return f'<div class="wordmark"><img src="data:image/svg+xml;base64,{encoded}"/><div><strong>냄새 나침반</strong><small>주민참여형 악취 진단 · 예보</small></div></div>'


def card(label: str, value: str, note: str = "", css_class: str = "") -> str:
    return f'<div class="card {css_class}"><div class="card-label">{html.escape(label)}</div><div class="card-value">{value}</div><div class="card-note">{note}</div></div>'


def badge(text: str, color: str = "#1F5C8B") -> str:
    return f'<span class="badge" style="background:{color}">{html.escape(text)}</span>'


def compass_svg(wd: float | None, ws: float | None, geometry: pd.DataFrame, active_source: str | None, compact: bool = False) -> str:
    size = 225 if compact else 290
    calm = ws is None or pd.isna(ws) or ws < 0.5 or wd is None or pd.isna(wd)
    needle_rotation = 90 if calm else float(wd)
    rays = []
    for _, row in geometry.iterrows():
        angle = math.radians(row.bearing_deg - 90)
        r1, r2 = 73, 102
        x1, y1 = 120 + r1 * math.cos(angle), 120 + r1 * math.sin(angle)
        x2, y2 = 120 + r2 * math.cos(angle), 120 + r2 * math.sin(angle)
        active = row.source_id == active_source and not calm
        rays.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{"#2E8B74" if active else "#9AA5AE"}" stroke-width="{"5" if active else "2"}" stroke-dasharray="4 4"/><text x="{x2:.1f}" y="{y2-4:.1f}" text-anchor="middle" fill="#526674" font-size="9" font-weight="800">{row.source_id}</text>')
    needle = "#9AA5AE" if calm else "#1F5C8B"
    status = "무풍 · 방향 보류" if calm else f'{wind_name(wd)}풍 {float(wd):.0f}° · {float(ws):.1f}m/s'
    return f'''<div class="compass-wrap"><svg xmlns="http://www.w3.org/2000/svg" class="compass-svg" width="{size}" viewBox="0 0 240 260" role="img" aria-label="현재 풍향 나침반">
      <defs><filter id="s"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity=".12"/></filter></defs>
      <circle cx="120" cy="120" r="106" fill="#FBFCFD" stroke="#D9E3E9" stroke-width="2" filter="url(#s)"/>
      <circle cx="120" cy="120" r="82" fill="none" stroke="#BFCBD2" stroke-width="1" stroke-dasharray="2 5"/>
      <g fill="#516673" font-size="10" font-weight="800"><text x="120" y="25" text-anchor="middle">N</text><text x="216" y="124">E</text><text x="120" y="222" text-anchor="middle">S</text><text x="18" y="124">W</text></g>
      {''.join(rays)}
      <g transform="rotate({needle_rotation:.1f} 120 120)" opacity="{'.45' if calm else '1'}"><path d="M120 34 L132 126 L120 116 L108 126 Z" fill="{needle}"/><path d="M120 206 L112 118 L120 126 L128 118 Z" fill="#C6D0D6"/></g>
      <circle cx="120" cy="120" r="7" fill="#F7F9FB" stroke="{needle}" stroke-width="4"/>
      <path d="M100 234c12-5 26 5 39 0 8-3 13-2 19 0M107 242c10-3 19 3 30 0" fill="none" stroke="#2E8B74" stroke-width="2.5" stroke-linecap="round"/>
      <text x="120" y="257" text-anchor="middle" fill="#526674" font-size="10" font-weight="700">{status}</text>
    </svg></div>'''


def section(title: str, description: str = "") -> str:
    return f'<div class="section-head"><h2>{html.escape(title)}</h2><p>{html.escape(description)}</p></div>'
