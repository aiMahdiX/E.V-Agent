"""Sample alignment helpers for audio. Moved here so vad.py stays dependency-free."""
from __future__ import annotations

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2   # s16le = 2 bytes


def ms_to_bytes(ms: int) -> int:
    """Bytes for a duration at the fixed 16 kHz mono s16 config."""
    return int(SAMPLE_RATE * (ms / 1000.0) * CHANNELS * SAMPLE_WIDTH)