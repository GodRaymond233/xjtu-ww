param(
    [Parameter(Mandatory)][string]$InstallRoot,
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][int]$AppProcessId,
    [switch]$Chinese,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$original = [IO.Path]::GetFullPath($InstallRoot)
$work = [IO.Path]::GetFullPath($Stage)
$payload = Join-Path $work 'xjtu-ww'
$previous = Join-Path $work 'previous'
$metadata = Join-Path $original 'build-info.json'
if ([IO.Path]::GetDirectoryName($work) -ne [IO.Path]::GetDirectoryName($original) -or
    [IO.Path]::GetFileName($work) -notmatch '^\.xjtu-ww-update-[a-z0-9_]+$' -or
    -not [IO.File]::Exists($metadata) -or
    -not [IO.File]::Exists((Join-Path $payload 'xjtu-ww.exe')) -or
    ((Get-Item -LiteralPath @($original, $work, $payload) -Force | Where-Object {
        $_.Attributes -band [IO.FileAttributes]::ReparsePoint
    }) | Measure-Object).Count -gt 0) {
    throw 'Invalid XJTU-WW installation or staging directory.'
}

function Copy-UserFiles($Source, $Destination, $Prefix) {
    foreach ($entry in Get-ChildItem -LiteralPath $Source -Force) {
        $relative = $Prefix + $entry.Name
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Cannot migrate a Windows link: $relative"
        }
        $target = Join-Path $Destination $entry.Name
        if ($entry.PSIsContainer) {
            Copy-UserFiles $entry.FullName $target ($relative + '/')
        } elseif (-not $managed.Contains($relative)) {
            if (Test-Path -LiteralPath $target) {
                throw "The new version has a file at the same path as your local file: $relative"
            }
            [void][IO.Directory]::CreateDirectory($Destination)
            [IO.File]::Copy($entry.FullName, $target)
        }
    }
}

function Show-Result($Message, $Icon) {
    if (-not $Quiet) {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show($Message, 'XJTU-WW', 'OK', $Icon)
    }
}

try {
    $app = Get-Process -Id $AppProcessId -ErrorAction SilentlyContinue
    if ($app -and -not $app.WaitForExit(60000)) {
        throw 'XJTU-WW did not exit in time.'
    }
    $managed = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in (Get-Content -LiteralPath $metadata -Raw -Encoding UTF8 | ConvertFrom-Json).package_files) {
        [void]$managed.Add($file)
    }
    if (-not $managed.Contains('build-info.json') -or -not $managed.Contains('xjtu-ww.exe')) {
        throw 'The installed package inventory is missing.'
    }
    Copy-UserFiles $original $payload ''

    # Move the complete trees on the same volume so locked files cannot leave a mixed installation.
    [IO.Directory]::Move($original, $previous)
    try {
        [IO.Directory]::Move($payload, $original)
    } catch {
        [IO.Directory]::Move($previous, $original)
        throw
    }
} catch {
    $failure = $_.Exception.Message
    if ([IO.Directory]::Exists($previous)) {
        $failure += "`nPrevious installation: $previous"
    } else {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    $message = if ($Chinese) { "更新安装失败。`n$failure" } else { "Update installation failed.`n$failure" }
    Show-Result $message 'Error'
    throw
}

Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
$message = if ($Chinese) { '更新已安装。请双击原来的 xjtu-ww.exe 打开新版。' }
           else { 'Update installed. Open xjtu-ww.exe from its original location to start the new version.' }
Show-Result $message 'Information'
