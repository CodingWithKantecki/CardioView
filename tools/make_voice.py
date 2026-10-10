"""Render the session voice lines once with Kokoro 82M from Hugging Face. The WAV files are committed,
so the booth needs neither the model nor the internet.

    py -3.12 -m venv .venv-voice                      (kokoro needs Python 3.10 to 3.12)
    .venv-voice/Scripts/pip install -r tools/requirements-voice.txt       (Mac, Linux: .venv-voice/bin/pip)
    .venv-voice/Scripts/python tools/make_voice.py

Model: hexgrad/Kokoro-82M on Hugging Face, Apache 2.0. Voice af_heart, 24 kHz mono.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

OUT = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "voice"
RATE = 24000
VOICE = "af_heart"
LINES = {
    "get_ready": "Hold still while we get a clean signal.",
    "rest": "Sit still and breathe normally.",
    "breathe": "Now breathe with the ring.",
    "in": "In.",
    "out": "Out.",
    "squats": "Squats. Keep going.",
    "recover": "Stop. Stand still and catch your breath.",
    "done": "All done. Here is your heart.",
    "stopped": "Session stopped and deleted.",
}


def render(pipe: KPipeline, text: str) -> np.ndarray:
    parts = []
    for result in pipe(text, voice=VOICE):
        audio = result.audio
        parts.append(audio.cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio))
    return np.concatenate(parts).astype(np.float32)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pipe = KPipeline(lang_code="a")   # American English
    for key, text in LINES.items():
        audio = render(pipe, text)
        sf.write(OUT / f"{key}.wav", audio, RATE, subtype="PCM_16")
        print(f"{key + '.wav':<14} {len(audio) / RATE:4.1f} s  {text}")


if __name__ == "__main__":
    main()
