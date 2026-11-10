param(
    [Parameter(Mandatory = $true)][string]$EastAsiaAccount,
    [Parameter(Mandatory = $true)][string]$KoreaCentralAccount,
    [string]$ProjectRoot = 'C:\Users\ACER\Documents\ChatGPT\Project Cloud',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
if ($EastAsiaAccount -eq $KoreaCentralAccount) { throw 'EastAsiaAccount and KoreaCentralAccount must be different.' }
$split = Join-Path $ProjectRoot 'data\experiments\split_seed_42'
$metadata = Get-Content -LiteralPath (Join-Path $split 'split_metadata.json') -Raw | ConvertFrom-Json
$summary = Get-Content -LiteralPath (Join-Path $split 'iid\clients_5\summary.json') -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath (Join-Path $split 'external_inference_metadata.json'))) {
    throw 'Run python scripts/prepare_external_inference.py before uploading.'
}
$external = Get-Content -LiteralPath (Join-Path $split 'external_inference_metadata.json') -Raw | ConvertFrom-Json
if ($external.feature_schema_sha256 -ne $metadata.feature_schema_sha256) { throw 'External inference schema differs from training split.' }
$files = @(
    @{ Account = $EastAsiaAccount; Container = 'fl-source'; Blob = 'cs-training.csv'; Path = (Join-Path $ProjectRoot 'data\cs-training.csv'); Hash = $metadata.source_sha256 },
    @{ Account = $EastAsiaAccount; Container = 'fl-source'; Blob = 'cs-test.csv'; Path = (Join-Path $ProjectRoot 'data\cs-test.csv'); Hash = $external.source_sha256 },
    @{ Account = $EastAsiaAccount; Container = 'fl-source'; Blob = 'feature_schema.json'; Path = (Join-Path $split 'feature_schema.json'); Hash = $metadata.feature_schema_sha256 },
    @{ Account = $EastAsiaAccount; Container = 'fl-source'; Blob = 'split_metadata.json'; Path = (Join-Path $split 'split_metadata.json'); Hash = $summary.split_sha256 },
    @{ Account = $EastAsiaAccount; Container = 'fl-source'; Blob = 'iid_summary.json'; Path = (Join-Path $split 'iid\clients_5\summary.json'); Hash = $null },
    @{ Account = $EastAsiaAccount; Container = 'fl-eval'; Blob = 'validation.csv'; Path = (Join-Path $split 'validation.csv'); Hash = $metadata.split_sha256.validation },
    @{ Account = $EastAsiaAccount; Container = 'fl-eval'; Blob = 'test.csv'; Path = (Join-Path $split 'test.csv'); Hash = $metadata.split_sha256.test },
    @{ Account = $EastAsiaAccount; Container = 'fl-inference'; Blob = 'external_inference.csv'; Path = (Join-Path $split 'external_inference.csv'); Hash = $external.output_sha256 },
    @{ Account = $EastAsiaAccount; Container = 'fl-inference'; Blob = 'external_inference_metadata.json'; Path = (Join-Path $split 'external_inference_metadata.json'); Hash = $null }
)
foreach ($client in $summary.clients) {
    $id = [int]$client.client_id
    $account = if ($id -le 2) { $EastAsiaAccount } else { $KoreaCentralAccount }
    $files += @{ Account = $account; Container = "client-$id"; Blob = "client_$id.csv"; Path = (Join-Path $split "iid\clients_5\client_$id.csv"); Hash = $client.sha256 }
}
foreach ($item in $files) {
    if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) { throw "Missing file: $($item.Path)" }
    $actual = (Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($item.Hash -and $actual -ne [string]$item.Hash) { throw "SHA256 mismatch: $($item.Path)" }
    Write-Host "$($item.Account)/$($item.Container)/$($item.Blob)  SHA256=$actual"
}
if ($ValidateOnly) { Write-Host 'Validation passed; no upload performed.'; return }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Install Azure CLI and run az login first.' }
az account show --output none
if ($LASTEXITCODE -ne 0) { throw 'Run az login and select the correct subscription.' }
foreach ($pair in @(@{ Name = $EastAsiaAccount; Region = 'eastasia' }, @{ Name = $KoreaCentralAccount; Region = 'koreacentral' })) {
    $actualRegion = az storage account show --name $pair.Name --query primaryLocation --output tsv
    if ($LASTEXITCODE -ne 0) { throw "Cannot read Storage Account $($pair.Name). Check subscription and account name." }
    if ($actualRegion.Trim().ToLowerInvariant().Replace(' ', '') -ne $pair.Region) {
        throw "Storage Account $($pair.Name) is in $actualRegion; expected $($pair.Region)."
    }
}
foreach ($target in ($files | ForEach-Object { "$($_.Account)|$($_.Container)" } | Sort-Object -Unique)) {
    $parts = $target.Split('|')
    az storage container create --account-name $parts[0] --name $parts[1] --auth-mode login --public-access off --output none
    if ($LASTEXITCODE -ne 0) { throw "Could not create container $target. Check Storage Blob Data Contributor role." }
}
$uploadLog = @()
foreach ($item in $files) {
    $startedUtc = (Get-Date).ToUniversalTime().ToString('o')
    $exists = az storage blob exists --account-name $item.Account --container-name $item.Container --name $item.Blob --auth-mode login --query exists --output tsv
    if ($LASTEXITCODE -ne 0) { throw "Cannot check blob: $($item.Account)/$($item.Container)/$($item.Blob)" }
    if ($exists.Trim().ToLowerInvariant() -eq 'true') {
        $temporaryFile = [System.IO.Path]::GetTempFileName()
        try {
            $elapsed = Measure-Command {
                az storage blob download --account-name $item.Account --container-name $item.Container --name $item.Blob --file $temporaryFile --auth-mode login --overwrite true --output none
            }
            if ($LASTEXITCODE -ne 0) { throw "Cannot verify existing blob: $($item.Account)/$($item.Container)/$($item.Blob)" }
            $remoteHash = (Get-FileHash -LiteralPath $temporaryFile -Algorithm SHA256).Hash.ToLowerInvariant()
            $localHash = (Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($remoteHash -ne $localHash) {
                throw "Existing blob differs from local file; no overwrite: $($item.Account)/$($item.Container)/$($item.Blob)"
            }
        }
        finally {
            Remove-Item -LiteralPath $temporaryFile -Force -ErrorAction SilentlyContinue
        }
        $operation = 'verified_existing'
    }
    else {
        $elapsed = Measure-Command {
            az storage blob upload --account-name $item.Account --container-name $item.Container --name $item.Blob --file $item.Path --auth-mode login --overwrite false --output none
        }
        if ($LASTEXITCODE -ne 0) { throw "Upload failed: $($item.Container)/$($item.Blob)" }
        $operation = 'uploaded'
    }
    $size = (Get-Item -LiteralPath $item.Path).Length
    $uploadLog += [pscustomobject]@{
        utc_started = $startedUtc
        operation = $operation
        storage_account = $item.Account
        container = $item.Container
        blob = $item.Blob
        bytes = $size
        seconds = [Math]::Round($elapsed.TotalSeconds, 6)
        mib_per_second = [Math]::Round(($size / 1MB) / [Math]::Max($elapsed.TotalSeconds, 0.000001), 4)
        sha256 = (Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    Write-Host "$operation $($item.Account)/$($item.Container)/$($item.Blob)"
}
$resultDir = Join-Path $ProjectRoot 'results'
New-Item -ItemType Directory -Path $resultDir -Force | Out-Null
$logPath = Join-Path $resultDir 'blob_upload_metrics.csv'
$uploadLog | Export-Csv -LiteralPath $logPath -NoTypeInformation -Encoding UTF8
Write-Host "Upload metrics: $logPath"
