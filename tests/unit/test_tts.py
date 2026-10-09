import io
import wave
from pathlib import Path

import numpy as np
import pytest

from shelfwise.voice.tts import KokoroSpeech, load_speech, sentences, wav_bytes


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Four on the shelf now. The first is the darkest!",
         ["Four on the shelf now.", "The first is the darkest!"]),
        ("Ok. Want something shorter?", ["Ok. Want something shorter?"]),  # "Ok." is too short
        ("It's “Rebecca.” Then Dr. No is 200 pages.",
         ["It's “Rebecca.”", "Then Dr. No is 200 pages."]),
        ("No full stop at the end", ["No full stop at the end"]),
        ("  ", []),
    ],
)  # fmt: skip
def test_sentences(text: str, expected: list[str]) -> None:
    assert sentences(text) == expected


def test_wav_is_16_bit_mono_and_clipped() -> None:
    clip = wav_bytes(np.array([0.0, 0.5, 2.0, -2.0], dtype=np.float32), 24_000)
    with wave.open(io.BytesIO(clip)) as w:
        frames = np.frombuffer(w.readframes(4), dtype="<i2")
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (24_000, 2, 1)
    assert frames.tolist() == [0, 16383, 32767, -32767]


def test_no_model_files_means_no_speech(tmp_path: Path) -> None:
    assert load_speech(tmp_path, "af_heart") is None


MODEL_DIR = Path("data/models/kokoro")


@pytest.mark.skipif(not KokoroSpeech.available(MODEL_DIR), reason="run `make download-tts`")
def test_kokoro_speaks() -> None:
    samples = KokoroSpeech(MODEL_DIR).synthesize("Four books on the shelf now.")
    seconds = len(samples) / KokoroSpeech.sample_rate
    assert samples.dtype == np.float32 and 0.8 < seconds < 5
    assert 0.01 < float(np.abs(samples).max()) <= 1.0
