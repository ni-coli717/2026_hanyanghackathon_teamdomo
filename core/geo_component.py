from pathlib import Path
import streamlit.components.v1 as components

geo_locate = components.declare_component('geo_locate', path=str(Path(__file__).resolve().parents[1] / 'components/geo_locate'))
