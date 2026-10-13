# 5. Lip-sync from the playing audio, in the browser

**Status:** accepted, 2026-10-08; measured 2026-10-11

## Context

The live session has a talking avatar (VRM, three.js). The reference project this started from synthesised the whole reply, ran Rhubarb on the WAV for mouth shapes, then played it: the full synthesis plus the analysis sat in front of the first word. Shelfwise streams speech sentence by sentence, so the first sentence plays while the LLM is still writing the third.

## Decision

- The avatar reads the **same Web Audio graph that plays the speech**: an AnalyserNode after the playback queue. Each frame, loudness opens the mouth and the balance of energy across three formant bands picks the vowel shape (VRM's `aa ih ou ee oh`), smoothed with a fast attack and slower release.
- Two hard rules: **audio never waits for the avatar**, and **its sync is measured** (`make measure`).
- Fallback to an orb on no WebGL, reduced motion, a missing or failed model, or under 20 fps.
- Rejected: Rhubarb on the whole reply (delays audio); Rhubarb per sentence (still delays); TTS word timings → phonemes (Kokoro's ONNX export has no timing side channel; a V2 option).

## Consequences

- Zero added delay by construction, and in sync by construction: the mouth moves on the samples being played. When playback stops (barge-in), the mouth closes on that frame.
- Vowels look right; consonants are approximate (no lip closure for /p b m/).
- Measured on the 8 GB M2 with `make measure` (20 spoken questions each way, order balanced): the avatar adds +0.36 s to the time to first audio on average, 95% CI −1.75 to +2.42 s, so no measurable cost next to run-to-run noise. The mouth opens 4 ms after the sound starts (median; 95% within 63 ms late); 17 of 20 answers are inside ITU-R BT.1359's detectability limit for sound leading the picture (45 ms), the other 3 at 50–65 ms; 59 fps while speaking (the slowest 5% of answers 55 fps); first frame 0.73 s after opening the page, the model itself 0.1 s.
- The A/V offset is measured in the page (the render loop's frame time vs the audio clock's output timestamps), not with a camera, so the display's own latency isn't in it.
