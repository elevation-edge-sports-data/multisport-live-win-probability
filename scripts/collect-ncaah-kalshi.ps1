# Pre-game priors only. These are Kalshi yes bids on open NCAAH game
# markets, captured before the games are played. Final scores must be
# joined later from ESPN or this repo's existing score source.
# No API key. The public markets endpoint is enough.

#Requires -Version 7.0

$ErrorActionPreference = 'Stop'

$endpoint = 'https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXNCAAHGAME&status=open&limit=200'

$markets = [System.Collections.Generic.List[object]]::new()
$cursor = ''
do {
    $uri = $endpoint
    if (-not [string]::IsNullOrWhiteSpace($cursor)) {
        $uri = '{0}&cursor={1}' -f $endpoint, [uri]::EscapeDataString($cursor)
    }
    $page = Invoke-RestMethod -Method Get -Uri $uri
    foreach ($market in @($page.markets)) {
        if ($null -ne $market) {
            $markets.Add($market)
        }
    }
    $cursor = [string]$page.cursor
} while (-not [string]::IsNullOrWhiteSpace($cursor))

$capturedAt = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')

$byEvent = [ordered]@{}
foreach ($market in $markets) {
    $eventTicker = [string]$market.event_ticker
    if ([string]::IsNullOrWhiteSpace($eventTicker)) {
        continue
    }
    if (-not $byEvent.Contains($eventTicker)) {
        $byEvent[$eventTicker] = [System.Collections.Generic.List[object]]::new()
    }
    $byEvent[$eventTicker].Add($market)
}

$rows = [System.Collections.Generic.List[object]]::new()
foreach ($eventTicker in $byEvent.Keys) {
    $pair = @($byEvent[$eventTicker] | Sort-Object { [string]$_.ticker })
    if ($pair.Count -ne 2) {
        Write-Warning ("Skipping {0}: expected 2 team markets, found {1}." -f $eventTicker, $pair.Count)
        continue
    }
    $rows.Add([ordered]@{
        event_ticker = $eventTicker
        team_a_title = [string]$pair[0].title
        team_a_yes   = [string]$pair[0].yes_bid_dollars
        team_b_title = [string]$pair[1].title
        team_b_yes   = [string]$pair[1].yes_bid_dollars
        captured_at  = $capturedAt
        source       = 'kalshi'
    })
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$outFile = Join-Path $repoRoot 'ncaah-kalshi-pregame.json'

if ($rows.Count -eq 0) {
    $json = '[]'
} elseif ($rows.Count -eq 1) {
    $one = ConvertTo-Json -InputObject $rows[0] -Depth 4
    $indented = ($one -replace "`r`n", "`n" -split "`n" | ForEach-Object { "  $_" }) -join "`n"
    $json = "[{0}{1}{0}]" -f "`n", $indented
} else {
    $array = [object[]]$rows.ToArray()
    $json = (ConvertTo-Json -InputObject $array -Depth 4) -replace "`r`n", "`n"
}

if (-not $json.EndsWith("`n")) {
    $json += "`n"
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($outFile, $json, $utf8)
Write-Output ("Wrote {0} events to {1}" -f $rows.Count, $outFile)
