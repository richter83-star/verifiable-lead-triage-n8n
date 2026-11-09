# Runs the kit's workflow in an isolated n8n (its own user folder; your real n8n is not touched),
# twice, in mock mode, then verifies the audit log and checks that tampering is caught.
# Prints one JSON line with the results; exit code 0 = all checks passed.
param(
  [string]$Python = "python",
  [string]$Sandbox = (Join-Path ([IO.Path]::GetTempPath()) "n8n-kit-test")
)
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
if (Test-Path $Sandbox) { Remove-Item $Sandbox -Recurse -Force }
New-Item -ItemType Directory -Force "$Sandbox\audit" | Out-Null
$log = "$Sandbox\audit\lead-triage.jsonl"
$env:N8N_USER_FOLDER = $Sandbox
$env:AUDIT_LOG_PATH = $log
$env:AUDIT_MOCK_LLM = "true"
$env:N8N_RESTRICT_FILE_ACCESS_TO = "$Sandbox\audit"
$env:N8N_BLOCK_ENV_ACCESS_IN_NODE = "false"
$env:N8N_DIAGNOSTICS_ENABLED = "false"

$result = [ordered]@{ n8n = (n8n --version 2>$null | Select-Object -First 1) }
n8n import:workflow --input "$root\kit\workflow\verifiable-lead-triage.json" *> "$Sandbox\import.log"
$result.import_ok = ($LASTEXITCODE -eq 0)
$runs = @()
foreach ($i in 1..2) {
  $out = n8n execute --id vltAuditKit00001 --rawOutput 2> "$Sandbox\run$i.err"
  $runs += [ordered]@{ exit = $LASTEXITCODE; out = (($out | Out-String).Trim()) }
}
$result.runs = $runs
$result.log_exists = Test-Path $log
if ($result.log_exists) {
  $v = & $Python "$root\kit\verifier\verify_audit.py" $log --json | ConvertFrom-Json
  $result.entries = $v.entries
  $result.intact = $v.intact
  $tampered = "$Sandbox\audit\tampered.jsonl"
  (Get-Content $log -Raw) -replace '"label":"hot"', '"label":"cold"' | Set-Content $tampered -NoNewline -Encoding utf8
  & $Python "$root\kit\verifier\verify_audit.py" $tampered --json | Out-Null
  $result.tamper_detected = ($LASTEXITCODE -eq 1)
}
$result.passed = [bool]($result.import_ok -and $result.log_exists -and $result.intact -and $result.entries -eq 6 -and $result.tamper_detected -and ($runs | Where-Object { $_.exit -ne 0 }).Count -eq 0)
$result | ConvertTo-Json -Depth 5 -Compress
if ($result.passed) { exit 0 } else { exit 1 }
