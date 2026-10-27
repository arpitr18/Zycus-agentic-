"""Exercise retry policy without network access or credentials."""
import sys
from types import SimpleNamespace
import pytest
from tam_agent.llm import LLMClient

class StatusError(Exception):
    def __init__(self, status, retry_after="0"):
        self.status_code = status
        self.response = SimpleNamespace(headers={"retry-after":retry_after})

class ConnectionError(Exception):
    pass

class TimeoutError(Exception):
    pass

def setup(monkeypatch, outcomes):
    outcomes = iter(outcomes)
    def create(**kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(
            model_dump=lambda **kw: {"role":"assistant", "content":"ok"}))])
    fake = SimpleNamespace(Groq=lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        APIConnectionError=ConnectionError, APITimeoutError=TimeoutError, APIStatusError=StatusError)
    monkeypatch.setitem(sys.modules, "groq", fake)
    monkeypatch.setenv("GROQ_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    sleeps = []
    monkeypatch.setattr("tam_agent.llm.time.sleep", sleeps.append)
    monkeypatch.setattr("tam_agent.llm.random.random", lambda:0)
    return LLMClient(), sleeps

def test_retry_after_and_transient_connection(monkeypatch):
    client,sleeps = setup(monkeypatch, [StatusError(429,"7"),ConnectionError(),True])
    assert client.complete([],[])["content"] == "ok"
    assert sleeps == [7,2]
    assert client.calls == 3
    assert len(client.events) == 3

def test_permanent_error_is_sanitized(monkeypatch):
    client,sleeps = setup(monkeypatch, [StatusError(401)])
    with pytest.raises(RuntimeError, match="status=401") as err:
        client.complete([],[])
    assert "test-only" not in str(err.value)
    assert not sleeps
    assert client.calls == 1

def test_retry_budget_and_long_wait(monkeypatch):
    client,sleeps = setup(monkeypatch, [StatusError(503)]*3)
    with pytest.raises(RuntimeError):
        client.complete([],[])
    assert client.calls == 3
    client,sleeps = setup(monkeypatch, [StatusError(429,"300")])
    with pytest.raises(RuntimeError,match="longer wait"):
        client.complete([],[])
    assert not sleeps

def test_missing_key_fails_before_call(monkeypatch):
    client,_ = setup(monkeypatch, [])
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(RuntimeError,match="missing"):
        client.complete([],[])
    assert client.calls == 0


def test_rejected_tool_generation_is_retried_without_execution(monkeypatch):
    error = StatusError(400)
    error.body = {"error":{"code":"tool_use_failed"}}
    client,sleeps = setup(monkeypatch, [error,True])
    assert client.complete([],[])["content"] == "ok"
    assert client.calls == 2
    assert not sleeps


def test_starter_chat_interface_is_preserved(monkeypatch):
    client,_=setup(monkeypatch,[True])
    assert client.chat([{"role":"user","content":"Hello"}],system="Be concise",max_tokens=32)=="ok"
    assert client.calls==1


@pytest.mark.parametrize("detail",["tokens per day (TPD)","requests per day (RPD)"])
def test_daily_quota_fails_without_wait_or_retry(monkeypatch,detail):
    from tam_agent.llm import GroqDailyQuotaError
    error=StatusError(429,"10")
    error.body={"error":{"code":"rate_limit_exceeded","message":detail}}
    client,sleeps=setup(monkeypatch,[error])
    with pytest.raises(GroqDailyQuotaError,match="daily quota exhausted"):
        client.complete([],[])
    assert client.calls==1
    assert sleeps==[]
    assert client.events[-1]["event"]=="quota_exhausted"
