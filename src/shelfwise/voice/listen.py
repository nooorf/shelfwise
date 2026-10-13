"""Hearing the reader: the browser streams 16 kHz 16-bit mono PCM; Silero
VAD decides where the utterance starts and ends (endpointing); Whisper transcribes it.

Endpointing: speech starts at the first 32 ms chunk above START_PROB and ends after
END_SILENCE_MS below END_PROB (600 ms to start with; tune on set F). An utterance is
cut at MAX_UTTERANCE_S, and listening gives up after NO_SPEECH_S of silence.

Models (not in git): `make download-stt` puts Silero VAD in data/models/silero; Whisper (MLX on
Apple Silicon) is fetched from Hugging Face on first use.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

log = logging.getLogger(__name__)

RATE = 16_000
CHUNK = 512  # samples per VAD step: 32 ms at 16 kHz (what Silero expects)
_CONTEXT = 64  # samples of the previous chunk Silero v5+ wants in front of each one
START_PROB = 0.5
END_PROB = 0.35
END_SILENCE_MS = 600
MAX_UTTERANCE_S = 15.0
NO_SPEECH_S = 8.0
PAD_MS = 200  # audio kept from before the start, so the first syllable isn't clipped

VAD_FILE = "silero_vad.onnx"

Event = Literal["start", "end", "timeout"]


class VAD(Protocol):
    def fresh(self) -> Callable[[np.ndarray], float]:
        """A speech-probability function with its own state, for one utterance."""
        ...


class SileroVAD:
    """Speech probability per 512-sample chunk; stateful, so one per utterance (`fresh`)."""

    def __init__(self, model: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model), options, providers=["CPUExecutionProvider"]
        )
        self._lock = threading.Lock()

    def fresh(self) -> Callable[[np.ndarray], float]:
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, _CONTEXT), dtype=np.float32)

        def prob(chunk: np.ndarray) -> float:
            nonlocal state, context
            x = np.concatenate([context, chunk.reshape(1, -1).astype(np.float32)], axis=1)
            with self._lock:
                out, new_state = self._session.run(
                    None, {"input": x, "state": state, "sr": np.array(RATE, dtype=np.int64)}
                )
            state = np.asarray(new_state, dtype=np.float32)
            context = x[:, -_CONTEXT:]
            return float(np.asarray(out).reshape(-1)[0])

        return prob


@dataclass
class Endpointer:
    """Feeds PCM in, says when the utterance starts and ends, keeps its audio."""

    prob: Callable[[np.ndarray], float]  # speech probability of one CHUNK (float32 in [-1, 1])
    end_silence_ms: int = END_SILENCE_MS
    _pending: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    _chunks: list[np.ndarray] = field(default_factory=list)
    _started_at: int | None = None  # chunk index
    _quiet: int = 0  # chunks below END_PROB since the last speech
    _seen: int = 0
    done: bool = False

    def feed(self, pcm16: bytes) -> list[Event]:
        """16-bit little-endian mono PCM at 16 kHz, any length."""
        if self.done:
            return []
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768
        self._pending = np.concatenate([self._pending, samples])
        events: list[Event] = []
        ms = CHUNK * 1000 // RATE
        while len(self._pending) >= CHUNK and not self.done:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            self._chunks.append(chunk)
            self._seen += 1
            p = self.prob(chunk)
            if self._started_at is None:
                if p >= START_PROB:
                    self._started_at = self._seen - 1
                    events.append("start")
                elif self._seen * ms >= NO_SPEECH_S * 1000:
                    self.done = True
                    events.append("timeout")
                else:
                    self._chunks = self._chunks[-(PAD_MS // ms) :]  # only the pre-roll
                continue
            self._quiet = self._quiet + 1 if p < END_PROB else 0
            long = (self._seen - self._started_at) * ms >= MAX_UTTERANCE_S * 1000
            if self._quiet * ms >= self.end_silence_ms or long:
                self.done = True
                events.append("end")
        return events

    @property
    def heard(self) -> bool:
        return self._started_at is not None

    def audio(self) -> np.ndarray:
        """The utterance (with its pre-roll), float32 at 16 kHz."""
        return np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str:
        """float32 mono 16 kHz -> text."""
        ...


class MlxWhisper:
    """Whisper on Apple Silicon (MLX). large-v3-turbo, 4-bit: close to full turbo accuracy at
    ~0.5 GB, which the 8 GB Mac can hold next to the search models."""

    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo-q4") -> None:
        self.model = model
        self._lock = threading.Lock()

    def transcribe(self, audio: np.ndarray) -> str:
        import mlx_whisper

        with self._lock:
            result = mlx_whisper.transcribe(
                audio, path_or_hf_repo=self.model, language="en", fp16=True,
                condition_on_previous_text=False,
            )  # fmt: skip
        return str(result.get("text", "")).strip()


def load_listening(model_dir: Path, whisper: str) -> tuple[VAD, Transcriber] | None:
    """VAD + Whisper when both can run here; None keeps the app text-only."""
    if not (model_dir / VAD_FILE).is_file():
        log.warning("no VAD model in %s: run `make download-stt` for voice input", model_dir)
        return None
    try:
        import mlx_whisper  # noqa: F401  (Apple Silicon only; CUDA gets faster-whisper later)
    except ImportError:
        log.warning("mlx-whisper isn't installed here: voice input is off")
        return None
    return SileroVAD(model_dir / VAD_FILE), MlxWhisper(whisper)
