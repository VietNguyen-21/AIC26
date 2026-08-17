[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$RunDir,
    [Parameter(Mandatory)] [string]$PreprocessRunId,
    [Parameter(Mandatory)] [string]$ArtifactSetId,
    [Parameter(Mandatory)] [string]$FramesJson,
    [Parameter(Mandatory)] [string]$AudioJson
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSCommandPath
$project = (Resolve-Path (Join-Path $here "..\..")).Path
$pythonExe = Join-Path $project ".venv-gpu\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { throw "Run .\setup.ps1 first." }

& $pythonExe -m wp04.cli preprocess --run-dir $RunDir --preprocess-run-id $PreprocessRunId --artifact-set-id $ArtifactSetId --frames-json $FramesJson --audio-json $AudioJson --config (Join-Path $project "configs\default.yaml")
& $pythonExe -m wp04.cli validate --run-dir $RunDir --preprocess-run-id $PreprocessRunId --artifact-set-id $ArtifactSetId --frames-json $FramesJson
