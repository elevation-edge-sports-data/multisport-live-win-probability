# Pre-game calibration stubs from ncaah-kalshi-pregame.json.
# Scores stay 0-0. Final scores must be joined from ESPN or this repo's
# score source before a stub is copied into data/calibration/ncaah/.
#
# Venue assumption: a Kalshi event ticker ends with the away code and then
# the home code. KXNCAAHGAME-26OCT23BCDEN is Boston College at Denver.
# prior_home is that home team's yes_bid_dollars, parsed as a 0-1 price
# and stored with prior_source moneyline. It is the raw yes bid, not a
# two-way de-vig. game_id is the event ticker because the ESPN event id
# is unknown.
# TODO: titles do not say which team is home. If a name is missing from
# the code table, ticker sort is not venue order. That event stores
# team_b as home and still needs a venue check.

#Requires -Version 7.0

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$inFile = Join-Path $repoRoot 'ncaah-kalshi-pregame.json'
$outDir = Join-Path $repoRoot 'ncaah-calibration-stubs'

# Kalshi market codes, keyed by the normalized team title. Used only to
# split the event ticker into away then home. Stored names stay the titles.
$kalshiCodes = @{
    airforce            = 'AF'
    alaskaanchorage    = 'UAA'
    armywestpoint       = 'ARM'
    augustana           = 'AUG'
    bemidjistate        = 'BEM'
    bentley             = 'BEN'
    bostoncollege       = 'BC'
    bostonuniversity    = 'BU'
    bowlinggreen        = 'BG'
    canisius            = 'CAN'
    clarkson            = 'CLA'
    colgate             = 'CLG'
    coloradocollege     = 'CC'
    connecticut         = 'CON'
    denver              = 'DEN'
    ferrisstate         = 'FER'
    holycross           = 'HC'
    lakesuperiorstate   = 'LSS'
    lindenwood          = 'LIN'
    maine               = 'MAI'
    massachusettslowell = 'UML'
    merrimack           = 'MMK'
    miami               = 'MIA'
    michigan            = 'MIC'
    michigantech        = 'MTU'
    michiganstate       = 'MSU'
    minnesota           = 'MIN'
    minnesotaduluth     = 'UMD'
    minnesotastate      = 'MNS'
    newhampshire        = 'UNH'
    niagara             = 'NIA'
    northdakota         = 'UND'
    notredame           = 'ND'
    ohiostate           = 'OSU'
    omaha               = 'UNO'
    pennstate           = 'PSU'
    providence          = 'PRO'
    quinnipiac          = 'QUI'
    rensselaer          = 'RPI'
    rit                 = 'RIT'
    robertmorris        = 'RMU'
    sacredheart         = 'SHU'
    stthomas            = 'UST'
    union               = 'UNI'
    vermont             = 'UVM'
    westernmichigan     = 'WMU'
}

function Get-NameKey([string]$Name) {
    return ([string]$Name).ToLowerInvariant() -replace '[^a-z0-9]', ''
}

function Get-TeamName([string]$Title) {
    $title = ([string]$Title).Trim()
    if ($title -match '^(?<team>.+?)\s+wins$') {
        return $Matches.team.Trim()
    }
    return $title
}

function Convert-YesPrice([string]$Text) {
    $number = 0.0
    $parsed = [double]::TryParse(
        $Text,
        [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$number
    )
    if (-not $parsed) {
        return $null
    }
    return $number
}

function Format-StubJson($Row) {
    $one = ConvertTo-Json -InputObject $Row -Depth 4
    $indented = ($one -replace "`r`n", "`n" -split "`n" | ForEach-Object { "  $_" }) -join "`n"
    return "[{0}{1}{0}]`n" -f "`n", $indented
}

if (-not (Test-Path -LiteralPath $inFile)) {
    throw "Missing $inFile. Run scripts/collect-ncaah-kalshi.ps1 first."
}

# JsonDocument keeps captured_at as the UTC string. ConvertFrom-Json
# turns that timestamp into a DateTime and drops the Z.
$parsed = [System.Text.Json.JsonDocument]::Parse((Get-Content -LiteralPath $inFile -Raw))
$events = foreach ($element in $parsed.RootElement.EnumerateArray()) {
    [pscustomobject]@{
        event_ticker = $element.GetProperty('event_ticker').GetString()
        team_a_title = $element.GetProperty('team_a_title').GetString()
        team_a_yes   = $element.GetProperty('team_a_yes').GetString()
        team_b_title = $element.GetProperty('team_b_title').GetString()
        team_b_yes   = $element.GetProperty('team_b_yes').GetString()
        captured_at  = $element.GetProperty('captured_at').GetString()
    }
}
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$written = 0
foreach ($event in $events) {
    $eventTicker = [string]$event.event_ticker
    if ([string]::IsNullOrWhiteSpace($eventTicker)) {
        Write-Warning 'Skipping a row with no event_ticker.'
        continue
    }

    $nameA = Get-TeamName $event.team_a_title
    $nameB = Get-TeamName $event.team_b_title
    $yesA = Convert-YesPrice ([string]$event.team_a_yes)
    $yesB = Convert-YesPrice ([string]$event.team_b_yes)
    if ($null -eq $yesA -or $null -eq $yesB) {
        Write-Warning "Skipping ${eventTicker}: yes price is not a number."
        continue
    }

    $codeA = $kalshiCodes[(Get-NameKey $nameA)]
    $codeB = $kalshiCodes[(Get-NameKey $nameB)]
    $codes = ''
    if ($eventTicker -match '^KXNCAAHGAME-\d{2}[A-Z]{3}\d{2}(?<codes>[A-Z0-9]+)$') {
        $codes = $Matches.codes
    }

    $awayName = $null
    $homeName = $null
    $priorHome = $null
    if ($codeA -and $codeB -and $codes) {
        if (($codeA + $codeB) -eq $codes) {
            $awayName = $nameA
            $homeName = $nameB
            $priorHome = $yesB
        } elseif (($codeB + $codeA) -eq $codes) {
            $awayName = $nameB
            $homeName = $nameA
            $priorHome = $yesA
        }
    }
    if ($null -eq $homeName) {
        # TODO: venue is ambiguous. team_b is a placeholder home, not a venue.
        Write-Warning ("TODO {0}: could not split away/home from titles. Storing team_b ({1}) as home." -f $eventTicker, $nameB)
        $awayName = $nameA
        $homeName = $nameB
        $priorHome = $yesB
    }

    $row = [ordered]@{
        sport                     = 'ncaah'
        game_id                   = $eventTicker
        home                      = $homeName
        away                      = $awayName
        home_score                = 0
        away_score                = 0
        period                    = 1
        seconds_remaining_period = 1200
        seconds_remaining_total  = 3600
        status                    = 'pre'
        prior_home                = $priorHome
        prior_source              = 'moneyline'
        strength                  = '5v5'
        extra_attacker            = $false
        penalty_remaining         = $null
        penalty_side              = $null
        source                    = 'kalshi'
        as_of                     = [string]$event.captured_at
    }

    $safeName = $eventTicker -replace '[^A-Za-z0-9._-]', '_'
    $outFile = Join-Path $outDir ($safeName + '.json')
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($outFile, (Format-StubJson $row), $utf8)
    $written++
}

$readme = @"
Pre-game stubs only.

These files were built from ncaah-kalshi-pregame.json. Each file is a one-row JSON array: score 0-0, status pre, and a Kalshi yes bid in prior_home. Final scores must be updated before any file is copied into data/calibration/ncaah/.

game_id is the Kalshi event ticker, not an ESPN event id. home and away are team titles. The venue split is documented in scripts/kalshi-to-calibration.ps1.
"@
$readme = ($readme -replace "`r`n", "`n").TrimEnd() + "`n"
$utf8 = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText((Join-Path $outDir 'README.txt'), $readme, $utf8)

Write-Output ("Wrote {0} stubs to {1}" -f $written, $outDir)
