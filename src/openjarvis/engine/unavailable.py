"""A stand-in engine for when no inference backend is reachable.

Why this exists
---------------
``jarvis serve`` used to exit when no engine could be resolved. That is the
right call for a chat-only server, but the API server carries capabilities
that need no model at all — Personal Jarvis contacts, telemetry, memory
browsing, health endpoints. Refusing to start took all of them down because
one optional dependency was missing.

This engine keeps the server startable. It is deliberately **not** registered
with ``EngineRegistry``: discovery must never find it and selection must never
choose it. ``serve`` constructs it explicitly, as a last resort, after
``get_engine()`` has come back empty.

Every inference call raises :class:`EngineConnectionError` with a message that
says what is missing and how to fix it. Failing per request — loudly, at the
point of use — is honest; silently returning empty completions would not be.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

from openjarvis.core.types import Message
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine._stubs import InferenceEngine, StreamChunk

__all__ = ["UnavailableEngine", "NO_ENGINE_MESSAGE"]

NO_ENGINE_MESSAGE = (
    "No inference engine is available. Start a local engine (for example "
    "'ollama serve') or configure an OpenAI-compatible endpoint, then reload. "
    "Features that do not need a model are unaffected."
)


class UnavailableEngine(InferenceEngine):
    """Answers every inference request with a clear, typed failure."""

    engine_id = "unavailable"
    is_cloud = False

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raise EngineConnectionError(NO_ENGINE_MESSAGE)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        raise EngineConnectionError(NO_ENGINE_MESSAGE)
        yield ""  # pragma: no cover — makes this an async generator

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        raise EngineConnectionError(NO_ENGINE_MESSAGE)
        yield StreamChunk()  # pragma: no cover — makes this an async generator

    def list_models(self) -> List[str]:
        return []

    def health(self) -> bool:
        """Always ``False``. Health checks must not report a working engine."""
        return False

    def can_serve(self, model: str) -> bool:
        """Never. Selection logic must not pick this engine over a real one."""
        return False
