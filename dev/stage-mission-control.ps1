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
    $taskTarVersion = @(& tar --version)
    if ($LASTEXITCODE -ne 0 -or $taskTarVersion.Count -eq 0) { throw 'Cannot identify the tar implementation.' }
    if ($taskTarVersion[0] -match '^bsdtar\b') {
        # Git archives store path names as UTF-8; bsdtar on Windows otherwise
        # interprets them using the active console code page.
        & tar --options 'hdrcharset=UTF-8' -xf $taskArchive -C $taskStage
    } else {
        & tar -xf $taskArchive -C $taskStage
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot extract committed Mission Control inputs.' }

    # Git archive honors export-ignore and export-subst, so verify the extracted
    # paths and bytes against HEAD before accepting the release staging area.
    $taskObjectFormat = (& git rev-parse --show-object-format).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the Git object format.' }
    $taskHashName = switch ($taskObjectFormat) {
        'sha1' { [Security.Cryptography.HashAlgorithmName]::SHA1 }
        'sha256' { [Security.Cryptography.HashAlgorithmName]::SHA256 }
        default { throw "Unsupported Git object format: $taskObjectFormat" }
    }
    $taskTreeProcess = [Diagnostics.Process]::new()
    $taskTreeOutput = [IO.MemoryStream]::new()
    try {
        $taskTreeProcess.StartInfo.FileName = 'git'
        $taskTreeProcess.StartInfo.WorkingDirectory = $taskRepo
        $taskTreeProcess.StartInfo.UseShellExecute = $false
        $taskTreeProcess.StartInfo.RedirectStandardOutput = $true
        $taskTreeProcess.StartInfo.RedirectStandardError = $true
        foreach ($taskArg in (@('ls-tree', '-r', '-z', '--full-tree', 'HEAD', '--') + $taskInputs)) {
            [void]$taskTreeProcess.StartInfo.ArgumentList.Add($taskArg)
        }
        [void]$taskTreeProcess.Start()
        $taskTreeError = $taskTreeProcess.StandardError.ReadToEndAsync()
        $taskTreeProcess.StandardOutput.BaseStream.CopyTo($taskTreeOutput)
        $taskTreeProcess.WaitForExit()
        $taskErrorText = $taskTreeError.GetAwaiter().GetResult()
        if ($taskTreeProcess.ExitCode -ne 0) { throw "Cannot inspect committed release inputs: $taskErrorText" }
        $taskTreeText = [Text.UTF8Encoding]::new($false, $true).GetString($taskTreeOutput.ToArray())
    } finally {
        $taskTreeOutput.Dispose()
        $taskTreeProcess.Dispose()
    }
    $taskExpected = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($taskEntry in $taskTreeText.Split([char]0, [StringSplitOptions]::RemoveEmptyEntries)) {
        $taskTab = $taskEntry.IndexOf("`t")
        if ($taskTab -lt 0) { throw 'Unexpected committed release input entry.' }
        $taskFields = $taskEntry.Substring(0, $taskTab).Split([char]' ')
        $taskRelative = $taskEntry.Substring($taskTab + 1)
        if ($taskFields.Count -ne 3 -or $taskFields[0] -notin @('100644', '100755') -or $taskFields[1] -ne 'blob') {
            throw "Unsupported committed release input type: $taskRelative"
        }
        if (-not $taskExpected.Add($taskRelative)) { throw "Duplicate committed release input: $taskRelative" }
        $taskFilePath = Join-Path $taskStage $taskRelative
        if (-not (Test-Path -LiteralPath $taskFilePath -PathType Leaf)) {
            throw "Release staging omitted committed input: $taskRelative"
        }
        if ((Get-Item -LiteralPath $taskFilePath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Release staging input is a symbolic link: $taskRelative"
        }
        $taskFile = [IO.File]::OpenRead($taskFilePath)
        $taskHash = [Security.Cryptography.IncrementalHash]::CreateHash($taskHashName)
        try {
            $taskHeader = [Text.Encoding]::ASCII.GetBytes("blob $($taskFile.Length)`0")
            $taskHash.AppendData($taskHeader)
            $taskBuffer = [byte[]]::new(65536)
            while (($taskRead = $taskFile.Read($taskBuffer, 0, $taskBuffer.Length)) -gt 0) {
                $taskHash.AppendData($taskBuffer, 0, $taskRead)
            }
            $taskActualHash = [Convert]::ToHexString($taskHash.GetHashAndReset()).ToLowerInvariant()
        } finally {
            $taskHash.Dispose()
            $taskFile.Dispose()
        }
        if ($taskActualHash -ne $taskFields[2]) { throw "Release staging changed committed input: $taskRelative" }
    }
    $taskActualCount = 0
    foreach ($taskItem in Get-ChildItem -LiteralPath $taskStage -Force -Recurse) {
        $taskRelative = [IO.Path]::GetRelativePath($taskStage, $taskItem.FullName).Replace([IO.Path]::DirectorySeparatorChar, [char]'/')
        if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Release staging contains a symbolic link: $taskRelative"
        }
        if (-not $taskItem.PSIsContainer) {
            if (-not $taskExpected.Contains($taskRelative)) {
                throw "Release staging contains an unexpected input: $taskRelative"
            }
            $taskActualCount++
        }
    }
    if ($taskActualCount -ne $taskExpected.Count) {
        throw 'Release staging omitted one or more distinct committed input paths.'
    }
} finally {
    if (Test-Path -LiteralPath $taskArchive) { Remove-Item -LiteralPath $taskArchive -ErrorAction Stop }
}
