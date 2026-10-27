"""Groq native tool calling with bounded retries and secret-safe telemetry."""
import logging
import os
import random
import time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
log = logging.getLogger(__name__)

class GroqDailyQuotaError(RuntimeError):
    """Non-transient quota failure: requires a deliberate retry after reset."""

class LLMClient:
    def __init__(self, provider=None, model=None):
        self.provider = provider or os.getenv("LLM_PROVIDER", "groq")
        if self.provider != "groq":
            raise ValueError("Use LLM_PROVIDER=groq")
        self.model = model or os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
        self.calls, self.events, self._client = 0, [], None
        self.event_sink = None

    def record(self, event):
        self.events.append(event)
        if self.event_sink:
            self.event_sink(event)

    def chat(self, messages, system=None, max_tokens=1024, temperature=0.0):
        """Compatibility with the starter text-chat interface; agent uses complete()."""
        prepared = ([{"role":"system","content":system}] if system else []) + list(messages)
        response = self.complete(prepared, [], max_tokens=max_tokens, temperature=temperature)
        return response.get("content") or ""

    def complete(self, messages, tools, *, max_tokens=None, temperature=0.0):
        from groq import Groq, APIConnectionError, APITimeoutError, APIStatusError
        if self._client is None:
            if not os.getenv("GROQ_API_KEY"):
                raise RuntimeError("GROQ_API_KEY missing; configure .env before live triage")
            self._client = Groq(timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")), max_retries=0)
        retries = int(os.getenv("LLM_MAX_RETRIES", "4"))
        request_messages = list(messages)
        for attempt in range(retries + 1):
            started = time.perf_counter()
            self.calls += 1
            try:
                request = {"model":self.model, "messages":request_messages, "temperature":temperature,
                           "max_completion_tokens":max_tokens if max_tokens is not None else int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "2000"))}
                if tools:
                    request.update(tools=tools, tool_choice="auto", parallel_tool_calls=False)
                response = self._client.chat.completions.create(**request)
                self.record({"event": "llm", "seconds": round(time.perf_counter()-started, 3),
                    "usage": response.usage.model_dump() if response.usage else {}})
                return response.choices[0].message.model_dump(exclude_none=True)
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                body = getattr(exc, "body", {}) or {}
                error = body.get("error", body) if isinstance(body, dict) else {}
                code = error.get("code") if isinstance(error, dict) else None
                self.record({"event": "llm_error", "type": type(exc).__name__, "status": status, "code": code,
                    "seconds": round(time.perf_counter()-started, 3)})
                if status == 400 and code == "tool_use_failed" and attempt < retries:
                    request_messages.append({"role":"user", "content": "The provider rejected the last generated tool call. No tool was executed. Use a valid tool name and arguments matching its JSON schema exactly. Include all required fields; omit extra fields."})
                    continue
                detail = str(error.get("message", ""))[:400] if isinstance(error, dict) else ""
                secret = os.getenv("GROQ_API_KEY", "")
                if secret:
                    detail = detail.replace(secret, "[REDACTED]")
                if status == 429 and any(marker in detail.lower() for marker in ("tokens per day", "requests per day", "(tpd)", "(rpd)", "daily quota")):
                    self.record({"event":"quota_exhausted", "scope":"daily", "model":self.model})
                    raise GroqDailyQuotaError(f"Groq daily quota exhausted for {self.model}. Investigation stopped without a new result. Retry manually after quota reset or configure a model/key with available quota.") from None
                if attempt == retries or (status is not None and status not in (408, 409, 429) and status < 500):
                    raise RuntimeError(f"Groq request failed ({type(exc).__name__}, status={status}, code={code}): {detail}") from None
                header = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after", "0")
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = 0
                delay = max(retry_after, min(30, 2 ** attempt) + random.random())
                if delay > 120:
                    raise RuntimeError(f"Rate limit requires a longer wait ({delay:.0f}s); retry this ticket later: {detail}") from None
                log.warning("Retrying Groq status=%s in %.1fs", status, delay)
                time.sleep(delay)
