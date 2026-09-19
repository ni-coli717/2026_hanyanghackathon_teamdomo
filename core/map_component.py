from pathlib import Path
import streamlit.components.v1 as components

odor_map = components.declare_component('odor_map', path=str(Path(__file__).resolve().parents[1]/'components/odor_map'))
