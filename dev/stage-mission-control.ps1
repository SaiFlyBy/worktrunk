# Stage only committed integration inputs for cargo-dist release archives.
$ErrorActionPreference = 'Stop'
$taskRepo = (& git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $taskRepo) { throw 'Cannot identify the Git repository.' }
Set-Location -LiteralPath $taskRepo
$taskInputs = @('mission-control-template', 'INTEGRATION_PROVENANCE.md', 'docs/third_party/pstack/LICENSE')
$taskIndexEntries = @(& git ls-files -v --full-name -- @taskInputs)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect release input index flags.' }
foreach ($taskEntry in $taskIndexEntries) {
    if ($taskEntry.Length -lt 3 -or $taskEntry[1] -ne ' ') { throw 'Unexpected release input index entry.' }
    $taskFlag = $taskEntry[0]
    if ([char]::IsLower($taskFlag) -or [char]::ToUpperInvariant($taskFlag) -eq 'S') {
        throw 'Release inputs have assume-unchanged or skip-worktree index flags; clear them before staging.'
    }
}
& git diff --quiet HEAD -- @taskInputs
if ($LASTEXITCODE -ne 0) { throw 'Mission Control release inputs have uncommitted changes; commit them before staging.' }
foreach ($taskRequired in @('mission-control-template/TEMPLATE.json', 'mission-control-template/tools/mc.py',
        'mission-control-template/tools/wt_mission.py', 'INTEGRATION_PROVENANCE.md', 'docs/third_party/pstack/LICENSE')) {
    & git cat-file -e "HEAD:$taskRequired"
    if ($LASTEXITCODE -ne 0) { throw "Required committed release input is missing: $taskRequired" }
}
$taskTarget = Join-Path $taskRepo 'target'
$taskParent = Join-Path $taskTarget 'flyby-dist'
$taskStage = Join-Path $taskParent 'flyby-integration'
foreach ($taskPath in @($taskTarget, $taskParent)) {
    if (Test-Path -LiteralPath $taskPath) {
        if ((Get-Item -LiteralPath $taskPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Release staging parent is a symbolic link: $taskPath"
        }
    }
}
if (Test-Path -LiteralPath $taskStage) { throw "Release staging destination already exists: $taskStage" }
New-Item -ItemType Directory -Path $taskParent -Force | Out-Null
New-Item -ItemType Directory -Path $taskStage -ErrorAction Stop | Out-Null
$taskArchive = Join-Path $taskParent ('mission-control-' + [guid]::NewGuid().ToString('N') + '.tar')
try {
    & git -c core.autocrlf=false -c core.eol=lf archive --format=tar "--output=$taskArchive" HEAD -- @taskInputs
    if ($LASTEXITCODE -ne 0) { throw 'Cannot archive committed Mission Control inputs.' }
    & tar -xf $taskArchive -C $taskStage
    if ($LASTEXITCODE -ne 0) { throw 'Cannot extract committed Mission Control inputs.' }
} finally {
    if (Test-Path -LiteralPath $taskArchive) { Remove-Item -LiteralPath $taskArchive -ErrorAction Stop }
}
