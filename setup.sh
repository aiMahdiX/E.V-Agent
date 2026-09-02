#!/usr/bin/env bash
# E.V. setup: create venv, bootstrap pip, ensure Ollama, pull the default model.
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${1:-qwen3:4b}"

echo "==> Creating virtualenv (.venv)"
python3 -m venv .venv
.venv/bin/python3 -m pip install --upgrade pip >/dev/null

echo "==> Ensuring data dirs"
mkdir -p data/logs data/memory

echo "==> Starting Ollama server if not running"
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >data/logs/ollama.log 2>&1 &
  for i in $(seq 1 30); do
    curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "==> Pulling model: $MODEL"
ollama pull "$MODEL"

echo
echo "Setup complete. Run:  .venv/bin/python3 main.py"
echo "To change the default model, edit 'default' in config.json "
echo "(fast/main/vision are set under ollama.models)."
