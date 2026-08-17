[CmdletBinding()]
param(
    [string]$PythonExecutable = "py",
    [string]$PythonVersionArgument = "-3.12",
    [switch]$SkipDeepSoloPreflight
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSCommandPath
$project = (Resolve-Path (Join-Path $here "..\..")).Path
$venv = Join-Path $project ".venv-gpu"

& $PythonExecutable $PythonVersionArgument -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version"
if (-not (Test-Path $venv)) { & $PythonExecutable $PythonVersionArgument -m venv $venv }
$pythonExe = Join-Path $venv "Scripts\python.exe"

& $pythonExe -m pip install --upgrade pip wheel setuptools
& $pythonExe -m pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
& $pythonExe -m pip install -r (Join-Path $here "requirements-gpu.txt")

if (Test-Path (Join-Path $here ".env")) {
    Get-Content (Join-Path $here ".env") | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process") }
    }
}

& $pythonExe -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print(torch.cuda.get_device_name(0)); print(torch.cuda.get_device_properties(0).total_memory // 1024 // 1024, 'MiB')"

if (-not $SkipDeepSoloPreflight) {
    $missing = @()
    foreach ($name in @("DEEPSOLO_HOME", "DEEPSOLO_CHECKPOINT", "PARSEQ_CHECKPOINT", "WP04_DEEPSOLO_COMMAND", "WP04_CHUNKFORMER_COMMAND", "WP04_RFDETR_COMMAND")) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        $isCommand = $name -like "WP04_*_COMMAND"
        if ([string]::IsNullOrWhiteSpace($value) -or (-not $isCommand -and -not (Test-Path $value))) { $missing += $name }
    }
    if ($missing) { throw "DeepSolo/PARSeq local artifacts missing: $($missing -join ', '). Fill deploy\windows-rtx5070ti\.env then rerun." }
}

$chunkformerPath = & $pythonExe -c "from huggingface_hub import snapshot_download; print(snapshot_download(repo_id='khanhld/chunkformer-ctc-large-vie', revision='311fc03558a895dc2b32957f2fb4236c7fb1455b'))"
$files = Get-ChildItem -LiteralPath $chunkformerPath -Recurse -File | ForEach-Object {
    [ordered]@{ path = $_.FullName.Substring($chunkformerPath.Length).TrimStart('\\', '/'); sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant() }
}
[ordered]@{
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    asr = [ordered]@{ repository = "khanhld/chunkformer-ctc-large-vie"; revision = "311fc03558a895dc2b32957f2fb4236c7fb1455b"; files = @($files) }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $here "checkpoints.lock.json") -Encoding UTF8
Write-Host "GPU environment ready: $venv"
