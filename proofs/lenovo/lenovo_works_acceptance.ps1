$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$expectedRuntimeHead = '86e0000963f35750a411c1a6f3e154f2ba274071'

if ($env:COMPUTERNAME -ne 'JONAS-LENOVO') { throw ('wrong_physical_host:' + $env:COMPUTERNAME) }
$tempBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$evidence = Join-Path $tempBase ('aftergraph-computer-proof-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$roots = @(
  (Join-Path $env:USERPROFILE 'Documents'),
  (Join-Path $env:USERPROFILE 'source'),
  (Join-Path $env:USERPROFILE 'repos'),
  (Join-Path $env:USERPROFILE 'workspace')
) | Where-Object { Test-Path $_ }
$runtimeRepo = $null
foreach ($root in $roots) {
  $candidate = Get-ChildItem -Path $root -Directory -Recurse -Depth 4 -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'runtime' } | Select-Object -First 1 -ExpandProperty FullName
  if ($candidate) {
    $remote = git -C $candidate remote get-url origin 2>$null
    if ($LASTEXITCODE -eq 0 -and $remote -match 'Aftergraph/runtime(?:\.git)?$') { $runtimeRepo = $candidate; break }
  }
}
if (-not $runtimeRepo) { throw 'Aftergraph/runtime local clone not found' }
$sourceHead = (git -C $runtimeRepo rev-parse HEAD).Trim()
if ($sourceHead -ne $expectedRuntimeHead) { throw ('runtime_exact_head_mismatch:' + $sourceHead) }

$tempRepo = Join-Path $tempBase ('aftergraph-runtime-proof-' + [Guid]::NewGuid().ToString('N'))
git clone --local $runtimeRepo $tempRepo | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'runtime_local_clone_failed' }
git -C $tempRepo checkout --detach $sourceHead | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'runtime_detach_failed' }

Push-Location $tempRepo
try {
  corepack enable
  corepack prepare pnpm@11.20.0 --activate
  pnpm install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw 'pnpm_install_failed' }
  pnpm --filter @aftergraph/computer-node build
  if ($LASTEXITCODE -ne 0) { throw 'computer_node_build_failed' }
  pnpm --filter @aftergraph/computer-node test
  if ($LASTEXITCODE -ne 0) { throw 'computer_node_tests_failed' }

  $tb = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Fill($tb)
  $ab = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Fill($ab)
  $token = [Convert]::ToHexString($tb).ToLowerInvariant()
  $authority = [Convert]::ToHexString($ab).ToLowerInvariant()
  if ($token -eq $authority) { throw 'authority_transport_collision' }
  $root = Join-Path $tempBase ('aftergraph-node-root-' + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $root | Out-Null
  Set-Content -LiteralPath (Join-Path $root 'read-proof.txt') -Value 'READ_OK' -NoNewline -Encoding utf8

  $env:AFTERGRAPH_COMPUTER_NODE_ID='jonas-lenovo'
  $env:AFTERGRAPH_COMPUTER_NODE_TOKEN=$token
  $env:AFTERGRAPH_COMPUTER_NODE_AUTHORITY_TOKEN=$authority
  $env:AFTERGRAPH_COMPUTER_NODE_HOST='127.0.0.1'
  $env:AFTERGRAPH_COMPUTER_NODE_PORT='7799'
  $env:AFTERGRAPH_COMPUTER_NODE_ALLOWED_ROOTS=$root

  $stdout=Join-Path $evidence 'node.stdout.log'
  $stderr=Join-Path $evidence 'node.stderr.log'
  $node=Start-Process node -ArgumentList 'packages/computer-node/dist/cli.js' -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden
  try {
    $ready=$false
    for($i=0;$i -lt 30;$i++){
      Start-Sleep -Milliseconds 500
      if($node.HasExited){break}
      try {
        $m=Invoke-RestMethod -Uri 'http://127.0.0.1:7799/v1/manifest' -Headers @{Authorization=('Bearer '+$token)} -TimeoutSec 2
        if($m.nodeId -eq 'jonas-lenovo'){ $ready=$true; break }
      } catch {}
    }
    if(-not $ready){throw 'computer_node_not_ready'}

    $unauth=0
    try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:7799/v1/manifest' -TimeoutSec 3 | Out-Null; $unauth=200 } catch { $unauth=$_.Exception.Response.StatusCode.value__ }
    if($unauth -ne 401){throw ('unauth_expected_401_got_'+$unauth)}

    $headers=@{Authorization=('Bearer '+$token)}
    $manifest=Invoke-RestMethod -Uri 'http://127.0.0.1:7799/v1/manifest' -Headers $headers
    $control=@($manifest.providers | Where-Object {$_.id -eq 'native-windows-control'})
    if($control.Count -ne 1){throw 'native_windows_control_missing'}
    if(@($control[0].capabilities | Where-Object {$_ -like 'computer.shell.*'}).Count -ne 0){throw 'shell_advertised'}
    if(@($control[0].capabilities) -contains 'computer.files.write'){throw 'file_write_advertised'}

    $list=@{providerId='native-windows-control';capability='computer.process.list';input=@{}} | ConvertTo-Json -Depth 4
    $pl=Invoke-RestMethod -Uri 'http://127.0.0.1:7799/v1/action' -Headers $headers -Method Post -ContentType 'application/json' -Body $list
    if(-not $pl.ok -or @($pl.output.processes).Count -lt 1){throw 'process_list_failed'}

    $read=@{providerId='native-windows-control';capability='computer.files.read';input=@{path=(Join-Path $root 'read-proof.txt')}} | ConvertTo-Json -Depth 5
    $rr=Invoke-RestMethod -Uri 'http://127.0.0.1:7799/v1/action' -Headers $headers -Method Post -ContentType 'application/json' -Body $read
    if(-not $rr.ok -or ([string]$rr.output.content).Trim() -ne 'READ_OK'){throw 'file_read_failed'}

    $probe=Start-Process powershell.exe -ArgumentList '-NoLogo','-NoProfile','-NonInteractive','-Command','Start-Sleep -Seconds 120' -PassThru -WindowStyle Hidden
    try {
      $stop=@{providerId='native-windows-control';capability='computer.process.stop';input=@{pid=$probe.Id}} | ConvertTo-Json -Depth 5
      $denied=0
      try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:7799/v1/action' -Headers $headers -Method Post -ContentType 'application/json' -Body $stop | Out-Null; $denied=200 } catch { $denied=$_.Exception.Response.StatusCode.value__ }
      if($denied -ne 403 -or $probe.HasExited){throw 'effect_authority_boundary_failed'}
      $eh=@{Authorization=('Bearer '+$token);'X-Aftergraph-Authority'=$authority}
      $sr=Invoke-RestMethod -Uri 'http://127.0.0.1:7799/v1/action' -Headers $eh -Method Post -ContentType 'application/json' -Body $stop
      if(-not $sr.ok -or -not $sr.output.stopped){throw 'authorized_process_stop_failed'}
      [void]$probe.WaitForExit(10000)
      if(-not $probe.HasExited){throw 'process_stop_not_observed'}
    } finally { if($probe -and -not $probe.HasExited){Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue} }

    foreach($depth in @('quick','standard','forensic')){
      $body=@{scope='health';depth=$depth}|ConvertTo-Json
      $hr=Invoke-RestMethod -Uri 'http://127.0.0.1:7799/v1/inspect' -Headers $headers -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 30
      if(-not ($hr.providers -contains 'native-windows') -or $hr.errors.Count -ne 0){throw ('health_failed_'+$depth)}
    }

    $listener=Get-NetTCPConnection -LocalPort 7799 -State Listen
    if(@($listener | Where-Object {$_.LocalAddress -eq '0.0.0.0' -or $_.LocalAddress -eq '::'}).Count -gt 0){throw 'non_loopback_listener'}

    $verdict=[ordered]@{ok=$true;host=$env:COMPUTERNAME;runtimeHead=$sourceHead;nodeId=$manifest.nodeId;transportAuth=$true;separateEffectAuthority=$true;processList=$true;boundedFileRead=$true;processStop=$true;shellAdvertised=$false;fileWriteAdvertised=$false;loopbackOnly=$true;acceptance='physical-lenovo-live-v02-works'}
    $json=$verdict|ConvertTo-Json -Compress
    Set-Content -LiteralPath (Join-Path $evidence 'verdict.json') -Value $json -Encoding utf8
    Write-Output $json
  } finally { if($node -and -not $node.HasExited){Stop-Process -Id $node.Id -Force -ErrorAction SilentlyContinue} }
} finally {
  Pop-Location
  if(Test-Path $tempRepo){Remove-Item -Recurse -Force $tempRepo -ErrorAction SilentlyContinue}
}
