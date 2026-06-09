# One-click install of everything Loomis needs to run its full pipeline on Windows.
#
# Baseline (installed by default — required to meet the project's goals):
#   uv, Node.js + pnpm, ffmpeg, Ollama (+ a default LLM model), and the backend
#   STT (whisperx) / diarization (pyannote) / LLM extras, plus the web deps.
# Only *alternatives* (a different STT/LLM backend) are optional and not installed here.
#
#   ./install.ps1                 # install + set up everything (CPU torch)
#   ./install.ps1 -Gpu            # also install CUDA torch (NVIDIA GPU; much faster STT)
#   ./install.ps1 -SkipLlmModel   # skip the (large) Ollama model pull
param([switch]$SkipLlmModel, [switch]$Gpu)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$LLM_MODEL = 'qwen2.5:7b'   # keep in sync with [llm].model default
$CUDA = 'cu124'            # CUDA wheel index for torch (cu121/cu124); match your driver

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:PATH = "$machine;$user"
}

function Winget-Install($id, $exe) {
  if (Have $exe) { Write-Host "    [ok]   $exe"; return }
  if (-not (Have winget)) { Write-Warning "winget not found — install $exe manually, then re-run"; return }
  Write-Host "    installing $id ..."
  winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent
  Refresh-Path
  if (Have $exe) { Write-Host "    [ok]   $exe" } else { Write-Warning "    $exe still not on PATH — open a new shell and re-run" }
}

Write-Host '==> System tools'
Winget-Install 'astral-sh.uv' 'uv'
Winget-Install 'OpenJS.NodeJS.LTS' 'node'
Winget-Install 'Gyan.FFmpeg' 'ffmpeg'
Winget-Install 'Ollama.Ollama' 'ollama'

if (-not (Have pnpm)) {
  if (Have corepack) { corepack enable; corepack prepare pnpm@latest --activate; Refresh-Path }
  elseif (Have npm) { npm install -g pnpm; Refresh-Path }
}
if (Have pnpm) { Write-Host '    [ok]   pnpm' } else { Write-Warning '    pnpm missing — install Node, then re-run' }

if (-not (Have uv)) { Write-Error 'uv is required and not on PATH. Open a new shell so PATH updates, then re-run.'; exit 1 }

Write-Host '==> Backend (uv sync + STT/diarize/LLM extras)'
Set-Location "$root\backend"
uv sync --extra stt --extra diarize --extra llm

if ($Gpu) {
  Write-Host "==> CUDA torch ($CUDA) — GPU acceleration"
  uv pip install torch torchaudio --index-url "https://download.pytorch.org/whl/$CUDA" --upgrade
  $cuda_ok = uv run python -c "import torch; print(torch.cuda.is_available())"
  Write-Host "    torch.cuda.is_available() = $cuda_ok"
}

if (Have pnpm) {
  Write-Host '==> Frontend (pnpm install)'
  Set-Location "$root\web"
  pnpm install
}

if (Have ollama -and -not $SkipLlmModel) {
  Write-Host "==> LLM model (ollama pull $LLM_MODEL — this is large)"
  try { ollama pull $LLM_MODEL } catch { Write-Warning "    pull failed (is Ollama running?). Run later: ollama pull $LLM_MODEL" }
}

Write-Host ''
Write-Host 'Done.'
Write-Host 'Next: set up the diarization model (HuggingFace token) - README "Getting started", step 2.'
Write-Host 'Then start Loomis:  cd backend; uv run loomis up'
