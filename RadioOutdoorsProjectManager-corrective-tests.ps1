$ErrorActionPreference='Stop'
$scriptPath=Join-Path $PSScriptRoot 'RadioOutdoorsProjectManager.ps1'
$source=Get-Content -LiteralPath $scriptPath -Raw
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw "Project Manager parse failed: $($parseErrors.Message -join '; ')"}

foreach($name in @('Status','Get-TestFailureSummary','Test-StatusBlocksPush','Get-CorrectiveInfo')){
    $functionAst=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if(!$functionAst){throw "Missing corrective-action function: $name"}
    Invoke-Expression $functionAst.Extent.Text
}
function Assert-True($condition,$message){if(!$condition){throw "FAIL: $message"}}

$listenersAst=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Listeners'},$true)
Assert-True ($null-ne$listenersAst) 'Listeners function must exist'
Assert-True (-not $listenersAst.Extent.Text.Contains(',$a')) 'Listeners must not wrap an empty result as one array item'

$ProjectRoot=$PSScriptRoot
$script:TileNames=@{tests='Tests';migrations='Migrations';db='Database backup';server='Port 8000 / Server';leftovers='Codex leftovers';safe='Checkpoint safety'}
$temp=Join-Path ([IO.Path]::GetTempPath()) ('ro-manager-corrective-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp|Out-Null
try{
    $pass=Join-Path $temp 'tests-pass.log';Set-Content -LiteralPath $pass -Value "Ran 1 test`r`nOK`r`nPASS exit=0"
    $one=Join-Path $temp 'tests-one.log';Set-Content -LiteralPath $one -Value @'
FAIL: test_one (core.tests.ExampleTests.test_one)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "C:\repo\core\tests.py", line 42, in test_one
AssertionError: expected true
FAILED (failures=1)
FAIL exit=1
'@
    $many=Join-Path $temp 'tests-many.log';Set-Content -LiteralPath $many -Value @'
FAIL: test_one (core.tests.ExampleTests.test_one)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "C:\repo\core\tests.py", line 42, in test_one
AssertionError: expected true
ERROR: test_two (adventures.tests.ExampleTests.test_two)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "C:\repo\adventures\tests.py", line 81, in test_two
ValueError: simulated problem
FAILED (failures=1, errors=1)
FAIL exit=1
'@
    $passSummary=Get-TestFailureSummary $pass;Assert-True ($passSummary.ExitCode-eq'0') 'passing-test exit code must parse'
    $oneSummary=Get-TestFailureSummary $one;Assert-True ($oneSummary.FailureCount-eq1-and$oneSummary.Failures[0].Source-like'*tests.py:42') 'one failure must include name, count, and source'
    $manySummary=Get-TestFailureSummary $many;Assert-True ($manySummary.FailureCount-eq2-and$manySummary.Failures.Count-eq2) 'multiple failures and errors must parse'
    $missingSummary=Get-TestFailureSummary (Join-Path $temp 'missing.log');Assert-True (!$missingSummary.Exists-and$missingSummary.Summary-like'*missing*') 'missing test log must be explained'

    foreach($case in @(
        @('migrations',(Status 'yellow' '2 unapplied' '[ ] core.0002'),$true),
        @('db',(Status 'yellow' '48.0 hr old' 'C:\backup.sqlite3'),$false),
        @('server',(Status 'yellow' 'Stopped' 'No listener on 8000'),$false),
        @('leftovers',(Status 'yellow' '2 extra' 'PID 10; PID 11'),$false),
        @('tests',(Status 'red' 'FAIL exit=1' $many),$true)
    )){$info=Get-CorrectiveInfo $case[0] $case[1];Assert-True ($info.Explanation-and$info.Actions.Count-and$info.Blocks-eq$case[2]) "$($case[0]) corrective mapping must be complete"}

    $blockers=@(
        Get-CorrectiveInfo 'tests' (Status 'red' 'FAIL exit=1' $one)
        Get-CorrectiveInfo 'migrations' (Status 'yellow' '1 unapplied' '[ ] core.0002')
    );Assert-True ($blockers.Count-eq2-and@($blockers|?{$_.Blocks}).Count-eq2) 'multiple push blockers must remain individually actionable'
    foreach($required in @('Status Details and Corrective Action','Open Test Log','Run Tests Again','Copy Corrective Task','Open Project Folder','Show-CheckpointBlockers','Open $($item.Name) Details','Cursors]::Hand')){Assert-True ($source.Contains($required)) "UI source must contain $required"}
    Write-Output 'PASS: corrective dialogs and passing, failed, missing-log, migration, backup, server, process, and multi-blocker simulations passed.'
}finally{Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
