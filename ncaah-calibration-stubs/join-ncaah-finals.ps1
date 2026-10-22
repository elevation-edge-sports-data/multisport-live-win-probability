# Join final scores onto the local NCAAH calibration stubs in this folder.
#
# Pass a CSV or JSON file with event_ticker or game_id, home_score,
# away_score, and final_status. A row is applied only when final_status
# is "final". The matching stub then gets those scores and status "final".
#
# The resulting files can later be copied by hand into
# data/calibration/ncaah/ once you are satisfied with the mapping.
# This script does not copy them, and it writes only inside this folder.
#
# Example:
#   .\ncaah-calibration-stubs\join-ncaah-finals.ps1 .\finals.csv
#   event_ticker,home_score,away_score,final_status
#   KXNCAAHGAME-26OCT22BUCON,4,2,final

#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Results
)

$ErrorActionPreference = 'Stop'

$stubDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$stubPrefix = $stubDir.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar

function Assert-InsideStubDir {
    param([string] $Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($stubPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside the stubs folder: $full"
    }
}

function Convert-Score {
    param([string] $Text)
    $number = 0
    $parsed = [int]::TryParse(
        $Text,
        [Globalization.NumberStyles]::Integer,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$number
    )
    if (-not $parsed -or $number -lt 0) {
        return $null
    }
    return $number
}

function Get-JsonField {
    param($Element, [string] $Name)
    foreach ($property in $Element.EnumerateObject()) {
        if (-not $property.Name.Equals($Name, [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $value = $property.Value
        if ($value.ValueKind -eq [System.Text.Json.JsonValueKind]::String) {
            return [string]$value.GetString()
        }
        if ($value.ValueKind -eq [System.Text.Json.JsonValueKind]::Number) {
            return [string]$value.GetRawText()
        }
        if ($value.ValueKind -eq [System.Text.Json.JsonValueKind]::Null) {
            return ''
        }
        return $null
    }
    return $null
}

function Convert-ResultElement {
    param($Element)
    if ($Element.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) {
        return $null
    }
    return [pscustomobject]@{
        EventTicker = Get-JsonField -Element $Element -Name 'event_ticker'
        GameId      = Get-JsonField -Element $Element -Name 'game_id'
        HomeScore   = Get-JsonField -Element $Element -Name 'home_score'
        AwayScore   = Get-JsonField -Element $Element -Name 'away_score'
        FinalStatus = Get-JsonField -Element $Element -Name 'final_status'
    }
}

function Read-ResultRows {
    param([string] $Path)
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    $raw = [System.IO.File]::ReadAllText($Path)
    $trimmed = $raw.TrimStart()
    $looksJson = $extension -eq '.json' -or $trimmed.StartsWith('[') -or $trimmed.StartsWith('{')
    if (-not $looksJson) {
        $rows = [System.Collections.Generic.List[object]]::new()
        foreach ($record in @(Import-Csv -LiteralPath $Path)) {
            $rows.Add([pscustomobject]@{
                EventTicker = [string]$record.event_ticker
                GameId      = [string]$record.game_id
                HomeScore   = [string]$record.home_score
                AwayScore   = [string]$record.away_score
                FinalStatus = [string]$record.final_status
            })
        }
        return $rows
    }

    $document = [System.Text.Json.JsonDocument]::Parse($raw)
    $root = $document.RootElement
    $elements = @()
    if ($root.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
        $elements = @($root.EnumerateArray())
    } elseif ($root.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
        $nested = $null
        foreach ($name in @('results', 'games', 'events')) {
            $property = $null
            foreach ($candidate in $root.EnumerateObject()) {
                if ($candidate.Name.Equals($name, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $property = $candidate.Value
                    break
                }
            }
            if ($null -ne $property -and $property.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
                $nested = $property
                break
            }
        }
        if ($null -ne $nested) {
            $elements = @($nested.EnumerateArray())
        } else {
            $elements = @($root)
        }
    } else {
        throw "Results JSON must be an array or an object: $Path"
    }

    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($element in $elements) {
        $row = Convert-ResultElement -Element $element
        if ($null -ne $row) {
            $rows.Add($row)
        }
    }
    return $rows
}

if (-not (Test-Path -LiteralPath $Results)) {
    throw "Results file not found: $Results"
}

$resultsPath = [System.IO.Path]::GetFullPath($Results)
$byId = @{}
$skipped = 0
foreach ($row in @(Read-ResultRows -Path $resultsPath)) {
    $status = ([string]$row.FinalStatus).Trim()
    if ($status -ne 'final') {
        Write-Warning ("Skipping result because final_status is '{0}', not final." -f $status)
        $skipped++
        continue
    }
    $homeScore = Convert-Score ([string]$row.HomeScore).Trim()
    $awayScore = Convert-Score ([string]$row.AwayScore).Trim()
    if ($null -eq $homeScore -or $null -eq $awayScore) {
        Write-Warning 'Skipping a final row with a non-integer score.'
        $skipped++
        continue
    }
    $ids = @(
        ([string]$row.EventTicker).Trim(),
        ([string]$row.GameId).Trim()
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    if ($ids.Count -eq 0) {
        Write-Warning 'Skipping a final row with no event_ticker or game_id.'
        $skipped++
        continue
    }
    foreach ($id in $ids) {
        if ($byId.ContainsKey($id)) {
            Write-Warning "Duplicate result for $id. Using the later row."
        }
        $byId[$id] = [pscustomobject]@{
            HomeScore = $homeScore
            AwayScore = $awayScore
        }
    }
}

$jsonOptions = [System.Text.Json.JsonSerializerOptions]::new()
$jsonOptions.WriteIndented = $true
$utf8 = [System.Text.UTF8Encoding]::new($false)
$updated = 0
$unchanged = 0
$matchedIds = @{}

Get-ChildItem -LiteralPath $stubDir -Filter '*.json' -File | ForEach-Object {
    $stubPath = $_.FullName
    if ($stubPath.Equals($resultsPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    Assert-InsideStubDir -Path $stubPath
    $node = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($stubPath))
    $objects = [System.Collections.Generic.List[System.Text.Json.Nodes.JsonObject]]::new()
    if ($node -is [System.Text.Json.Nodes.JsonArray]) {
        foreach ($child in $node) {
            if ($child -is [System.Text.Json.Nodes.JsonObject]) {
                $objects.Add($child)
            }
        }
    } elseif ($node -is [System.Text.Json.Nodes.JsonObject]) {
        $objects.Add($node)
    } else {
        Write-Warning "Skipping $($_.Name): stub JSON is not an object or array."
        $unchanged++
        return
    }

    $fileId = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
    foreach ($item in $objects) {
        $gameNode = $item['game_id']
        if ($gameNode -is [System.Text.Json.Nodes.JsonValue] -and $gameNode.GetValueKind() -eq [System.Text.Json.JsonValueKind]::String) {
            $gameId = [string]$gameNode.GetValue[string]()
            if (-not [string]::IsNullOrWhiteSpace($gameId)) {
                $fileId = $gameId.Trim()
                break
            }
        }
    }

    if (-not $byId.ContainsKey($fileId)) {
        $unchanged++
        return
    }

    $score = $byId[$fileId]
    foreach ($item in $objects) {
        if ($item -isnot [System.Text.Json.Nodes.JsonObject]) {
            continue
        }
        $item['home_score'] = [System.Text.Json.Nodes.JsonValue]::Create([int]$score.HomeScore)
        $item['away_score'] = [System.Text.Json.Nodes.JsonValue]::Create([int]$score.AwayScore)
        $item['status'] = [System.Text.Json.Nodes.JsonValue]::Create('final')
    }

    $body = $node.ToJsonString($jsonOptions) -replace "`r`n", "`n"
    if (-not $body.EndsWith("`n")) {
        $body += "`n"
    }
    [System.IO.File]::WriteAllText($stubPath, $body, $utf8)
    $matchedIds[$fileId] = $true
    $updated++
}

$unmatched = @($byId.Keys | Where-Object { -not $matchedIds.ContainsKey($_) })
foreach ($id in $unmatched) {
    Write-Warning "No stub matched $id."
}

Write-Output ("Updated {0} stub(s), left {1} unchanged, skipped {2} result row(s), unmatched {3}." -f $updated, $unchanged, $skipped, $unmatched.Count)
