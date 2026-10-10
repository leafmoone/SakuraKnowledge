# Repository-local native entry; no automatic builds/downloads or global configuration.
$ErrorActionPreference = 'Stop'
$root = if (Test-Path (Join-Path $PSScriptRoot 'sknow-config.json')) { $PSScriptRoot } else { Split-Path -Parent $PSScriptRoot }
$utf8 = [System.Text.UTF8Encoding]::new($false)
$target = Join-Path $root 'bin'
$db = Join-Path $root 'data/knowledge.sqlite'
$pack = Join-Path $root 'data/manifest.json'
$childPath = $target + ';' + $env:PATH
$modular = $false
$configPath = Join-Path $root 'sknow-config.json'
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $modular = $null -ne $config.packs_directory
    $paths = if ($modular) { @($config.bin_directory,$config.packs_directory,$config.model_directory) } else { @($config.bin,$config.database,$config.manifest) }
    foreach ($value in $paths) {
        if ([IO.Path]::IsPathRooted($value) -or $value -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Config paths must stay inside package' }
    }
    if ($modular) { $target = Join-Path $root $config.bin_directory }
    else { $target = Join-Path $root $config.bin; $db = Join-Path $root $config.database; $pack = Join-Path $root $config.manifest }
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
        [Console]::Error.WriteLine("Missing program: $path. Prepare bin/ or set package-relative paths in sknow-config.json. Queries never build programs.")
        exit 1
    }
}
if (-not $modular -and $command -notin @('--help','-h','runtime')) {
    foreach ($path in @($db) + $(if ($command -in @('retrieve','serve')) { @($pack) } else { @() })) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            [Console]::Error.WriteLine("Missing prepared asset: $path. Configure prepared local assets in sknow-config.json. Queries never build or download assets.")
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
    $start.Arguments = if ($modular) { '--config ' + (Quote-NativeArgument $configPath) } else { (Quote-NativeArgument $db) + ' ' + (Quote-NativeArgument $pack) }
    $child = [System.Diagnostics.Process]::Start($start)
    try {
        $inputReader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
        $writer = [System.IO.StreamWriter]::new($child.StandardInput.BaseStream, $utf8)
        # A caller may keep stdin open after the native watchdog exits. Never
        # block the launcher on the next input line (or on a full child pipe).
        function Wait-ChildIo($task) {
            while (-not $task.IsCompleted) {
                if ($child.WaitForExit(50)) { return $false }
            }
            return -not $child.HasExited
        }
        while (-not $child.HasExited) {
            $read = $inputReader.ReadLineAsync()
            if (-not (Wait-ChildIo $read)) { break }
            $line = $read.GetAwaiter().GetResult()
            if ($null -eq $line) { $writer.Dispose(); break }
            try {
                $write = $writer.WriteLineAsync($line)
                if (-not (Wait-ChildIo $write)) { break }
                $write.GetAwaiter().GetResult()
                $flush = $writer.FlushAsync()
                if (-not (Wait-ChildIo $flush)) { break }
                $flush.GetAwaiter().GetResult()
            } catch {
                if (-not $child.HasExited) { throw }
                break
            }
        }
        # Do not dispose a reader with a pending console read, or flush a
        # writer after child exit; either can wait on an abandoned pipe.
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
if ($modular) { $forward = @('--config',$configPath,$command) }
if (-not $modular -and $command -eq 'retrieve') { $forward += @($db,$pack) }
elseif (-not $modular -and $command -notin @('--help','-h','runtime')) { $forward += @($db) }
$forward += $tail
$start.Arguments = (@($forward | ForEach-Object { Quote-NativeArgument ([string]$_) }) -join ' ')
$child = [System.Diagnostics.Process]::Start($start)
$child.WaitForExit()
$code = $child.ExitCode
$child.Dispose()
exit $code
