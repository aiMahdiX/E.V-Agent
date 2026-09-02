"""Phase 2 offline smoke: VAD, Vosk STT model load, WakeWord matching."""
import json, struct, sys
sys.path.insert(0, '.')

from voice.vad import EnergyVAD
from voice.stt import find_model, VoskSTT
from voice.wakeword import WakeWord

# 1) VAD energy: silence -> False, loud -> True
silence = bytes(1600)  # 100 ms @16k s16 all-zero
noise = b"".join(struct.pack("<h", 4000 if i % 2 else -4000)
                 for i in range(800))
vad = EnergyVAD(frame_ms=20)
for _ in range(5):
    vad.feed(silence)
print("VAD silence active =", vad.active)

vad2 = EnergyVAD(frame_ms=20)
loud = vad2.feed(noise)
print("VAD noise active =", loud)
assert loud, "VAD should detect loud noise"
print("VAD OK")

# 2) Vosk STT loads the Persian model
model = find_model()
print("model found:", model)
stt = VoskSTT()
print("STT ready, sr =", stt.sample_rate)

# 3) Wake word matching
w = WakeWord(words=("e.v", "ای وی"))
for t in ["hello", "ای وی", "ای وی صبح بخیر", "سلام"]:
    print(f"wake({t!r}) -> {w.is_wake(t)}")
assert w.is_wake("ای وی"), "wake for 'ای وی'"
assert not w.is_wake("سلام"), "no wake for 'سلام'"
assert not w.is_wake("hello")
print("WakeWord OK")