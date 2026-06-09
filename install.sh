#!/usr/bin/env bash
# One-click install of everything Loomis needs to run its full pipeline.
#
# Baseline (installed by default — required to meet the project's goals):
#   uv, Node.js + pnpm, ffmpeg, Ollama (+ a default LLM model), and the backend
#   STT (whisperx) / diarization (pyannote) / LLM extras, plus the web deps.
# Only *alternatives* (a different STT/LLM backend) are optional and not installed here.
#
#   ./install.sh                 # install + set up everything (CPU torch)
#   ./install.sh --gpu           # also install CUDA torch (NVIDIA GPU; much faster STT)
#   ./install.sh --skip-llm-model  # skip the (large) Ollama model pull
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLM_MODEL="qwen2.5:7b"   # keep in sync with [llm].model default
CUDA="cu124"             # CUDA wheel index for torch (cu121/cu124); match your driver
SKIP_LLM_MODEL=0
GPU=0
for arg in "$@"; do
  case "$arg" in
    --skip-llm-model) SKIP_LLM_MODEL=1 ;;
    --gpu) GPU=1 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

# Pick a system package manager for ffmpeg / node / ollama.
PM=""
if have brew; then PM=brew
elif have apt-get; then PM=apt
elif have dnf; then PM=dnf
fi

pm_install() {  # pm_install <command-to-check> <brew-pkg> <apt-pkg> <dnf-pkg>
  local exe=$1 brew_pkg=$2 apt_pkg=$3 dnf_pkg=$4
  if have "$exe"; then echo "    [ok]   $exe"; return; fi
  case "$PM" in
    brew) brew install "$brew_pkg" ;;
    apt)  sudo apt-get update -y && sudo apt-get install -y "$apt_pkg" ;;
    dnf)  sudo dnf install -y "$dnf_pkg" ;;
    *)    echo "    [miss] $exe — no supported package manager; install it manually"; return ;;
  esac
  have "$exe" && echo "    [ok]   $exe" || echo "    [warn] $exe still missing"
}

echo "==> System tools (${PM:-none detected})"
if ! have uv; then
  if have brew; then brew install uv; else curl -LsSf https://astral.sh/uv/install.sh | sh; fi
  # shellcheck disable=SC1090
  [[ -f "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env" || true
fi
have uv && echo "    [ok]   uv" || { echo "ERROR: uv install failed — see https://github.com/astral-sh/uv"; exit 1; }

pm_install node nodejs nodejs nodejs
pm_install ffmpeg ffmpeg ffmpeg ffmpeg
if ! have ollama; then
  if have brew; then brew install ollama; else curl -fsSL https://ollama.com/install.sh | sh; fi
fi
have ollama && echo "    [ok]   ollama" || echo "    [warn] ollama missing — https://ollama.com"

if ! have pnpm; then
  if have corepack; then corepack enable && corepack prepare pnpm@latest --activate
  elif have npm; then npm install -g pnpm; fi
fi
have pnpm && echo "    [ok]   pnpm" || echo "    [warn] pnpm missing — install Node first"

echo "==> Backend (uv sync + STT/diarize/LLM extras)"
cd "$ROOT/backend"
uv sync --extra stt --extra diarize --extra llm

if [[ "$GPU" == "1" ]]; then
  echo "==> CUDA torch ($CUDA) — GPU acceleration"
  uv pip install torch torchaudio --index-url "https://download.pytorch.org/whl/$CUDA" --upgrade
  echo "    torch.cuda.is_available() = $(uv run python -c 'import torch; print(torch.cuda.is_available())')"
fi

if have pnpm; then
  echo "==> Frontend (pnpm install)"
  cd "$ROOT/web"
  pnpm install
fi

if have ollama && [[ "$SKIP_LLM_MODEL" == "0" ]]; then
  echo "==> LLM model (ollama pull $LLM_MODEL — this is large)"
  ollama pull "$LLM_MODEL" || echo "    pull failed (is Ollama running?). Run later: ollama pull $LLM_MODEL"
fi

cat <<'EOF'

Done.
Next: set up the diarization model (HuggingFace token) — README "Getting started", step 2.
Then start Loomis:  cd backend && uv run loomis up
EOF
