$ErrorActionPreference='Stop'
$scriptPath=Join-Path $PSScriptRoot 'RadioOutdoorsProjectManager.ps1'
$source=Get-Content -LiteralPath $scriptPath -Raw
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw "Project Manager parse failed: $($parseErrors.Message -join '; ')"}

foreach($name in @(
    'Run-Cmd','Log','Format-CommandStream','Normalize-CheckpointPath',
    'Get-CheckpointPathFingerprint','Get-CheckpointSnapshot',
    'Get-CheckpointPathDiagnostic','Stage-CheckpointPaths',
    'Remove-TimedOutStagingLock','Get-StagedCheckpointPaths',
    'Test-StagedCheckpointSet','Format-StagingVerificationDiagnostics',
    'Reset-StagingAfterFailure'
)){
    $functionAst=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if(!$functionAst){throw "Missing staging-verification function: $name"}
    Invoke-Expression $functionAst.Extent.Text
}

function Assert-True($condition,$message){if(!$condition){throw "FAIL: $message"}}
function Item($path){[pscustomobject]@{Status=' M';Path=$path;Reason=$null}}

$temp=Join-Path ([IO.Path]::GetTempPath()) ('ro-manager-staging-verification-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp|Out-Null
try{
    $ProjectRoot=$temp;$LogDir=Join-Path $temp 'logs';New-Item -ItemType Directory -Path $LogDir|Out-Null
    Assert-True ((Run-Cmd 'git init --quiet' 30).Exit-eq0) 'temporary repository initialization failed'
    Assert-True ((Run-Cmd 'git config user.name "Project Manager Test"' 30).Exit-eq0) 'temporary Git user.name configuration failed'
    Assert-True ((Run-Cmd 'git config user.email "project-manager-test@example.invalid"' 30).Exit-eq0) 'temporary Git user.email configuration failed'
    [IO.File]::WriteAllText((Join-Path $temp '.gitattributes'),"*.txt text eol=lf`n",[Text.UTF8Encoding]::new($false))
    foreach($name in @('changed.py','normalization.txt','missing.py','unexpected.py')){
        [IO.File]::WriteAllText((Join-Path $temp $name),"baseline`n",[Text.UTF8Encoding]::new($false))
    }
    Assert-True ((Run-Cmd 'git add -- .gitattributes changed.py normalization.txt missing.py unexpected.py' 30).Exit-eq0) 'baseline staging failed'
    Assert-True ((Run-Cmd 'git commit --quiet -m baseline' 30).Exit-eq0) 'baseline commit failed'

    # A genuinely changed approved path is staged and verified.
    [IO.File]::AppendAllText((Join-Path $temp 'changed.py'),"changed`n",[Text.UTF8Encoding]::new($false))
    $changed=@(Item 'changed.py');$before=Get-CheckpointSnapshot $changed
    $add=Stage-CheckpointPaths $changed;$verified=Test-StagedCheckpointSet $changed $add $before
    Assert-True ($add.Exit-eq0-and$verified.Matches-and$verified.Staged-ccontains'changed.py') 'genuinely changed approved file must stage successfully'
    Assert-True ((Run-Cmd 'git reset --mixed' 30).Exit-eq0) 'changed fixture reset failed'

    # A stale approved path whose CRLF bytes normalize to the HEAD LF blob is
    # accurately removed from the expected set instead of reported missing.
    [IO.File]::WriteAllText((Join-Path $temp 'normalization.txt'),"baseline`r`n",[Text.UTF8Encoding]::new($false))
    $normal=@(Item 'normalization.txt');$normalBefore=Get-CheckpointSnapshot $normal
    $normalAdd=Stage-CheckpointPaths $normal;$normalVerified=Test-StagedCheckpointSet $normal $normalAdd $normalBefore
    Assert-True ($normalVerified.Matches) 'normalization-only approved path must not fail verification'
    Assert-True ($normalVerified.NoStageableDifference-ccontains'normalization.txt') 'normalization-only path must be labeled no stageable difference'
    Assert-True (!$normalVerified.Missing.Count) 'normalization-only path must not be labeled genuinely missing'

    # A genuinely changed approved path that is absent from the index blocks.
    [IO.File]::AppendAllText((Join-Path $temp 'missing.py'),"still-stageable`n",[Text.UTF8Encoding]::new($false))
    $missing=@(Item 'missing.py');$missingVerified=Test-StagedCheckpointSet $missing
    Assert-True (!$missingVerified.Matches-and$missingVerified.Missing-ccontains'missing.py') 'genuinely missing stageable path must block'
    Assert-True ($missingVerified.Diagnostics[0].DiffersFromHead) 'missing stageable diagnostic must report a HEAD difference'

    # An unexpected cached path remains a hard failure.
    [IO.File]::AppendAllText((Join-Path $temp 'unexpected.py'),"unexpected`n",[Text.UTF8Encoding]::new($false))
    Assert-True ((Run-Cmd 'git add -- unexpected.py' 30).Exit-eq0) 'unexpected fixture staging failed'
    $unexpectedVerified=Test-StagedCheckpointSet @()
    Assert-True (!$unexpectedVerified.Matches-and$unexpectedVerified.Unexpected-ccontains'unexpected.py') 'unexpected staged path must block'

    # Failure cleanup empties the index and preserves exact working bytes.
    $workingBefore=@{}
    foreach($name in @('changed.py','normalization.txt','missing.py','unexpected.py')){$workingBefore[$name]=[IO.File]::ReadAllBytes((Join-Path $temp $name))}
    $cleanup=Reset-StagingAfterFailure 'simulated staging-verification failure'
    Assert-True ($cleanup.Command-ceq'git reset --mixed'-and$cleanup.Result.Exit-eq0) 'failure cleanup must use successful mixed reset'
    Assert-True (![string](Run-Cmd 'git diff --cached --name-only' 30).Out) 'failure cleanup must leave the index empty'
    foreach($name in $workingBefore.Keys){
        $after=[IO.File]::ReadAllBytes((Join-Path $temp $name))
        Assert-True ([Convert]::ToBase64String($after)-ceq[Convert]::ToBase64String($workingBefore[$name])) "mixed reset must preserve $name bytes"
    }

    $log=Get-Content -LiteralPath (Join-Path $LogDir ('manager-'+(Get-Date -Format 'yyyyMMdd')+'.log')) -Raw
    foreach($required in @('Reset command: git reset --mixed','Reset exit code: 0','Reset stdout:','Reset stderr:')){Assert-True ($log.Contains($required)) "cleanup log must contain $required"}
    Write-Output 'PASS: staging verification handles changed, normalized no-op, genuinely missing, unexpected, and working-tree-preserving reset cases.'
}finally{
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
