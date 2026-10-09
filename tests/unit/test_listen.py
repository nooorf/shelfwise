from pathlib import Path

import numpy as np
import pytest

from shelfwise.voice.listen import RATE, Endpointer, SileroVAD
from shelfwise.voice.tts import KokoroSpeech

from ..fakes import FakeVAD, pcm


def feed(endpointer: Endpointer, audio: bytes, step: int = 1000) -> list[tuple[str, float]]:
    """Events with the time (s) of the frame that raised them; odd frame sizes on purpose."""
    events = []
    for i in range(0, len(audio), step):
        events += [
            (e, round((i + step) / 2 / RATE, 1)) for e in endpointer.feed(audio[i : i + step])
        ]
    return events


def test_an_utterance_starts_on_speech_and_ends_after_600_ms_of_quiet() -> None:
    ep = Endpointer(FakeVAD().fresh())
    events = feed(ep, pcm(("silence", 1.0), ("tone", 1.5), ("silence", 2.0)))

    assert [e for e, _ in events] == ["start", "end"]
    assert events[0][1] == pytest.approx(1.0, abs=0.1) and events[1][1] == pytest.approx(
        3.1, abs=0.15
    )
    seconds = len(ep.audio()) / RATE  # 200 ms pre-roll + 1.5 s + the 600 ms of quiet
    assert seconds == pytest.approx(2.3, abs=0.1) and ep.heard and ep.done
    assert ep.feed(pcm(("tone", 1.0))) == []  # finished: ignores more


def test_silence_times_out_and_long_speech_is_cut() -> None:
    quiet = Endpointer(FakeVAD().fresh())
    assert [e for e, _ in feed(quiet, pcm(("silence", 9.0)))] == ["timeout"]
    assert not quiet.heard

    talker = Endpointer(FakeVAD().fresh())
    events = feed(talker, pcm(("tone", 17.0)))
    assert [e for e, _ in events] == ["start", "end"]
    assert events[1][1] == pytest.approx(15.0, abs=0.1)


VAD = Path("data/models/silero/silero_vad.onnx")
TTS = Path("data/models/kokoro")


@pytest.mark.skipif(not VAD.is_file() or not KokoroSpeech.available(TTS), reason="models")
def test_silero_finds_real_speech() -> None:
    voice = KokoroSpeech(TTS).synthesize("Do you have anything like Rebecca?")
    speech = np.interp(
        np.arange(int(len(voice) * 2 / 3)) / RATE, np.arange(len(voice)) / 24_000, voice
    )
    audio = np.concatenate([np.zeros(RATE), speech, np.zeros(RATE)])
    ep = Endpointer(SileroVAD(VAD).fresh())

    events = feed(ep, (audio * 32767).astype("<i2").tobytes())

    assert [e for e, _ in events] == ["start", "end"]
    assert events[0][1] == pytest.approx(1.0, abs=0.25)
