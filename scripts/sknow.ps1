# Repository-local native entry; no automatic builds/downloads or global configuration.
$ErrorActionPreference = 'Stop'
$root = if (Test-Path (Join-Path $PSScriptRoot 'sknow-config.json')) { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
$utf8 = [System.Text.UTF8Encoding]::new($false)
$target = Join-Path $root 'build/p4-usearch-native-fix/rust-target/release'
$db = Join-Path $root 'build/p3-full-authorized-retry1/knowledge.sqlite'
$pack = Join-Path $root 'build/p4-dev-2048-1mib-3ee34e2-v1/manifest.json'
$childPath = 'C:/msys64/ucrt64/bin;' + $env:PATH
$configPath = Join-Path $root 'sknow-config.json'
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($value in @($config.bin,$config.database,$config.manifest)) {
        if ([IO.Path]::IsPathRooted($value) -or $value -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Config paths must stay inside package' }
    }
    $target = Join-Path $root $config.bin
    $db = Join-Path $root $config.database
    $pack = Join-Path $root $config.manifest
    $childPath = $target + ';' + [Environment]::GetFolderPath('System') + ';' + $env:SystemRoot
}
function Quote-NativeArgument([string]$value) {
    # Windows CommandLineToArgvW quoting, including embedded quotes/trailing slashes.
    return '"' + ([regex]::Replace([regex]::Replace($value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1')) + '"'
}
$command = if ($args.Count) { [string]$args[0] } else { '--help' }
$tail = @($args | Select-Object -Skip 1)
$exe = Join-Path $target $(if ($command -eq 'serve') { 'semantic_pilot.exe' } else { 'sknow-rs.exe' })
foreach ($path in @($exe)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        [Console]::Error.WriteLine("Missing program: $path. Build from repo root: `$env:CARGO_TARGET_DIR='build/p4-usearch-native-fix/rust-target'; cargo build --release --manifest-path rust/Cargo.toml --features semantic --bins")
        exit 1
    }
}
if ($command -notin @('--help','-h','runtime')) {
    foreach ($path in @($db) + $(if ($command -in @('retrieve','serve')) { @($pack) } else { @() })) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            [Console]::Error.WriteLine("Missing prepared asset: $path. See README semantic prerequisites; use the existing tools.p4_full_build preparation CLI with explicit create-new paths. Queries never build assets.")
            exit 1
        }
    }
}
if ($command -eq 'serve') {
    # Forward complete JSONL stdin through .NET, avoiding native argument quoting loss.
    $start = [System.Diagnostics.ProcessStartInfo]::new($exe)
    $start.UseShellExecute = $false
    $start.EnvironmentVariables['PATH'] = $childPath
    $start.EnvironmentVariables['PYTHONUTF8'] = '1'
    $start.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $start.RedirectStandardInput = $true
    $start.Arguments = (Quote-NativeArgument $db) + ' ' + (Quote-NativeArgument $pack)
    $child = [System.Diagnostics.Process]::Start($start)
    try {
        $inputReader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
        $writer = [System.IO.StreamWriter]::new($child.StandardInput.BaseStream, $utf8)
        while ($null -ne ($line = $inputReader.ReadLine())) { $writer.WriteLine($line); $writer.Flush() }
        $writer.Dispose()
        $child.WaitForExit()
        exit $child.ExitCode
    } finally { if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit() }; $child.Dispose() }
}
$start = [System.Diagnostics.ProcessStartInfo]::new($exe)
$start.UseShellExecute = $false
$start.EnvironmentVariables['PATH'] = $childPath
$start.EnvironmentVariables['PYTHONUTF8'] = '1'
$start.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
$forward = @($command)
if ($command -eq 'retrieve') { $forward += @($db,$pack) }
elseif ($command -notin @('--help','-h','runtime')) { $forward += @($db) }
$forward += $tail
$start.Arguments = (@($forward | ForEach-Object { Quote-NativeArgument ([string]$_) }) -join ' ')
$child = [System.Diagnostics.Process]::Start($start)
$child.WaitForExit()
$code = $child.ExitCode
$child.Dispose()
exit $code
