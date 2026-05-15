# Generate REPORT.md - Run from project root
# Usage: powershell -File 10_TMUX/scripts/generate_report.ps1

$d = Get-Date -Format "yyyy-MM-dd"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (Test-Path (Join-Path $root "CLAUDE.md")) {
    $tg = (Get-ChildItem (Join-Path $root "02_CONTENT\telegram\drafts") -Filter "*.md" -EA SilentlyContinue).Count
    $vc = (Get-ChildItem (Join-Path $root "02_CONTENT\vc\drafts") -Filter "*.md" -EA SilentlyContinue).Count
    $res = (Get-ChildItem (Join-Path $root "03_RESEARCH\market") -Filter "*.md" -EA SilentlyContinue).Count
    $out = Join-Path $root "REPORT.md"
    $body = @"
# AI Growth Team Report
Date: $d
Telegram: $tg | VC: $vc | Research: $res
Update 00_MASTER/ and run daily.
"@
    $body | Out-File $out -Encoding UTF8
    Write-Host "Report saved to $out"
} else {
    Write-Host "Run from project root (where CLAUDE.md exists)"
}
