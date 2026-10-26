# Copy the repo packages into the Worker vendor tree.
# Extra files that exist only under worker/python_modules are left in place.

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$vendor = Join-Path $root 'worker\python_modules'
$synced = @()

$liveSource = Join-Path $root 'src\live_win_prob'
$liveDest = Join-Path $vendor 'live_win_prob'
if (-not (Test-Path -LiteralPath $liveSource -PathType Container)) {
    throw "Source package is missing: $liveSource"
}
if (-not (Test-Path -LiteralPath $liveDest -PathType Container)) {
    throw "Worker package directory is missing: $liveDest"
}
Copy-Item -Path (Join-Path $liveSource '*') -Destination $liveDest -Force -Recurse
$synced += 'live_win_prob'

$msSource = Join-Path $root 'src\ms_win_prob'
$msDest = Join-Path $vendor 'ms_win_prob'
if (Test-Path -LiteralPath $msDest -PathType Container) {
    if (-not (Test-Path -LiteralPath $msSource -PathType Container)) {
        throw "Source package is missing: $msSource"
    }
    Copy-Item -Path (Join-Path $msSource '*') -Destination $msDest -Force -Recurse
    $synced += 'ms_win_prob'
}

Write-Output ("Synced {0} into worker/python_modules." -f ($synced -join ', '))
