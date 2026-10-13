"""Native Gemini Live speech-to-speech provider adapter.

The SDK is imported lazily. No credential lookup or network request occurs
until an explicit connection test or a user-consented Live session.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from voice.interfaces import AudioChunk


class LiveProviderError(RuntimeError):
    pass


class GeminiLiveProvider:
    provider = "gemini_live"

    def __init__(self, api_key: str, model: str = "gemini-3.8-live",
                 voice_name: str | None = None):
        if not api_key:
            raise LiveProviderError("Gemini API key is not configured.")
        self._api_key = api_key
        self.model = model
        self.voice_name = voice_name

    @staticmethod
    def _sdk():
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LiveProviderError(
                "Gemini Live requires the optional google-genai package.") from exc
        return genai, types

    def _client(self):
        genai, _ = self._sdk()
        return genai.Client(api_key=self._api_key)

    def validate_credentials(self) -> dict:
        """Make one explicit metadata request; does not generate text/audio."""
        client = self._client()
        try:
            model = client.models.get(model=self.model)
            return {"ok": True, "provider": self.provider,
                    "model": str(getattr(model, "name", self.model))}
        except Exception as exc:  # noqa: BLE001 - never return a secret
            detail = str(exc).replace(self._api_key, "[REDACTED]")[:500]
            return {"ok": False, "provider": self.provider,
                    "error": detail or type(exc).__name__}
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _function_tools(tool_schemas: list[dict] | None,
                        types_module) -> list:
        declarations = []
        for schema in tool_schemas or []:
            function = schema.get("function", {})
            name = function.get("name")
            if not name:
                continue
            declaration = {
                "name": name,
                "description": function.get("description", ""),
                "parameters_json_schema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
            declarations.append(types_module.FunctionDeclaration(**declaration))
        return ([types_module.Tool(function_declarations=declarations)]
                if declarations else [])

    async def connect(self, *, system_instruction: str,
                      tool_schemas: list[dict] | None = None):
        genai, types = self._sdk()
        client = self._client()
        config = {
            "response_modalities": ["AUDIO"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "system_instruction": system_instruction,
            "tools": self._function_tools(tool_schemas, types),
        }
        if self.voice_name:
            config["speech_config"] = {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": self.voice_name}
                }
            }
        manager = client.aio.live.connect(model=self.model, config=config)
        try:
            session = await manager.__aenter__()
        except Exception as exc:  # noqa: BLE001 - sanitize provider errors
            close = getattr(client.aio, "aclose", None)
            if callable(close):
                await close()
            detail = str(exc).replace(self._api_key, "[REDACTED]")[:500]
            raise LiveProviderError(detail or type(exc).__name__) from exc
        return GeminiLiveSession(client, manager, session, types)


class GeminiLiveSession:
    provider = "gemini_live"
    input_sample_rate = 16000
    output_sample_rate = 24000

    def __init__(self, client, manager, session, types_module):
        self._client = client
        self._manager = manager
        self._session = session
        self._types = types_module
        self._closed = False

    async def send_audio(self, audio: AudioChunk) -> None:
        if self._closed:
            raise LiveProviderError("Live session is closed.")
        if audio.sample_format != "s16le" or audio.channels != 1:
            raise LiveProviderError("Live input must be mono s16le PCM audio.")
        await self._session.send_realtime_input(
            audio=self._types.Blob(
                data=audio.data,
                mime_type=f"audio/pcm;rate={audio.sample_rate}"))

    async def send_text(self, text: str) -> None:
        if self._closed:
            raise LiveProviderError("Live session is closed.")
        await self._session.send_realtime_input(text=text)

    async def send_tool_responses(self, responses: list[dict]) -> None:
        if self._closed:
            raise LiveProviderError("Live session is closed.")
        values = [self._types.FunctionResponse(
            id=item.get("id"), name=item["name"],
            response={"result": item.get("result")})
            for item in responses]
        await self._session.send_tool_response(function_responses=values)

    async def interrupt(self) -> None:
        """Flush the input stream; user speech itself triggers server barge-in."""
        if not self._closed:
            await self._session.send_realtime_input(audio_stream_end=True)

    async def receive(self) -> AsyncIterator[dict]:
        if self._closed:
            raise LiveProviderError("Live session is closed.")
        async for response in self._session.receive():
            server = getattr(response, "server_content", None)
            if server is not None:
                input_text = getattr(server, "input_transcription", None)
                if input_text and getattr(input_text, "text", None):
                    yield {"type": "input_transcription",
                           "text": input_text.text}
                output_text = getattr(server, "output_transcription", None)
                if output_text and getattr(output_text, "text", None):
                    yield {"type": "output_transcription",
                           "text": output_text.text}
                turn = getattr(server, "model_turn", None)
                if turn:
                    for part in getattr(turn, "parts", []) or []:
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            yield {"type": "audio", "data": inline.data,
                                   "sample_rate": self.output_sample_rate,
                                   "sample_format": "s16le"}
                        text = getattr(part, "text", None)
                        if text:
                            yield {"type": "text", "text": text}
                if getattr(server, "interrupted", False):
                    yield {"type": "interrupted"}
                if getattr(server, "turn_complete", False):
                    yield {"type": "turn_complete"}

            tool_call = getattr(response, "tool_call", None)
            if tool_call:
                calls = []
                for call in getattr(tool_call, "function_calls", []) or []:
                    calls.append({"id": getattr(call, "id", None),
                                  "name": call.name,
                                  "args": dict(call.args or {})})
                if calls:
                    yield {"type": "tool_calls", "calls": calls}

            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                yield {"type": "usage", "provider": self.provider,
                       "total_tokens": getattr(usage, "total_token_count", None),
                       "input_tokens": getattr(usage, "prompt_token_count", None),
                       "output_tokens": getattr(usage, "response_token_count", None)}

            go_away = getattr(response, "go_away", None)
            if go_away is not None:
                yield {"type": "reconnect_soon",
                       "seconds": getattr(go_away, "time_left", None)}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._manager.__aexit__(None, None, None)
        finally:
            close = getattr(self._client.aio, "aclose", None)
            if callable(close):
                await close()