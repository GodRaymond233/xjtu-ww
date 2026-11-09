param([string]$PackageDirectory = 'dist/xjtu-ww')

$ErrorActionPreference = 'Stop'
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$buildRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../build'))
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$smokeDirectory = Join-Path $buildRoot "portable-smoke-$([guid]::NewGuid().ToString('N'))"
$stdout = Join-Path $buildRoot 'portable-smoke.stdout.log'
$stderr = Join-Path $buildRoot 'portable-smoke.stderr.log'
$environmentNames = @('PATH', 'QT_QPA_PLATFORM', 'ONEDNN_MAX_CPU_ISA')
$oldEnvironment = @{}
foreach ($name in $environmentNames) {
    $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$process = $null

try {
    Copy-Item -LiteralPath $package -Destination $smokeDirectory -Recurse
    foreach ($required in @('xjtu-ww.exe', 'version.txt', 'src/gui/CharacterCodeTab.py',
                            'src/char/BaseChar.py', 'onnxocr/models/ppocrv5/det/det.onnx')) {
        if (-not (Test-Path -LiteralPath (Join-Path $smokeDirectory $required))) {
            throw "Missing portable runtime file: $required"
        }
    }
    $executable = Join-Path $smokeDirectory 'xjtu-ww.exe'
    $identity = [Diagnostics.FileVersionInfo]::GetVersionInfo($executable)
    $version = (Get-Content -LiteralPath (Join-Path $smokeDirectory 'version.txt') -Raw).Trim()
    if ($identity.ProductName -ne 'XJTU-WW' -or
        $identity.FileDescription -ne 'XJTU-WW Workshop' -or
        $identity.OriginalFilename -ne 'xjtu-ww.exe' -or
        $identity.ProductVersion -ne $version) {
        throw 'Portable executable metadata does not match the XJTU-WW package.'
    }
    # Exclude developer-installed DLLs from the portable runtime's search path.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:ONEDNN_MAX_CPU_ISA = 'AVX2'
    $process = Start-Process -FilePath $executable `
        -WorkingDirectory $buildRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
        [string]$output = Get-Content -LiteralPath $stdout -Raw
        [string]$errors = Get-Content -LiteralPath $stderr -Raw
        if ($errors -match 'Traceback \(most recent call last\)') {
            throw "Portable startup failed. See $stderr"
        }
        if ($process.HasExited) {
            throw "Portable app exited during startup ($($process.ExitCode)). See $stderr"
        }
        if ($output -match 'Window has fully displayed' -and $output -match 'default ocr init end') {
            Write-Host 'Portable app opened its main window and initialized OCR with an isolated PATH.'
            return
        }
    } while ((Get-Date) -lt $deadline)
    throw "Portable startup timed out. See $stdout and $stderr"
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id
        $process.WaitForExit()
    }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name], 'Process')
    }
    $smokeDirectory = [IO.Path]::GetFullPath($smokeDirectory)
    if (-not $smokeDirectory.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar,
                                       [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup path is outside the build directory: $smokeDirectory"
    }
    if (Test-Path -LiteralPath $smokeDirectory) {
        Remove-Item -LiteralPath $smokeDirectory -Recurse -Force
    }
}
