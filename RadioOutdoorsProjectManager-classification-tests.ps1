$ErrorActionPreference='Stop'
$scriptPath=Join-Path $PSScriptRoot 'RadioOutdoorsProjectManager.ps1'
$source=Get-Content -LiteralPath $scriptPath -Raw
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw "Project Manager parse failed: $($parseErrors.Message -join '; ')"}

foreach($name in @('Run-Cmd','Normalize-CheckpointPath','Get-CheckpointPath','Get-CheckpointExclusionReason','Test-IntentionalCheckpointPath','ConvertTo-CheckpointClassification','Get-CheckpointClassification')){
    $functionAst=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if(!$functionAst){throw "Missing classification function: $name"}
    Invoke-Expression $functionAst.Extent.Text
}

function Assert-True($condition,$message){if(!$condition){throw "FAIL: $message"}}
function Assert-Excluded($path){Assert-True ((Get-CheckpointExclusionReason $path) -ne $null) "$path must remain excluded"}

$rootStatus=' M .gitignore'
$rootPath=Get-CheckpointPath $rootStatus
Assert-True ($rootPath -ceq '.gitignore') 'root .gitignore status path must parse exactly'
Assert-True (Test-IntentionalCheckpointPath $rootPath) 'root .gitignore must be intentional configuration'
Assert-True (!(Test-IntentionalCheckpointPath 'nested/.gitignore')) 'nested .gitignore must not be broadly approved'
Assert-True (!(Test-IntentionalCheckpointPath '.env')) 'other hidden files must not be broadly approved'

$porcelain=@(
    ' M .gitignore',
    '?? work.bak',
    '?? RO-20260813-tool.ps1',
    '?? archive.zip',
    '?? google_maps_api_key.txt',
    '?? db.sqlite3',
    '?? local-backups/db-copy.sqlite3',
    '?? __pycache__/module.pyc'
)
$classification=ConvertTo-CheckpointClassification $porcelain
Assert-True ($classification.Intentional.Count -eq 1) 'porcelain classification must contain one intentional path'
Assert-True ($classification.Intentional[0].Path -ceq '.gitignore') 'root .gitignore must retain its leading period in the intentional list'
Assert-True (!($classification.Excluded.Path -contains '.gitignore')) 'root .gitignore must not appear in the excluded list'
Assert-True ($classification.Excluded.Count -eq 7) 'all porcelain backup/tool/archive/secret/database/cache artifacts must be excluded'

# Exercise the real command runner and grouping pipeline. This catches leading
# porcelain whitespace being stripped before fixed-column parsing.
$ProjectRoot=$PSScriptRoot
$live=Get-CheckpointClassification
Assert-True (!$live.Error) "live Git classification failed: $($live.Error)"
$liveStatus=Run-Cmd 'git status --short --untracked-files=all' 30
if($liveStatus.Out -match '(?m)^.. \.gitignore$'){
    Assert-True ($live.Intentional.Path -ccontains '.gitignore') 'live classification must place a changed root .gitignore in the intentional list'
    Assert-True (!($live.Excluded.Path -ccontains '.gitignore')) 'live classification must not exclude a changed root .gitignore'
}

@(
    'work.bak',
    'RO-20260813-tool.ps1',
    'RO-20260813-source.zip',
    'radiooutdoors-source-collection.zip',
    'local-backups/db.sqlite3',
    'db.sqlite3',
    'media-backups/media.zip',
    '__pycache__/module.pyc',
    'temp/work.tmp',
    'google_maps_api_key.txt'
)|ForEach-Object{Assert-Excluded $_}

Write-Output 'PASS: root .gitignore is intentional; nested/other hidden files and backup/tool artifacts remain excluded.'
