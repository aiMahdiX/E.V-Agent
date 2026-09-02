"""Ollama LLM client — local-first inference via the Ollama HTTP API.

Uses only the standard library. Optimised for low latency:

- keep_alive  : keep the model resident in VRAM between requests
- think=False : disable reasoning tokens for thinking models (big win)
- num_predict : cap generation length so responses finish faster
- warm()      : preload the model at startup so the first reply is instant
- chat_stream : incremental streaming for perceived latency
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error


class LLMError(RuntimeError):
    pass


def _is_remote(model: str) -> bool:
    return "cloud" in model.lower()


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434",
                 model: str = "qwen3.5:4b", timeout: int = 300,
                 keep_alive: str = "30m", num_predict: int = 512,
                 num_ctx: int = 8192, think: bool = False,
                 temperature: float = 0.6,
                 cloud_timeout: int = 45,
                 fallback_model: str | None = None):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.cloud_timeout = cloud_timeout
        self.fallback_model = fallback_model
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.num_ctx = num_ctx
        self.think = think
        self.temperature = temperature

    # ------------------------------------------------------------------ #
    # low level                                                          #
    # ------------------------------------------------------------------ #
    def _post(self, path: str, payload: dict, stream: bool = False,
              timeout: float | None = None):
        url = f"{self.host}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if timeout is None:
            timeout = (self.cloud_timeout
                       if _is_remote(str(payload.get("model", "")))
                       else self.timeout)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"Ollama HTTP {e.code}: {detail}") from e
        except TimeoutError as e:
            raise LLMError(
                f"Ollama timed out after {timeout}s "
                f"(model={payload.get('model')})") from e
        except urllib.error.URLError as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.host} ({e.reason}). "
                "Start it with 'ollama serve'."
            ) from e
        if stream:
            return resp   # caller owns the response and closes it
        try:
            return json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()

    def _get_json(self, path: str):
        try:
            with urllib.request.urlopen(f"{self.host}{path}",
                                        timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.host} ({e.reason}).") from e

    # ------------------------------------------------------------------ #
    # availability / model management                                    #
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        try:
            self._get_json("/api/tags")
            return True
        except LLMError:
            return False

    def list_models(self) -> list[str]:
        data = self._get_json("/api/tags")
        return [m.get("name", "") for m in data.get("models", [])]

    def has_model(self, model: str | None = None) -> bool:
        return (model or self.model) in self.list_models()

    def pull(self, model: str, progress: bool = True) -> None:
        """Stream-pull a model (e.g. 'qwen3:4b'). Raises LLMError on failure."""
        if progress:
            print(f"Pulling {model} … (this can take a while)")
        raw = self._post("/api/pull", {"model": model, "stream": True},
                         stream=True)
        for line in raw:
            if not line:
                continue
            try:
                chunk = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            status = chunk.get("status", "")
            if progress and "downloading" in status:
                pass  # avoid spamming
            if chunk.get("error"):
                raise LLMError(chunk["error"])
        if progress:
            print(f"Model {model} ready.")

    # ------------------------------------------------------------------ #
    # chat / generation                                                  #
    # ------------------------------------------------------------------ #
    def warm(self, model: str | None = None) -> None:
        """Preload a local model into VRAM so the first reply is instant."""
        target = model or self.model
        if _is_remote(target):
            return
        try:
            self.generate(".", model=target, options={"num_predict": 1})
        except LLMError:
            pass  # warm-up is best-effort; a later call still works

    # ------------------------------------------------------------------ #
    # payload helpers                                                    #
    # ------------------------------------------------------------------ #
    def _base_options(self, temperature: float | None,
                      options: dict | None) -> dict:
        opt = {
            "temperature": temperature if temperature is not None
            else self.temperature,
            "num_predict": self.num_predict,
        }
        if self.num_ctx:
            opt["num_ctx"] = self.num_ctx
        if options:
            opt.update(options)
        return opt

    def _chat_payload(self, messages, tools, model, temperature,
                      options, stream):
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": self._base_options(temperature, options),
        }
        if tools:
            payload["tools"] = tools
        if self.think is not None:
            payload["think"] = self.think
        return payload

    # ------------------------------------------------------------------ #
    # chat / generation                                                  #
    # ------------------------------------------------------------------ #
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             model: str | None = None, temperature: float | None = None,
             options: dict | None = None) -> dict:
        """Single non-streaming chat round. Returns the raw /api/chat body.

        If the (cloud) model fails and ``fallback_model`` is set, retries
        once with the fallback and annotates the body with ``ev_fallback``.
        """
        payload = self._chat_payload(
            messages, tools, model, temperature, options, stream=False)
        try:
            return self._post("/api/chat", payload)
        except LLMError as e:
            fb = self.fallback_model
            if fb and _is_remote(str(payload.get("model", ""))) \
                    and not _is_remote(fb):
                body = self._post("/api/chat", {
                    **payload, "model": fb})
                body["ev_fallback"] = {"from": payload["model"],
                                       "to": fb, "error": str(e)[:200]}
                return body
            raise

    def chat_stream(self, messages: list[dict],
                    tools: list[dict] | None = None,
                    model: str | None = None,
                    temperature: float | None = None,
                    options: dict | None = None):
        """Streamed chat — yields NDJSON chunks from Ollama.

        Cloud failure -> single retry with local ``fallback_model``;
        a first synthetic chunk announces the switch.
        """
        payload = self._chat_payload(
            messages, tools, model, temperature, options, stream=True)
        try:
            raw = self._post("/api/chat", payload, stream=True)
        except LLMError as e:
            fb = self.fallback_model
            if not (fb and _is_remote(str(payload.get("model", "")))
                    and not _is_remote(fb)):
                raise
            yield {"model": fb, "ev_fallback":
                   {"from": payload["model"], "to": fb,
                    "error": str(e)[:200]}}
            payload = {**payload, "model": fb}
            raw = self._post("/api/chat", payload, stream=True)
        try:
            for line in raw:
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                yield chunk
        finally:
            raw.close()

    def generate(self, prompt: str, model: str | None = None,
                 temperature: float = 0.6,
                 options: dict | None = None) -> str:
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": self._base_options(temperature, options),
        }
        data = self._post("/api/generate", payload)
        return data.get("response", "")
