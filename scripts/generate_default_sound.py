#!/usr/bin/env python3
"""Generate the plugin's original, deterministic timer sound."""

import math
import struct
import wave
from pathlib import Path

RATE = 24_000
AMPLITUDE = 0.24
TONES = ((659.25, 0.16), (783.99, 0.24))
GAP_SECONDS = 0.035
OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "timer-complete.wav"


def tone(frequency: float, seconds: float) -> bytes:
    count = round(RATE * seconds)
    fade = round(RATE * 0.018)
    frames = bytearray()
    for index in range(count):
        envelope = min(1.0, index / fade, (count - 1 - index) / fade)
        sample = AMPLITUDE * envelope * math.sin(2 * math.pi * frequency * index / RATE)
        frames.extend(struct.pack("<h", round(32767 * sample)))
    return bytes(frames)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    silence = b"\0\0" * round(RATE * GAP_SECONDS)
    audio = silence.join(tone(frequency, seconds) for frequency, seconds in TONES)
    with wave.open(str(OUTPUT), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(audio)


if __name__ == "__main__":
    main()
