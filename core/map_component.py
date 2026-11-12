from pathlib import Path
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
odor_map = components.declare_component('odor_map', path=str(ROOT/'components/odor_map'))
# 부스 시연 웹(demo/)을 배포본에서도 열 수 있게: https://odor-compass.streamlit.app/?demo=1
demo_web = components.declare_component('demo_web', path=str(ROOT/'demo'))
