"""All pytest tests are offline; a real Groq client is forbidden."""
import pytest

@pytest.fixture(autouse=True)
def no_live_groq(monkeypatch):
    import groq
    class ForbiddenClient:
        def __init__(self,*args,**kwargs):
            raise AssertionError("Live Groq calls are forbidden in the offline test suite")
    monkeypatch.setattr(groq,"Groq",ForbiddenClient)
    monkeypatch.setenv("EMBEDDING_MODEL","")
