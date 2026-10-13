#!/usr/bin/env bash
# E.V. setup: inspect hardware and configure local Ollama or a cloud provider.
set -euo pipefail
cd "$(dirname "$0")"

MODEL=""
SETUP_MODE="auto"
CLOUD_PROVIDER=""
case "${1:-}" in
  --help|-h)
    printf 'Usage: %s [--cloud [provider]|--local|--manual [model]|--recommended|model]\n' "$0"
    exit 0
    ;;
  --cloud) SETUP_MODE="cloud"; CLOUD_PROVIDER="${2:-}" ;;
  --local) SETUP_MODE="local" ;;
  --manual) SETUP_MODE="local"; MODEL="${2:-qwen3:4b}" ;;
  --recommended|"") ;;
  *) SETUP_MODE="local"; MODEL="$1" ;;
esac

finish_setup() {
  echo
  echo "Setup complete. Run:  .venv/bin/python3 main.py"
  echo "Edit .env to override configuration values; see .env.example."
  if [[ -t 0 && -t 1 ]]; then
    read -r -p "Configure optional Voice & Live features now? [y/N] " VOICE_SETUP
    case "$VOICE_SETUP" in
      [Yy]|[Yy][Ee][Ss]) .venv/bin/python3 -m voice.setup ;;
      *) echo "Voice setup skipped. Run /voice setup later from E.V." ;;
    esac
  fi
}

echo "==> Creating virtualenv (.venv)"
python3 -m venv .venv
.venv/bin/python3 -m pip install --upgrade pip >/dev/null
echo "==> Installing base application requirements"
.venv/bin/python3 -m pip install -r requirements.txt

if [[ "$SETUP_MODE" == "cloud" ]]; then
  if [[ -n "$CLOUD_PROVIDER" ]]; then
    .venv/bin/python3 -m core.provider_setup "$CLOUD_PROVIDER"
  else
    .venv/bin/python3 -m core.provider_setup
  fi
  finish_setup
  exit 0
fi

if [[ -z "$MODEL" ]]; then
  .venv/bin/python3 -m voice.hardware
  MODEL="$(.venv/bin/python3 -m voice.hardware --model)"
  if [[ "$SETUP_MODE" == "auto" && -t 0 && -t 1 ]]; then
    DEFAULT_MODE="L"
    [[ -n "$MODEL" ]] || DEFAULT_MODE="C"
    echo "Setup choices: [L]ocal model, [C]loud provider, [M]anual local model"
    read -r -p "Choose setup mode [$DEFAULT_MODE]: " MODE_CHOICE
    MODE_CHOICE="${MODE_CHOICE:-$DEFAULT_MODE}"
    case "$MODE_CHOICE" in
      [Cc])
        .venv/bin/python3 -m core.provider_setup
        finish_setup
        exit 0
        ;;
      [Mm])
        read -r -p "Enter an Ollama model name (blank cancels): " MODEL
        [[ -n "$MODEL" ]] || exit 1
        ;;
      *)
        if [[ -z "$MODEL" ]]; then
          echo "No local model is recommended. Choose --cloud or --manual <model>."
          exit 1
        fi
        ;;
    esac
  elif [[ -z "$MODEL" ]]; then
    echo "No local model is recommended. Run ./setup.sh --cloud or --manual <model>."
    exit 1
  fi
fi

echo "==> Ensuring data dirs"
mkdir -p data/logs data/memory

echo "==> Starting Ollama server if not running"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it from https://ollama.com/download,"
  echo "or configure a cloud provider separately with explicit consent."
  exit 1
fi
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >data/logs/ollama.log 2>&1 &
  for i in $(seq 1 30); do
    curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "==> Pulling model: $MODEL"
ollama pull "$MODEL"
finish_setup
