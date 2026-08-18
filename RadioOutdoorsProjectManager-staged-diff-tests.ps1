$ErrorActionPreference='Stop'
$scriptPath=Join-Path $PSScriptRoot 'RadioOutdoorsProjectManager.ps1'
$source=Get-Content -LiteralPath $scriptPath -Raw
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw "Project Manager parse failed: $($parseErrors.Message -join '; ')"}

foreach($name in @('Run-Cmd','Log','Format-CommandStream','Invoke-StagedDiffValidation','Normalize-CheckpointPath','Get-CheckpointPath','Get-CheckpointExclusionReason','Test-IntentionalCheckpointPath','ConvertTo-CheckpointClassification')){
    $functionAst=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if(!$functionAst){throw "Missing staged-diff function: $name"}
    Invoke-Expression $functionAst.Extent.Text
}

function Assert-True($condition,$message){if(!$condition){throw "FAIL: $message"}}

$acceptedImages=@(
    'static/images/example.png',
    'static/images/example.jpg',
    'static/images/example.jpeg',
    'static/images/example.gif',
    'static/images/example.webp',
    'static/images/example.svg'
)
$rejectedImages=@(
    'artifacts/example.png',
    'media/example.png',
    'local-backups/example.png',
    'static/images/../../secret.png',
    '../static/images/example.png',
    'C:/outside/static/images/example.png',
    'static/images/program.exe',
    'static/images/database.sqlite3',
    'static/images/private-key.pem',
    'static/images/example.png.bak',
    'static/images/example.bmp'
)
$imageClassification=ConvertTo-CheckpointClassification @(
    $acceptedImages|ForEach-Object{"?? $_"}
    $rejectedImages|ForEach-Object{"?? $_"}
)
Assert-True ($imageClassification.Intentional.Count-eq$acceptedImages.Count) 'only the six allowed static web-image extensions may be approved'
foreach($path in $acceptedImages){Assert-True ($imageClassification.Intentional.Path-ccontains$path) "$path must be approved as a normal static web image"}
foreach($path in $rejectedImages){Assert-True ($imageClassification.Excluded.Path-ccontains$path) "$path must remain excluded"}
foreach($path in @(
    'static/images/contacts-pencil-background.png',
    'static/images/contacts-radio-telescope-background.png',
    'static/images/login-global-background.png'
)){
    Assert-True (Test-Path -LiteralPath (Join-Path $PSScriptRoot $path)) "$path must remain present for live classification"
    Assert-True (Test-IntentionalCheckpointPath $path) "$path must be approved by live checkpoint classification"
}

$temp=Join-Path ([IO.Path]::GetTempPath()) ('ro-manager-staged-diff-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp|Out-Null
try{
    $ProjectRoot=$temp
    $LogDir=Join-Path $temp 'logs'
    New-Item -ItemType Directory -Path $LogDir|Out-Null

    $init=Run-Cmd 'git init --quiet' 30
    Assert-True ($init.Exit-eq0) "temporary Git repository initialization failed: $($init.Err)"
    Assert-True ((Run-Cmd 'git config user.name "Project Manager Test"' 30).Exit-eq0) 'temporary Git user.name configuration failed'
    Assert-True ((Run-Cmd 'git config user.email "project-manager-test@example.invalid"' 30).Exit-eq0) 'temporary Git user.email configuration failed'

    $testPath=Join-Path $temp 'deliberate-whitespace.txt'
    Set-Content -LiteralPath $testPath -Value 'baseline' -NoNewline
    Assert-True ((Run-Cmd 'git add -- deliberate-whitespace.txt' 30).Exit-eq0) 'baseline staging failed'
    Assert-True ((Run-Cmd 'git commit --quiet -m baseline' 30).Exit-eq0) 'baseline commit failed'
    $headBefore=(Run-Cmd 'git rev-parse HEAD' 30).Out
    $commitCountBefore=(Run-Cmd 'git rev-list --count HEAD' 30).Out

    $workingContent="baseline`r`nline with trailing whitespace   `r`n"
    [IO.File]::WriteAllText($testPath,$workingContent,[Text.UTF8Encoding]::new($false))
    Assert-True ((Run-Cmd 'git add -- deliberate-whitespace.txt' 30).Exit-eq0) 'failure-fixture staging failed'
    $beforeValidation=[IO.File]::ReadAllText($testPath)

    $result=Invoke-StagedDiffValidation @('deliberate-whitespace.txt')

    Assert-True (!$result.Passed) 'deliberate staged-diff failure must be reported'
    Assert-True ($result.ValidationCommand-ceq'git diff --cached --check') 'exact validation command must be retained'
    Assert-True ($result.Validation.Exit-ne0) 'validation exit code must be nonzero'
    Assert-True ($result.Validation.Out-like'*deliberate-whitespace.txt:2: trailing whitespace.*') 'complete Git failure output must be captured'
    Assert-True ($result.ResetCommand-ceq'git reset --mixed') 'reset must explicitly use working-tree-preserving mixed mode'
    Assert-True ($result.Reset.Exit-eq0) "index reset failed: $($result.Reset.Err)"
    Assert-True ($result.DialogText-like'*Command: git diff --cached --check*') 'dialog must contain the validation command'
    Assert-True ($result.DialogText-like"*Exit code: $($result.Validation.Exit)*") 'dialog must contain the validation exit code'
    Assert-True ($result.DialogText-like'*deliberate-whitespace.txt:2: trailing whitespace.*') 'dialog must contain complete validation output'

    $logPath=Join-Path $LogDir ('manager-'+(Get-Date -Format 'yyyyMMdd')+'.log')
    $log=Get-Content -LiteralPath $logPath -Raw
    $normalizedLog=$log-replace"`r?`n","`n"
    $normalizedValidationOut=$result.Validation.Out-replace"`r?`n","`n"
    $normalizedValidationErr=Format-CommandStream $result.Validation.Err
    $normalizedValidationErr=$normalizedValidationErr-replace"`r?`n","`n"
    $normalizedResetOut=Format-CommandStream $result.Reset.Out
    $normalizedResetOut=$normalizedResetOut-replace"`r?`n","`n"
    $normalizedResetErr=Format-CommandStream $result.Reset.Err
    $normalizedResetErr=$normalizedResetErr-replace"`r?`n","`n"
    foreach($expected in @(
        'Validation command: git diff --cached --check',
        "Validation exit code: $($result.Validation.Exit)",
        "Validation stdout:`n$normalizedValidationOut",
        "Validation stderr:`n$normalizedValidationErr",
        'Staged paths (1):',
        'deliberate-whitespace.txt',
        'Reset command: git reset --mixed',
        'Reset exit code: 0',
        "Reset stdout:`n$normalizedResetOut",
        "Reset stderr:`n$normalizedResetErr"
    )){Assert-True ($normalizedLog.Contains($expected)) "manager log must contain: $expected"}

    $cached=Run-Cmd 'git diff --cached --name-only' 30
    Assert-True ($cached.Exit-eq0-and![string]$cached.Out) 'index must be empty after validation failure'
    Assert-True ([IO.File]::ReadAllText($testPath)-ceq$beforeValidation) 'mixed reset must not alter working-file bytes'
    Assert-True ((Run-Cmd 'git rev-parse HEAD' 30).Out-ceq$headBefore) 'validation failure must not create a commit'
    Assert-True ((Run-Cmd 'git rev-list --count HEAD' 30).Out-ceq$commitCountBefore) 'commit count must remain unchanged'
    Assert-True ((Run-Cmd 'git remote' 30).Out-eq'') 'temporary repository must have no push destination'
    Assert-True ($result.ValidationCommand-notmatch'(?i)commit|push'-and$result.ResetCommand-notmatch'(?i)commit|push') 'failure handler must execute neither commit nor push'

    Write-Output 'PASS: static image classification is safe; staged-diff failure logs complete diagnostics, resets only the index, preserves working bytes, and performs no commit or push.'
}finally{
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
