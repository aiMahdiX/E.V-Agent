#!/usr/bin/env bash
# E.V. Phase 2 — Voice: install STT/TTS deps + download the Persian Vosk model.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Installing voice Python deps (vosk, webrtcvad, edge-tts) into .venv"
.venv/bin/python3 -m pip install vosk webrtcvad-wheels edge-tts

echo "==> Ensuring data/models"
mkdir -p data/models

if [ ! -d data/models/vosk-model-small-fa-0.5 ]; then
  echo "==> Downloading Persian Vosk model (~59 MB)…"
  curl -fSL --retry 3 -o /tmp/vosk-fa.zip \
    https://alphacephei.com/vosk/models/vosk-model-small-fa-0.5.zip
  unzip -o -q /tmp/vosk-fa.zip -d data/models
  rm -f /tmp/vosk-fa.zip
else
  echo "==> Persian Vosk model already present"
fi

echo
echo "Setup complete. Voice deps installed and model ready."
echo "Run voice session:   .venv/bin/python3 -m ev.voice  (or via main.py)"
echo "Test TTS:            python3 -c \"from models.tts import test_tts; test_tts()\""