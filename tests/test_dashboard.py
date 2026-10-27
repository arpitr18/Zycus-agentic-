"""Exercise the rendered dashboard without making any network/model calls."""
from streamlit.testing.v1 import AppTest
from pathlib import Path

def test_dashboard_loads_and_switches_tickets():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Ticket triage workbench"
    app.selectbox[0].select("TKT-128253").run()
    assert not app.exception
    assert any("NOTHING WORKS" in h.value for h in app.subheader)
