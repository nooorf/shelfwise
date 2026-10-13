"""Text-to-speech behind one interface: Kokoro-82M through ONNX Runtime
(int8, ~90 MB, about 8x faster than real time on the M2's CPU), a sentence at a time so the
first sentence plays while the next is made.

Model files are downloaded by `make download-tts` into `data/models/kokoro` (not in git).
"""

import io
import logging
import re
import threading
import wave
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

MODEL_FILE = "kokoro-v1.0.int8.onnx"
VOICES_FILE = "voices-v1.0.bin"
MIN_SENTENCE = (
    12  # chars: shorter pieces ("Dr.") join the next; a short first sentence plays sooner
)

# A sentence ends at . ! ? or an ellipsis, with any closing quote or bracket kept on it, before
# whitespace and a capital, digit or opening quote.
_END = "[.!?\u2026]"
_CLOSE = '["\u201d\u2019)]'
_SENTENCE_END = re.compile(rf"(?:(?<={_END})|(?<={_END}{_CLOSE}))\s+(?=[A-Z0-9\"\u201c\u2018(])")


class Speech(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> np.ndarray:
        """Mono float32 samples in [-1, 1] at `sample_rate`."""
        ...


def sentences(text: str) -> list[str]:
    """`text` split where sentences end, short pieces joined to the next."""
    pieces = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    out: list[str] = []
    carry = ""
    for piece in pieces:
        carry = f"{carry} {piece}".strip()
        if len(carry) >= MIN_SENTENCE:
            out.append(carry)
            carry = ""
    if carry:
        if out and len(carry) < MIN_SENTENCE:
            out[-1] = f"{out[-1]} {carry}"
        else:
            out.append(carry)
    return out


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """16-bit PCM WAV, which every browser's decodeAudioData reads."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


class KokoroSpeech:
    """Kokoro v1.0, loaded on first use. One synthesis at a time (one ONNX session)."""

    sample_rate = 24_000

    def __init__(self, model_dir: Path, voice: str = "af_heart", speed: float = 1.0) -> None:
        self.model_dir = model_dir
        self.voice = voice
        self.speed = speed
        self._model = None
        self._lock = threading.Lock()

    @staticmethod
    def available(model_dir: Path) -> bool:
        return (model_dir / MODEL_FILE).is_file() and (model_dir / VOICES_FILE).is_file()

    def synthesize(self, text: str) -> np.ndarray:
        with self._lock:
            if self._model is None:
                from kokoro_onnx import Kokoro  # heavy import: only when speech is used

                self._model = Kokoro(
                    str(self.model_dir / MODEL_FILE), str(self.model_dir / VOICES_FILE)
                )
            samples, rate = self._model.create(
                text, voice=self.voice, speed=self.speed, lang="en-us"
            )
        if rate != self.sample_rate:
            raise ValueError(f"Kokoro returned {rate} Hz, expected {self.sample_rate}")
        return np.asarray(samples, dtype=np.float32)


def load_speech(model_dir: Path, voice: str) -> Speech | None:
    """Kokoro if its files are there; None (the app stays text-only) otherwise."""
    if KokoroSpeech.available(model_dir):
        return KokoroSpeech(model_dir, voice)
    log.warning("no TTS model in %s: run `make download-tts` for speech", model_dir)
    return None
