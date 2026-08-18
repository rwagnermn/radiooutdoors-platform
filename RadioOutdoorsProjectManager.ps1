Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = 8000
$LogDir = Join-Path $ProjectRoot "project-manager-logs"
$BackupDir = Join-Path $ProjectRoot "local-backups"
New-Item -ItemType Directory -Force -Path $LogDir,$BackupDir | Out-Null

function Run-Cmd($cmd,[int]$timeout=120) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName="cmd.exe"; $psi.Arguments="/d /s /c `"$cmd`""
    $psi.WorkingDirectory=$ProjectRoot; $psi.UseShellExecute=$false
    $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
    $psi.CreateNoWindow=$true
    $p=New-Object System.Diagnostics.Process; $p.StartInfo=$psi; [void]$p.Start()
    # Drain both redirected streams while the process runs. Waiting first can
    # deadlock when Git emits enough warnings to fill a pipe buffer.
    $outTask=$p.StandardOutput.ReadToEndAsync();$errTask=$p.StandardError.ReadToEndAsync()
    if(-not $p.WaitForExit($timeout*1000)){
        $timedOutPid=$p.Id
        # cmd.exe can leave git.exe descendants alive. Kill and await the whole
        # process tree so descendants cannot retain .git/index.lock.
        try{Start-Process taskkill.exe -ArgumentList '/PID',"$timedOutPid",'/T','/F' -Wait -WindowStyle Hidden -ErrorAction Stop|Out-Null}catch{try{$p.Kill()}catch{}}
        if(!$p.HasExited){[void]$p.WaitForExit(15000)}
        return @{Exit=124;TimedOut=$true;ProcessId=$timedOutPid;Out=$outTask.GetAwaiter().GetResult().TrimEnd();Err=("Timed out after $timeout seconds; process tree PID $timedOutPid was terminated and awaited.`r`n"+$errTask.GetAwaiter().GetResult()).Trim()}
    }
    # Preserve leading characters: Git porcelain uses a leading space as the
    # unstaged status column. Trim() corrupts the first status line.
    return @{Exit=$p.ExitCode;Out=$outTask.GetAwaiter().GetResult().TrimEnd();Err=$errTask.GetAwaiter().GetResult().Trim()}
}
function Py(){ $p=Join-Path $ProjectRoot ".venv\Scripts\python.exe"; if(Test-Path $p){$p}else{$null} }
function Django($djangoArgs,[int]$timeout=120){$p=Py;if(!$p){return @{Exit=9001;Out="";Err=".venv Python missing"}};Run-Cmd "`"$p`" manage.py $djangoArgs" $timeout}
function Log($m){Add-Content (Join-Path $LogDir ("manager-"+(Get-Date -Format "yyyyMMdd")+".log")) "[$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")] $m"}
function Status($state,$text,$detail=""){[pscustomobject]@{State=$state;Text=$text;Detail=$detail}}

function Format-CommandStream($value){
    if([string]::IsNullOrEmpty([string]$value)){'(empty)'}else{[string]$value}
}

function Invoke-StagedDiffValidation($stagedPaths){
    $validationCommand='git diff --cached --check'
    $validation=Run-Cmd $validationCommand 60
    if($validation.Exit-eq0){
        return [pscustomobject]@{Passed=$true;ValidationCommand=$validationCommand;Validation=$validation;ResetCommand=$null;Reset=$null;DialogText=$null}
    }

    $paths=@($stagedPaths)
    $validationOut=Format-CommandStream $validation.Out
    $validationErr=Format-CommandStream $validation.Err
    # A mixed reset replaces only the index with HEAD. It leaves tracked and
    # untracked working-tree content untouched.
    $resetCommand='git reset --mixed'
    $reset=Run-Cmd $resetCommand 60
    $resetOut=Format-CommandStream $reset.Out
    $resetErr=Format-CommandStream $reset.Err
    $pathText=if($paths.Count){$paths-join"`r`n"}else{'(none)'}
    $logText=@"
Staged diff validation failed.
Validation command: $validationCommand
Validation exit code: $($validation.Exit)
Validation stdout:
$validationOut
Validation stderr:
$validationErr
Staged paths ($($paths.Count)):
$pathText
Reset command: $resetCommand
Reset exit code: $($reset.Exit)
Reset stdout:
$resetOut
Reset stderr:
$resetErr
"@
    Log $logText.TrimEnd()
    $dialogText=@"
Command: $validationCommand
Exit code: $($validation.Exit)

STDOUT:
$validationOut

STDERR:
$validationErr

Reset command: $resetCommand
Reset exit code: $($reset.Exit)
The reset only unstages files; working-tree contents are unchanged.
"@
    [pscustomobject]@{Passed=$false;ValidationCommand=$validationCommand;Validation=$validation;ResetCommand=$resetCommand;Reset=$reset;DialogText=$dialogText.TrimEnd()}
}

function GitBranch(){ $r=Run-Cmd "git branch --show-current" 20; if($r.Exit-eq0){Status ($(if($r.Out-eq"main"){"green"}else{"yellow"})) $r.Out "Expected main"}else{Status "red" "Git failed" $r.Err}}
function Tree(){ $r=Run-Cmd "git status --porcelain" 30;if($r.Exit-ne0){return Status "red" "Git failed" $r.Err};if(!$r.Out){return Status "green" "Clean" "No uncommitted changes"};$lines=@($r.Out -split "`r?`n"|?{$_});$conflicts=@($lines|?{$_ -match '^(DD|AU|UD|UA|DU|AA|UU) '});if($conflicts.Count){return Status "red" "$($conflicts.Count) merge conflict(s)" ($conflicts-join"`r`n")};Status "yellow" "$($lines.Count) changed/new" ($lines-join"`r`n")}
function Sync(){ $f=Run-Cmd "git fetch --quiet origin" 45;if($f.Exit-ne0){return Status "yellow" "Fetch unavailable" $f.Err};$r=Run-Cmd "git rev-list --left-right --count HEAD...origin/main" 20;if($r.Exit-ne0){return Status "yellow" "Unknown" $r.Err};$x=$r.Out -split '\s+';$a=[int]$x[0];$b=[int]$x[1];$s=if($b-gt0){"red"}elseif($a-gt0){"yellow"}else{"green"};Status $s "Ahead $a / Behind $b" "origin/main"}
function LastCommit(){ $r=Run-Cmd 'git log -1 --format="%h %ad %s" --date=format:"%Y-%m-%d %H:%M"' 20;if($r.Exit-eq0){Status "green" ($r.Out.Substring(0,[Math]::Min(32,$r.Out.Length))) $r.Out}else{Status "yellow" "Unavailable" $r.Err}}
function DjCheck(){ $r=Django "check" 90;if($r.Exit-eq0){Status "green" "Passed" ($r.Out+" "+$r.Err).Trim()}else{Status "red" "Failed" ($r.Out+"`r`n"+$r.Err).Trim()}}
function Migrations(){ $r=Django "showmigrations --plan" 90;if($r.Exit-ne0){return Status "red" "Check failed" $r.Err};$u=@($r.Out -split "`r?`n"|?{$_ -match '^\s*\[\s\]'});if($u.Count){Status "yellow" "$($u.Count) unapplied" ($u-join"`r`n")}else{Status "green" "All applied" ""}}
function MissingMig(){ $r=Django "makemigrations --check --dry-run" 90;if($r.Exit-eq0){Status "green" "None" ($r.Out+" "+$r.Err).Trim()}else{Status "red" "Migration needed" ($r.Out+"`r`n"+$r.Err).Trim()}}
function PythonVer(){ $p=Py;if(!$p){return Status "red" ".venv missing" ""};$r=Run-Cmd "`"$p`" --version" 15;if($r.Exit-eq0){Status "green" $r.Out $p}else{Status "red" "Python failed" $r.Err}}
function DjangoVer(){ $p=Py;if(!$p){return Status "red" "Unavailable" ""};$r=Run-Cmd "`"$p`" -m django --version" 15;if($r.Exit-eq0){Status "green" "Django $($r.Out)" ""}else{Status "red" "Unavailable" $r.Err}}
function Test-RadioOutdoorsHttp(){
    try{
        $r=Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($r.Content -match '(?i)Radio Outdoors')
    }catch{
        return $false
    }
}
function Listeners(){
    $a=@()
    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue|%{
        $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue
        $cmd=if($p){$p.CommandLine}else{""}
        $isRunserver=($cmd -match '(?i)manage\.py.*runserver')
        $hasProjectHint=($cmd -like "*$ProjectRoot*" -or $cmd -like "*.venv\Scripts\python.exe*")
        $a += [pscustomobject]@{PID=$_.OwningProcess;Cmd=$cmd;RO=($isRunserver -and $hasProjectHint)}
    }
    # A normal Windows-launched Django server may have a short command line such as
    # "python manage.py runserver --noreload" with no project path.  When there is
    # exactly one listener, confirm it by probing localhost for Radio Outdoors.
    if($a.Count -eq 1 -and -not $a[0].RO){
        if(($a[0].Cmd -match '(?i)manage\.py.*runserver') -and (Test-RadioOutdoorsHttp)){
            $a[0].RO=$true
        }
    }
    ,$a
}
function Server(){ $a=@(Listeners);if(!$a.Count){return Status "yellow" "Stopped" "No listener on $Port"};if($a.Count-gt1){return Status "red" "$($a.Count) listeners" (($a|%{"PID $($_.PID): $($_.Cmd)"})-join"`r`n")};$x=$a[0];Status ($(if($x.RO){"green"}else{"red"})) "PID $($x.PID)" $x.Cmd}
function Leftovers(){ $all=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|?{$_.CommandLine-like"*radiooutdoors-platform*" -and $_.CommandLine-like"*manage.py*runserver*"});$ls=@(Listeners|%{$_.PID});$e=@($all|?{$_.ProcessId-notin$ls});if($e.Count){Status "yellow" "$($e.Count) extra" (($e|%{"PID $($_.ProcessId): $($_.CommandLine)"})-join"`r`n")}else{Status "green" "None" ""}}
$patterns=@("openai_api_key*.txt","google_*api_key*.txt","qrz_username.txt","qrz_password.txt",".env","db.sqlite3","*.sqlite3")
function Secrets(){
    $bad=@();$seen=@()
    foreach($pat in $patterns){Get-ChildItem $ProjectRoot -Filter $pat -File -ErrorAction SilentlyContinue|%{$seen+=$_.Name;$r=Run-Cmd "git check-ignore -q -- `"$($_.Name)`"" 15;if($r.Exit-ne0){$bad+=$_.Name}}}
    $st=Run-Cmd "git diff --cached --name-only" 20
    foreach($n in @($st.Out -split "`r?`n"|?{$_})){foreach($pat in $patterns){if($n-like$pat){$bad+=$n}}}
    $bad=@($bad|sort -Unique)
    if($bad.Count){Status "red" "DO NOT PUSH" ("Sensitive/unignored:`r`n"+($bad-join"`r`n"))}else{Status "green" "Protected" ($(if($seen.Count){$seen-join", "}else{"No secret files found"}))}
}
function DbBackup(){ $db=Join-Path $ProjectRoot "db.sqlite3";if(!(Test-Path $db)){return Status "yellow" "No database" ""};$f=@(Get-ChildItem $BackupDir -Filter "db-*.sqlite3" -File -ErrorAction SilentlyContinue|sort LastWriteTime -Descending);if(!$f.Count){return Status "red" "No backup" ""};$h=((Get-Date)-$f[0].LastWriteTime).TotalHours;$s=if($h-le24){"green"}elseif($h-le72){"yellow"}else{"red"};Status $s ("{0:N1} hr old" -f $h) $f[0].FullName}
function MediaBackup(){ $m=Join-Path $ProjectRoot "media";if(!(Test-Path $m)){return Status "yellow" "No media folder" ""};$f=@(Get-ChildItem $BackupDir -Filter "media-*.zip" -File -ErrorAction SilentlyContinue|sort LastWriteTime -Descending);if(!$f.Count){return Status "yellow" "No backup" ""};$h=((Get-Date)-$f[0].LastWriteTime).TotalHours;$s=if($h-le24){"green"}elseif($h-le72){"yellow"}else{"red"};Status $s ("{0:N1} hr old" -f $h) $f[0].FullName}
function Disk(){ $d=New-Object IO.DriveInfo([IO.Path]::GetPathRoot($ProjectRoot));$g=[math]::Round($d.AvailableFreeSpace/1GB,1);Status ($(if($g-gt50){"green"}elseif($g-gt15){"yellow"}else{"red"})) "$g GB free" ""}
$script:TestJob=$null
$script:TestLog=$null
$script:TestTimer=$null

function Tests(){
    if($script:TestJob -and $script:TestJob.State -eq "Running"){
        return Status "yellow" "Running..." $script:TestLog
    }
    $f=@(Get-ChildItem $LogDir -Filter "tests-*.log" -File -ErrorAction SilentlyContinue|sort LastWriteTime -Descending)
    if(!$f.Count){return Status "yellow" "Not run here" ""}
    $last=Get-Content $f[0].FullName -Tail 1
    $s=if($last-like"PASS*"){"green"}else{"red"}
    Status $s $last $f[0].FullName
}

function Get-TestFailureSummary($path){
    $result=[ordered]@{Path=$path;Exists=$false;Date='Unknown';ExitCode='Unknown';FailureCount=0;Failures=@();Summary='Test log is missing.'}
    if(!$path-or!(Test-Path -LiteralPath $path)){return [pscustomobject]$result}
    $file=Get-Item -LiteralPath $path;$result.Exists=$true;$result.Date=$file.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    $lines=@(Get-Content -LiteralPath $path -ErrorAction SilentlyContinue)
    $exitLine=@($lines|?{$_ -match '^(PASS|FAIL) exit=(-?\d+)\s*$'}|Select-Object -Last 1)
    if($exitLine-and$exitLine[-1]-match 'exit=(-?\d+)'){$result.ExitCode=$Matches[1]}
    $reported=@($lines|?{$_ -match '^FAILED \((?:failures|errors)='}|Select-Object -Last 1)
    if($reported){$counts=[regex]::Matches($reported[-1],'(?:failures|errors)=(\d+)');$result.FailureCount=($counts|%{[int]$_.Groups[1].Value}|Measure-Object -Sum).Sum}
    for($i=0;$i-lt$lines.Count;$i++){
        if($lines[$i]-notmatch '^(FAIL|ERROR):\s+(.+)$'){continue}
        $name=$Matches[2].Trim();$source='';$message=''
        for($j=$i+1;$j-lt[Math]::Min($lines.Count,$i+35);$j++){
            if(!$source-and$lines[$j]-match '^\s*File "([^"]+)", line (\d+)'){$source="$($Matches[1]):$($Matches[2])"}
            if(!$message-and$lines[$j]-match '^(AssertionError|[A-Za-z_][\w.]*Error|[A-Za-z_][\w.]*Exception):\s*(.+)$'){$message=$lines[$j].Trim()}
            if($j-gt$i+2-and$lines[$j]-match '^(FAIL|ERROR):'){break}
        }
        if(!$message){$message='See the complete test log for the traceback.'}
        $result.Failures+=,[pscustomobject]@{Name=$name;Message=$message;Source=$source}
    }
    if(!$result.FailureCount){$result.FailureCount=$result.Failures.Count}
    $result.Summary=if($result.Failures.Count){($result.Failures|%{"$($_.Name)`r`n  $($_.Message)$(if($_.Source){"`r`n  Source: $($_.Source)"})"})-join"`r`n`r`n"}elseif($result.ExitCode-ne'0'){'Tests exited unsuccessfully, but no named failure block was found. Open the log for complete output.'}else{'No test failures were found.'}
    [pscustomobject]$result
}

function Test-StatusBlocksPush($key,$status){
    if(!$status){return $false}
    switch($key){'secrets'{return $status.State-eq'red'}'django'{return $status.State-eq'red'}'missing'{return $status.State-eq'red'}'migrations'{return $status.State-ne'green'}'tests'{return $status.State-eq'red'-or$status.Text-like'Running*'}'tree'{return $status.State-eq'red'}'sync'{return $status.State-eq'red'}default{return $false}}
}
function Get-CorrectiveInfo($key,$status){
    $name=if($script:TileNames-and$script:TileNames.ContainsKey($key)){$script:TileNames[$key]}else{$key}
    $blocks=Test-StatusBlocksPush $key $status;$explanation='This status needs attention before normal development continues.';$evidence=$status.Detail;$actions=@('Review the supporting evidence.','Correct the underlying condition.','Refresh status and verify that the tile turns green.');$task="Repository: $ProjectRoot`r`nCondition: $name - $($status.Text)`r`nEvidence:`r`n$($status.Detail)`r`n`r`nInspect and correct this condition. Run the relevant verification commands. Do not commit or push. Restart exactly one development server at 127.0.0.1:8000 when complete.";$logPath=$null;$run='Refresh'
    switch($key){
        'tests'{$summary=Get-TestFailureSummary $status.Detail;$logPath=$summary.Path;$explanation=if($summary.Exists){"The most recent test run exited with code $($summary.ExitCode). $($summary.FailureCount) failure(s) or error(s) were reported."}else{'The latest test result refers to a log that is missing, so the failure output cannot be inspected.'};$evidence="Exit code: $($summary.ExitCode)`r`nTest date/time: $($summary.Date)`r`nComplete test-log path: $($summary.Path)`r`nFailure/error count: $($summary.FailureCount)`r`n`r`n$($summary.Summary)";$actions=@('Open the test log and inspect each complete traceback.','Correct the application or test code responsible for each named failure.','Run the failed tests, then run the complete Django test suite.','Run python manage.py check, python manage.py makemigrations --check --dry-run, and git diff --check.','Do not commit or push; stop all development servers and restart exactly one at 127.0.0.1:8000.');$names=($summary.Failures|%{$_.Name})-join"`r`n";$task="Repository path: $ProjectRoot`r`nTest-log path: $($summary.Path)`r`n`r`nFailed-test names:`r`n$names`r`n`r`nError summaries:`r`n$($summary.Summary)`r`n`r`nInspect the complete log and correct every failure. Verify with the failed-test commands, then:`r`npython manage.py test`r`npython manage.py check`r`npython manage.py makemigrations --check --dry-run`r`ngit diff --check`r`n`r`nDo not commit or push. At completion, stop all Radio Outdoors development-server processes and restart exactly one server at 127.0.0.1:8000.";$run='Tests'}
        'django'{$explanation='Django found a configuration, import, model, URL, or application-system error.';$actions=@('Read the Django check output below.','Correct the first reported application error and repeat until clean.','Run python manage.py check.');$run='Django'}
        'migrations'{$explanation='Migration files exist but have not been applied to this development database.';$actions=@('Back up db.sqlite3.','Review the unapplied migration names.','Use Apply Migrations only after confirming the backup.','Run python manage.py showmigrations --plan.');$run='Migrations'}
        'missing'{$explanation='Model changes are not represented by migration files.';$actions=@('Review the model changes.','Create and inspect the required migration.','Run python manage.py makemigrations --check --dry-run.');$run='Missing'}
        'tree'{if($status.State-eq'red'){$explanation='Git reports unresolved merge conflicts.';$actions=@('Open each conflicted file listed below.','Resolve conflict markers without discarding unrelated work.','Run git status --short and the project verification commands.')}else{$explanation='The working tree contains uncommitted work. This is expected while work is in progress and is a warning, not an automatic failure.';$actions=@('Review the changed and untracked paths.','Preserve unrelated work.','Finish and verify the intended changes before checkpointing.')}}
        'branch'{$explanation="The current branch differs from the expected main branch. A feature branch may intentionally protect unfinished work, so this is a warning rather than a failure.";$actions=@('Confirm that the displayed branch is intentional.','Do not switch branches while uncommitted work exists unless that work is safely preserved.','Refresh status after returning to the expected branch.');$run='Branch'}
        'sync'{if($status.Text-match'Behind ([1-9]\d*)'){$explanation='This repository is behind origin/main; pushing without reconciling remote work is blocked.';$actions=@('Preserve all local work.','Fetch and review the incoming commits.','Integrate them deliberately, resolve conflicts, and rerun verification.')}elseif($status.Text-match'Ahead ([1-9]\d*)'){$explanation='Local commits have not yet reached GitHub. This is a warning when the commits are intentional.';$actions=@('Review the local commits and current branch.','Verify the working tree and checks.','Use the checkpoint workflow only when explicitly ready.')}else{$explanation='GitHub synchronization could not be confirmed.'};$run='Sync'}
        'db'{$explanation='The database backup is missing or older than the safe freshness window.';$actions=@('Review the backup path and age.','Click Backup Database to create a new recoverable copy.','Refresh and confirm the backup tile is green.');$run='Database Backup'}
        'media'{$explanation='The media backup is missing or stale.';$actions=@('Review the media folder and latest backup path.','Click Backup Media to create a current archive.','Refresh and confirm the backup age.');$run='Media Backup'}
        'server'{$explanation=if($status.Text-eq'Stopped'){'No development server is listening at 127.0.0.1:8000.'}else{'Port 8000 has multiple listeners or a listener that could not be identified as Radio Outdoors.'};$actions=@('Review every PID and command line below.','Use the explicit Stop Server control for confirmed Radio Outdoors processes.','Start exactly one server at 127.0.0.1:8000 and refresh.');$run='Server'}
        'leftovers'{$explanation='One or more Radio Outdoors development-server processes remain outside the active listener.';$actions=@('Review each PID and command line.','Stop only confirmed leftover Radio Outdoors server processes.','Start or retain exactly one listener at 127.0.0.1:8000.');$run='Server'}
        'python'{$explanation='The project virtual environment or its Python executable is missing or unusable.';$actions=@('Confirm the expected .venv path below.','Create or repair the virtual environment without deleting unrelated files.','Install requirements and rerun Python and Django checks.');$run='Python'}
        'venv'{$explanation='The required .venv environment is missing.';$actions=@('Create .venv in the repository root.','Install requirements.txt.','Run python manage.py check.');$run='Python'}
        'secrets'{$explanation='A credential or sensitive local file is not safely ignored, or is staged. A push is blocked to prevent disclosure.';$actions=@('Unstage any sensitive path without deleting the local file.','Add the appropriate ignore rule and verify it with git check-ignore.','Rotate any credential that may already have been exposed.','Refresh status before attempting a checkpoint.');$run='Secrets'}
        'disk'{$explanation='Available disk space is below the recommended development threshold.';$actions=@('Review the drive and free-space amount.','Remove only known disposable files outside this dialog.','Maintain backups before clearing project data, then refresh.');$run='Disk'}
        'safe'{$explanation='One or more checkpoint prerequisites are blocked or need review.';$actions=@('Open the Full Checkpoint & Push control to see all blockers.','Open each relevant tile and follow its corrective actions.','Refresh and confirm no blocking issues remain.');$run='Refresh'}
    }
    [pscustomobject]@{Key=$key;Name=$name;Status=$status.Text;Blocks=$blocks;Explanation=$explanation;Evidence=$evidence;Actions=$actions;Task=$task;LogPath=$logPath;Run=$run}
}

function BackupDB(){ $db=Join-Path $ProjectRoot "db.sqlite3";if(!(Test-Path $db)){[Windows.Forms.MessageBox]::Show("db.sqlite3 not found.")|Out-Null;return};$to=Join-Path $BackupDir ("db-"+(Get-Date -Format "yyyyMMdd-HHmmss")+".sqlite3");Copy-Item $db $to;Log "Database backup: $to";[Windows.Forms.MessageBox]::Show("Backup created:`r`n$to")|Out-Null}
function BackupMedia(){ $m=Join-Path $ProjectRoot "media";if(!(Test-Path $m)){[Windows.Forms.MessageBox]::Show("No media folder.")|Out-Null;return};$to=Join-Path $BackupDir ("media-"+(Get-Date -Format "yyyyMMdd-HHmmss")+".zip");Compress-Archive (Join-Path $m "*") $to -Force;Log "Media backup: $to";[Windows.Forms.MessageBox]::Show("Backup created:`r`n$to")|Out-Null}
function StartServer(){
    if(@(Listeners).Count){[Windows.Forms.MessageBox]::Show("Port 8000 is already occupied. Server not started.")|Out-Null;return}
    $p=Py;if(!$p){[Windows.Forms.MessageBox]::Show(".venv Python missing.")|Out-Null;return}
    $base=(& $p -c "import sys; print(sys._base_executable)").Trim();if(!$base-or!(Test-Path -LiteralPath $base)){[Windows.Forms.MessageBox]::Show("Base Python executable could not be resolved.")|Out-Null;return}
    $previousPythonPath=$env:PYTHONPATH
    try{$env:PYTHONPATH=Join-Path $ProjectRoot '.venv\Lib\site-packages';$process=Start-Process -FilePath $base -ArgumentList @('manage.py','runserver','127.0.0.1:8000','--noreload') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru}finally{$env:PYTHONPATH=$previousPythonPath}
    Log "Server started PID $($process.Id) at 127.0.0.1:8000"
}
function StopServer(){ $a=@(Listeners|?{$_.RO});if(!$a.Count){[Windows.Forms.MessageBox]::Show("No Radio Outdoors server on port 8000.")|Out-Null;return};$ok=[Windows.Forms.MessageBox]::Show("Stop Radio Outdoors listener(s): "+(($a|%{$_.PID})-join", ")+"?","Stop Server","YesNo");if($ok-ne"Yes"){return};$a|%{Stop-Process -Id $_.PID -Force -ErrorAction SilentlyContinue;Log "Stopped server PID $($_.PID)"}}
function ApplyMigrations(){if([Windows.Forms.MessageBox]::Show("Back up database and apply migrations?","Migrations","YesNo")-ne"Yes"){return};BackupDB;$r=Django "migrate" 300;[Windows.Forms.MessageBox]::Show(($r.Out+"`r`n"+$r.Err).Trim(),"Migration Result")|Out-Null}
function RunTests(){
    if($script:TestJob -and $script:TestJob.State -eq "Running"){
        [Windows.Forms.MessageBox]::Show("Tests are already running.","Tests")|Out-Null
        return
    }
    $p=Py
    if(!$p){[Windows.Forms.MessageBox]::Show(".venv Python missing.","Tests")|Out-Null;return}

    $script:TestLog=Join-Path $LogDir ("tests-"+(Get-Date -Format "yyyyMMdd-HHmmss")+".log")
    $root=$ProjectRoot
    $log=$script:TestLog

    $script:TestJob=Start-Job -ArgumentList $root,$p,$log -ScriptBlock {
        param($root,$python,$log)
        Set-Location $root
        $lines=@()
        & $python manage.py test 2>&1 | ForEach-Object {
            $lines += $_.ToString()
        }
        $exit=$LASTEXITCODE
        $res=if($exit -eq 0){"PASS"}else{"FAIL"}
        $body=(($lines -join "`r`n").Trim()+"`r`n$res exit=$exit")
        Set-Content -Path $log -Value $body -Encoding UTF8
        [pscustomobject]@{Exit=$exit;Result=$res;Log=$log}
    }

    SetM "tests" (Status "yellow" "Running..." $script:TestLog)
    $overall.Text="TESTS RUNNING - DO NOT PUSH"
    $overall.ForeColor="DarkOrange"
    Log "Tests started"

    if($script:TestTimer){$script:TestTimer.Stop();$script:TestTimer.Dispose()}
    $script:TestTimer=New-Object Windows.Forms.Timer
    $script:TestTimer.Interval=1000
    $script:TestTimer.Add_Tick({
        if(!$script:TestJob){return}
        if($script:TestJob.State -in @("Completed","Failed","Stopped")){
            $script:TestTimer.Stop()
            $result=Receive-Job $script:TestJob -ErrorAction SilentlyContinue | Select-Object -Last 1
            $state=$script:TestJob.State
            Remove-Job $script:TestJob -Force -ErrorAction SilentlyContinue
            $script:TestJob=$null
            $script:TestTimer.Dispose()
            $script:TestTimer=$null

            if($result -and $result.Result){
                Log "Tests $($result.Result)"
                Refresh
                [Windows.Forms.MessageBox]::Show("$($result.Result)`r`n$($result.Log)","Tests")|Out-Null
            }else{
                if(!(Test-Path $script:TestLog)){
                    Set-Content -Path $script:TestLog -Value "FAIL test job state=$state" -Encoding UTF8
                }
                Log "Tests FAIL - background job state $state"
                Refresh
                [Windows.Forms.MessageBox]::Show("FAIL`r`nBackground test job state: $state`r`n$script:TestLog","Tests")|Out-Null
            }
        }
    })
    $script:TestTimer.Start()
}

function Normalize-CheckpointPath($path){
    if($null-eq$path){return $null}
    $normalized=$path.Replace('\','/').TrimEnd()
    if($normalized.StartsWith('./')){$normalized=$normalized.Substring(2)}
    return $normalized
}

function Get-CheckpointPath($statusLine){
    if($statusLine.Length -lt 4){return $null}
    # Porcelain v1 reserves exactly columns 0-1 for status and column 2 for
    # the separator. Never TrimStart(): the first path character may be '.'.
    $path=$statusLine.Substring(3).TrimEnd()
    if($path -match ' -> '){$path=($path -split ' -> ',2)[1]}
    if($path.StartsWith('"') -and $path.EndsWith('"')){
        # Quoted porcelain paths can contain Git escape sequences. Treating them as
        # unapproved is safer than staging a path we did not decode exactly.
        return $null
    }
    Normalize-CheckpointPath $path
}

function Get-CheckpointExclusionReason($path){
    $p=$path.Replace('\','/')
    $leaf=[IO.Path]::GetFileName($p)
    if([IO.Path]::IsPathRooted($p) -or $p -match '(^|/)\.\.(/|$)'){return 'rooted path or path-traversal attempt'}
    if($leaf -match '(?i)\.bak$'){return 'backup file (*.bak)'}
    if($leaf -match '(?i)^RO-.*\.ps1$'){return 'local RO tool script'}
    if($leaf -match '(?i)^RO-.*\.zip$'){return 'local RO archive'}
    if($leaf -match '(?i)source[-_ ]collection.*\.zip$'){return 'source-collection archive'}
    if($leaf -match '(?i)\.zip$'){return 'generated/archive ZIP'}
    if($p -match '(?i)(^|/)local-backups/'){return 'local backup directory'}
    if($p -match '(?i)(^|/)project-manager-logs/'){return 'generated Project Manager log'}
    if($p -match '(?i)(^|/)media(/|$)' -or $p -match '(?i)(^|/)media[-_ ]?backups?(/|$)'){return 'media or media backup'}
    if($leaf -match '(?i)^(db\.sqlite3|.*\.(sqlite3?|db))$'){return 'database file'}
    if($p -match '(?i)(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|htmlcov)(/|$)' -or $leaf -match '(?i)\.(pyc|pyo)$'){return 'Python cache/test output'}
    if($p -match '(?i)(^|/)(tmp|temp)(/|$)' -or $leaf -match '(?i)(\.tmp|\.temp|\.swp|~)$'){return 'temporary/generated file'}
    if($leaf -match '(?i)^\.env($|\.)' -or $leaf -match '(?i)(api[-_]?key|secret|credential|password).*\.(txt|key|pem|json)$'){return 'secret or API-key file'}
    return $null
}

function Test-IntentionalCheckpointPath($path){
    $p=Normalize-CheckpointPath $path
    $leaf=[IO.Path]::GetFileName($p)
    # This is intentionally an exact repository-relative match. Do not broaden
    # this to every dotfile or to nested .gitignore files.
    if([string]::Equals($p,'.gitignore',[StringComparison]::OrdinalIgnoreCase)){return $true}
    if($leaf -in @('manage.py','requirements.txt','README.txt','RadioOutdoorsProjectManager.ps1','RadioOutdoorsProjectManager-async-tests.ps1','RadioOutdoorsProjectManager-classification-tests.ps1','RadioOutdoorsProjectManager-corrective-tests.ps1','RadioOutdoorsProjectManager-staged-diff-tests.ps1','Start-Project-Manager.bat','Start-RadioOutdoors-Project-Manager.bat')){return $true}
    if($p -match '^static/images/.+' -and $leaf -match '(?i)\.(png|jpg|jpeg|gif|webp|svg)$'){return $true}
    if($p -notmatch '^(adventures|backend|core|static|templates|docs|tools)/'){return $false}
    return ($leaf -match '(?i)\.(py|html|css|js|json|md|txt|bat|ps1|yml|yaml|toml)$')
}

function ConvertTo-CheckpointClassification($statusLines){
    $intentional=@();$excluded=@()
    foreach($line in @($statusLines|Where-Object{$_})){
        $path=Get-CheckpointPath $line
        if(!$path){$excluded += [pscustomobject]@{Status=$line.Substring(0,[Math]::Min(2,$line.Length));Path=$line.Substring([Math]::Min(3,$line.Length));Reason='path could not be safely decoded'};continue}
        $reason=Get-CheckpointExclusionReason $path
        if(!$reason -and !(Test-IntentionalCheckpointPath $path)){$reason='not an approved source/config/migration/test/template/static path'}
        $item=[pscustomobject]@{Status=$line.Substring(0,2);Path=$path;Reason=$reason}
        if($reason){$excluded += $item}else{$intentional += $item}
    }
    [pscustomobject]@{Intentional=@($intentional);Excluded=@($excluded)}
}

function Get-CheckpointClassification(){
    $status=Run-Cmd 'git status --short --untracked-files=all' 30
    if($status.Exit-ne0){return [pscustomobject]@{Error=($status.Out+"`r`n"+$status.Err).Trim();Intentional=@();Excluded=@()}}
    $classified=ConvertTo-CheckpointClassification ($status.Out -split "`r?`n")
    [pscustomobject]@{Error=$null;Intentional=$classified.Intentional;Excluded=$classified.Excluded}
}

function Show-CheckpointConfirmation($files){
    $dialog=New-Object Windows.Forms.Form
    $dialog.Text='Confirm Full Checkpoint Push'
    $work=[Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $dialog.Width=[Math]::Min(960,[int]($work.Width*.88))
    $dialog.Height=[Math]::Min(760,[int]($work.Height*.88))
    $dialog.StartPosition='CenterScreen';$dialog.MinimizeBox=$false;$dialog.MaximizeBox=$false;$dialog.ShowInTaskbar=$false;$dialog.KeyPreview=$true

    $layout=New-Object Windows.Forms.TableLayoutPanel
    $layout.Dock='Fill';$layout.Padding=New-Object Windows.Forms.Padding(12);$layout.ColumnCount=1;$layout.RowCount=3
    $layout.RowStyles.Add((New-Object Windows.Forms.RowStyle([Windows.Forms.SizeType]::AutoSize)))|Out-Null
    $layout.RowStyles.Add((New-Object Windows.Forms.RowStyle([Windows.Forms.SizeType]::Percent,100)))|Out-Null
    $layout.RowStyles.Add((New-Object Windows.Forms.RowStyle([Windows.Forms.SizeType]::AutoSize)))|Out-Null
    $dialog.Controls.Add($layout)

    $notice=New-Object Windows.Forms.Label
    $notice.AutoSize=$true;$notice.MaximumSize=New-Object Drawing.Size(($dialog.Width-55),0)
    $notice.Text="Full Checkpoint Push commits the intentional files listed below and pushes the commit to GitHub (origin/main).`r`nExcluded local, backup, generated, database, media, and secret files will not be staged."
    $layout.Controls.Add($notice,0,0)

    $split=New-Object Windows.Forms.SplitContainer
    $split.Dock='Fill';$split.Orientation='Horizontal';$split.SplitterDistance=[int](($dialog.Height-190)*.55)
    $layout.Controls.Add($split,0,1)
    $intentGroup=New-Object Windows.Forms.GroupBox;$intentGroup.Text="Intentional files to checkpoint ($($files.Intentional.Count))";$intentGroup.Dock='Fill';$split.Panel1.Controls.Add($intentGroup)
    $intentBox=New-Object Windows.Forms.TextBox;$intentBox.Multiline=$true;$intentBox.ReadOnly=$true;$intentBox.WordWrap=$false;$intentBox.ScrollBars='Both';$intentBox.Dock='Fill';$intentBox.Font=New-Object Drawing.Font('Consolas',9)
    $intentBox.Text=(($files.Intentional|ForEach-Object{"$($_.Status)  $($_.Path)"})-join"`r`n");$intentGroup.Controls.Add($intentBox)
    $excludedGroup=New-Object Windows.Forms.GroupBox;$excludedGroup.Text="Excluded files (not staged) ($($files.Excluded.Count))";$excludedGroup.Dock='Fill';$split.Panel2.Controls.Add($excludedGroup)
    $excludedBox=New-Object Windows.Forms.TextBox;$excludedBox.Multiline=$true;$excludedBox.ReadOnly=$true;$excludedBox.WordWrap=$false;$excludedBox.ScrollBars='Both';$excludedBox.Dock='Fill';$excludedBox.Font=New-Object Drawing.Font('Consolas',9)
    $excludedBox.Text=(($files.Excluded|ForEach-Object{"$($_.Status)  $($_.Path)  [$($_.Reason)]"})-join"`r`n");$excludedGroup.Controls.Add($excludedBox)

    $buttons=New-Object Windows.Forms.FlowLayoutPanel;$buttons.Dock='Fill';$buttons.AutoSize=$true;$buttons.FlowDirection='RightToLeft';$buttons.WrapContents=$false
    $cancel=New-Object Windows.Forms.Button;$cancel.Text='Cancel';$cancel.AutoSize=$true;$cancel.MinimumSize=New-Object Drawing.Size(110,36);$cancel.DialogResult='Cancel'
    $confirm=New-Object Windows.Forms.Button;$confirm.Text='Checkpoint and Push';$confirm.AutoSize=$true;$confirm.MinimumSize=New-Object Drawing.Size(165,36)
    $confirm.Add_Click({$dialog.DialogResult='OK';$dialog.Close()})
    $buttons.Controls.Add($cancel);$buttons.Controls.Add($confirm);$layout.Controls.Add($buttons,0,2)
    $dialog.CancelButton=$cancel;$dialog.AcceptButton=$null
    $dialog.Add_Shown({$cancel.Select()})
    $dialog.Add_KeyDown({
        param($sender,$e)
        if($e.KeyCode-eq[Windows.Forms.Keys]::Escape){$cancel.PerformClick();$e.SuppressKeyPress=$true}
        elseif($e.KeyCode-eq[Windows.Forms.Keys]::Enter){if($confirm.Focused){$confirm.PerformClick()}else{$cancel.PerformClick()};$e.SuppressKeyPress=$true}
    })
    try{return ($dialog.ShowDialog()-eq[Windows.Forms.DialogResult]::OK)}finally{$dialog.Dispose()}
}

function Stage-CheckpointPaths($items){
    $pathspec=Join-Path ([IO.Path]::GetTempPath()) ("radiooutdoors-stage-"+[guid]::NewGuid().ToString('N')+'.paths')
    try{
        $stream=New-Object IO.MemoryStream
        foreach($item in $items){$bytes=[Text.Encoding]::UTF8.GetBytes($item.Path);$stream.Write($bytes,0,$bytes.Length);$stream.WriteByte(0)}
        [IO.File]::WriteAllBytes($pathspec,$stream.ToArray());$stream.Dispose()
        $displayCommand='git add --pathspec-from-file=<temporary-approved-path-list> --pathspec-file-nul'
        Log "Staging started: $($items.Count) approved paths; command: $displayCommand"
        foreach($item in $items){Log "Staging approved path: $($item.Path)"}
        $stagingStarted=Get-Date
        $result=Run-Cmd "git add --pathspec-from-file=`"$pathspec`" --pathspec-file-nul" 300
        if($result.Exit-eq124){$result.LockCleanup=Remove-TimedOutStagingLock $stagingStarted;Log "Timed-out staging cleanup: $($result.LockCleanup)"}
        $result.Command=$displayCommand;$result.Paths=@($items|ForEach-Object{$_.Path})
        Log "Staging finished: exit=$($result.Exit); approved=$($items.Count)"
        return $result
    }finally{if(Test-Path -LiteralPath $pathspec){Remove-Item -LiteralPath $pathspec -Force}}
}

function Remove-TimedOutStagingLock($stagingStarted){
    $gitDir=Join-Path $ProjectRoot '.git';$lockPath=Join-Path $gitDir 'index.lock';$indexPath=Join-Path $gitDir 'index'
    $deadline=(Get-Date).AddSeconds(10)
    do{$gitProcesses=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{$_.Name-match'^(git|git-lfs)(\.exe)?$'});if(!$gitProcesses.Count){break};Start-Sleep -Milliseconds 200}while((Get-Date)-lt$deadline)
    if($gitProcesses.Count){return "Lock not removed: Git process(es) still active: $($gitProcesses.ProcessId-join', ')"}
    $markers=@(@('rebase-apply','rebase-merge','MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','BISECT_LOG','BISECT_START','sequencer')|Where-Object{Test-Path -LiteralPath (Join-Path $gitDir $_)})
    if($markers.Count){return "Lock not removed: active Git operation marker(s): $($markers-join', ')"}
    if(!(Test-Path -LiteralPath $lockPath)){return 'No index lock remained after the terminated staging process.'}
    $lock=Get-Item -LiteralPath $lockPath
    if($lock.Length-ne0-or$lock.LastWriteTime-lt$stagingStarted.AddSeconds(-2)){return "Lock not removed: it was not identified as the zero-byte lock created by this staging attempt ($($lock.LastWriteTime))."}
    if(!(Test-Path -LiteralPath $indexPath)){return 'Lock not removed: .git/index could not be confirmed.'}
    $expected=[IO.Path]::GetFullPath((Join-Path $gitDir 'index.lock'));if($lock.FullName-ne$expected){return 'Lock not removed: resolved lock path did not match .git/index.lock.'}
    try{Remove-Item -LiteralPath $expected -Force -ErrorAction Stop}catch{return "Stale lock removal failed: $($_.Exception.Message)"}
    if(Test-Path -LiteralPath $expected){return 'Stale lock removal was attempted but the lock still exists.'}
    return 'Confirmed no Git process or operation owned the lock; removed the stale .git/index.lock and preserved .git/index.'
}

function Get-StagedCheckpointPaths(){
    $result=Run-Cmd 'git diff --cached --name-only' 60
    if($result.Exit-ne0){return [pscustomobject]@{Error=($result.Out+"`r`n"+$result.Err).Trim();Paths=@()}}
    [pscustomobject]@{Error=$null;Paths=@($result.Out -split "`r?`n"|Where-Object{$_}|ForEach-Object{$_.Replace('\','/')})}
}

function Test-StagedCheckpointSet($approvedItems){
    $approved=@($approvedItems|ForEach-Object{$_.Path.Replace('\','/')}|Sort-Object -Unique)
    $staged=Get-StagedCheckpointPaths
    if($staged.Error){return [pscustomobject]@{Matches=$false;Error=$staged.Error;Missing=@();Unexpected=@();Staged=@()}}
    $actual=@($staged.Paths|Sort-Object -Unique)
    $missing=@(Compare-Object $approved $actual -PassThru|Where-Object{$_.SideIndicator-eq'<='})
    $unexpected=@(Compare-Object $approved $actual -PassThru|Where-Object{$_.SideIndicator-eq'=>'})
    [pscustomobject]@{Matches=(!$missing.Count-and!$unexpected.Count);Error=$null;Missing=$missing;Unexpected=$unexpected;Staged=$actual}
}

function Checkpoint([bool]$quick=$false){
    if(!$quick){$blocking=@($last.GetEnumerator()|?{Test-StatusBlocksPush $_.Key $_.Value}|%{Get-CorrectiveInfo $_.Key $_.Value});if($blocking.Count){Show-CheckpointBlockers $blocking;return}}
    $sec=Secrets;if($sec.State-eq"red"){[Windows.Forms.MessageBox]::Show($sec.Detail,"DO NOT PUSH")|Out-Null;return}
    if(!$quick){
        $d=DjCheck;if($d.State-eq"red"){[Windows.Forms.MessageBox]::Show($d.Detail,"Django Check Failed")|Out-Null;return}
        $m=MissingMig;if($m.State-eq"red"){[Windows.Forms.MessageBox]::Show($m.Detail,"Migration Required")|Out-Null;return}
        $a=Migrations;if($a.State-ne"green"){[Windows.Forms.MessageBox]::Show("Unapplied migrations exist.","Checkpoint Blocked")|Out-Null;return}
        $x=Run-Cmd "git diff --check" 60;if($x.Exit-ne0){[Windows.Forms.MessageBox]::Show(($x.Out+"`r`n"+$x.Err),"Diff Check Failed")|Out-Null;return}
    }
    $files=Get-CheckpointClassification
    if($files.Error){[Windows.Forms.MessageBox]::Show($files.Error,"Git Status Failed")|Out-Null;return}
    if(!$files.Intentional.Count){[Windows.Forms.MessageBox]::Show("No intentional source, configuration, migration, test, template, or static files remain after exclusions. No commit was created.","Nothing to Checkpoint")|Out-Null;return}
    if(!(Show-CheckpointConfirmation $files)){return}
    $reset=Run-Cmd "git reset" 30;if($reset.Exit-ne0){[Windows.Forms.MessageBox]::Show(($reset.Out+"`r`n"+$reset.Err),"Could Not Prepare Staging")|Out-Null;return}
    $a=Stage-CheckpointPaths $files.Intentional
    if($a.Exit-ne0){
        $staged=Get-StagedCheckpointPaths;$stagedText=if($staged.Paths.Count){$staged.Paths-join"`r`n"}else{'(none)'}
        Log "Staging failed: command=$($a.Command); exit=$($a.Exit); affected paths=$($a.Paths-join', '); staged before failure=$($staged.Paths-join', '); error=$($a.Err)"
        [Windows.Forms.MessageBox]::Show("Command: $($a.Command)`r`nAffected paths: all $($a.Paths.Count) approved paths (listed in the Project Manager log).`r`n`r`nStaged before failure:`r`n$stagedText`r`n`r`nLock cleanup: $($a.LockCleanup)`r`n`r`n$($a.Out)`r`n$($a.Err)`r`n`r`nCommit and push were blocked.","Staging Failed")|Out-Null;return
    }
    $verified=Test-StagedCheckpointSet $files.Intentional
    if(!$verified.Matches){
        Log "Staged-set mismatch; commit blocked. Missing=$($verified.Missing-join', '); unexpected=$($verified.Unexpected-join', '); error=$($verified.Error)"
        $reconcile=Run-Cmd 'git reset' 60;Log "Index reconciled after staged-set mismatch: git reset exit=$($reconcile.Exit); working-tree content preserved"
        [Windows.Forms.MessageBox]::Show("The staged files do not exactly match the approved list. Commit and push were blocked, and the index was cleared without changing working-tree files.`r`n`r`nMissing:`r`n$($verified.Missing-join"`r`n")`r`n`r`nUnexpected:`r`n$($verified.Unexpected-join"`r`n")`r`n`r`n$($verified.Error)","Staging Verification Failed")|Out-Null;return
    }
    Log "Staged-set verification passed: $($verified.Staged.Count) paths exactly match the approved list"
    $sec=Secrets;if($sec.State-eq"red"){Run-Cmd "git reset" 30|Out-Null;[Windows.Forms.MessageBox]::Show($sec.Detail+"`r`n`r`nStaging reset.","DO NOT PUSH")|Out-Null;return}
    $stagedDiff=Invoke-StagedDiffValidation $verified.Staged
    if(!$stagedDiff.Passed){[Windows.Forms.MessageBox]::Show($stagedDiff.DialogText,"Staged Diff Check Failed")|Out-Null;return}
    $msg="Radio Outdoors checkpoint - "+(Get-Date -Format "yyyy-MM-dd HH:mm")
    $c=Run-Cmd "git commit -m `"$msg`"" 180;if($c.Exit-ne0){[Windows.Forms.MessageBox]::Show(($c.Out+"`r`n"+$c.Err),"Commit Failed")|Out-Null;return}
    $p=Run-Cmd "git push origin main" 300;if($p.Exit-ne0){[Windows.Forms.MessageBox]::Show(($p.Out+"`r`n"+$p.Err),"Push Failed")|Out-Null;return}
    Log "Checkpoint pushed: $msg";[Windows.Forms.MessageBox]::Show("Checkpoint pushed.`r`n$msg","Success")|Out-Null;Refresh
}

function Invoke-CorrectiveRun($kind){
    switch($kind){'Tests'{RunTests}'Django'{SetM 'django' (DjCheck)}'Migrations'{SetM 'migrations' (Migrations)}'Missing'{SetM 'missing' (MissingMig)}'Branch'{SetM 'branch' (GitBranch)}'Sync'{SetM 'sync' (Sync)}'Database Backup'{BackupDB;SetM 'db' (DbBackup)}'Media Backup'{BackupMedia;SetM 'media' (MediaBackup)}'Server'{Refresh}'Python'{SetM 'python' (PythonVer)}'Secrets'{SetM 'secrets' (Secrets)}'Disk'{SetM 'disk' (Disk)}default{Refresh}}
}
function Show-StatusDetails($key){
    $status=$last[$key];if(!$status-or$status.State-eq'green'){return};$info=Get-CorrectiveInfo $key $status
    $dialog=New-Object Windows.Forms.Form;$dialog.Text='Status Details and Corrective Action';$dialog.Size=New-Object Drawing.Size(900,700);$dialog.MinimumSize=New-Object Drawing.Size(720,540);$dialog.StartPosition='CenterParent';$dialog.Font=New-Object Drawing.Font('Segoe UI',11);$dialog.KeyPreview=$true
    $layout=New-Object Windows.Forms.TableLayoutPanel;$layout.Dock='Fill';$layout.Padding=New-Object Windows.Forms.Padding(16);$layout.ColumnCount=1;$layout.RowCount=3;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize')))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent',100)))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize')))|Out-Null;$dialog.Controls.Add($layout)
    $heading=New-Object Windows.Forms.Label;$heading.AutoSize=$true;$heading.Font=New-Object Drawing.Font('Segoe UI Semibold',15);$heading.Text=$info.Name;$layout.Controls.Add($heading)
    $body=New-Object Windows.Forms.TextBox;$body.Multiline=$true;$body.ReadOnly=$true;$body.ScrollBars='Both';$body.WordWrap=$true;$body.Dock='Fill';$body.Font=New-Object Drawing.Font('Segoe UI',11);$numbered=for($i=0;$i-lt$info.Actions.Count;$i++){"$($i+1). $($info.Actions[$i])"};$body.Text="Current status: $($info.Status)`r`nBlocks a checkpoint push: $(if($info.Blocks){'Yes'}else{'No'})`r`n`r`nExplanation`r`n$($info.Explanation)`r`n`r`nSupporting evidence`r`n$($info.Evidence)`r`n`r`nCorrective actions`r`n$($numbered-join"`r`n")";$layout.Controls.Add($body)
    $buttons=New-Object Windows.Forms.FlowLayoutPanel;$buttons.AutoSize=$true;$buttons.Dock='Fill';$buttons.WrapContents=$true;$layout.Controls.Add($buttons)
    function Add-DialogButton($text,$handler,[int]$width=145){$b=New-Object Windows.Forms.Button;$b.Text=$text;$b.Width=$width;$b.Height=40;$b.Margin=New-Object Windows.Forms.Padding(4);$b.Add_Click($handler);$buttons.Controls.Add($b)|Out-Null}
    if($info.LogPath-and(Test-Path -LiteralPath $info.LogPath)){Add-DialogButton $(if($key-eq'tests'){'Open Test Log'}else{'Open Log'}) ({Start-Process notepad.exe -ArgumentList @($info.LogPath)}) 150}
    Add-DialogButton 'Open Project Folder' ({Start-Process explorer.exe -ArgumentList @($ProjectRoot)}) 170
    Add-DialogButton 'Copy Corrective Task' ({[Windows.Forms.Clipboard]::SetText($info.Task)}) 180
    Add-DialogButton $(if($key-eq'tests'){'Run Tests Again'}else{'Run Again'}) ({Invoke-CorrectiveRun $info.Run;$dialog.Close()}) 150
    Add-DialogButton 'Close' ({$dialog.Close()}) 100;$dialog.Add_KeyDown({param($sender,$e)if($e.KeyCode-eq'Escape'){$dialog.Close()}})
    [void]$dialog.ShowDialog($form);$dialog.Dispose()
}
function Show-CheckpointBlockers($blockers){
    $dialog=New-Object Windows.Forms.Form;$dialog.Text='Full Checkpoint Push Blocked';$dialog.Size=New-Object Drawing.Size(900,680);$dialog.MinimumSize=New-Object Drawing.Size(720,520);$dialog.StartPosition='CenterParent';$dialog.Font=New-Object Drawing.Font('Segoe UI',11)
    $layout=New-Object Windows.Forms.TableLayoutPanel;$layout.Dock='Fill';$layout.Padding=New-Object Windows.Forms.Padding(16);$layout.RowCount=3;$layout.ColumnCount=1;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize')))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent',100)))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize')))|Out-Null;$dialog.Controls.Add($layout)
    $label=New-Object Windows.Forms.Label;$label.AutoSize=$true;$label.Font=New-Object Drawing.Font('Segoe UI Semibold',15);$label.Text="Checkpoint push blocked by $($blockers.Count) condition(s)";$layout.Controls.Add($label)
    $body=New-Object Windows.Forms.TextBox;$body.Multiline=$true;$body.ReadOnly=$true;$body.ScrollBars='Both';$body.WordWrap=$true;$body.Dock='Fill';$blockerLines=for($i=0;$i-lt$blockers.Count;$i++){"$($i+1). $($blockers[$i].Name): $($blockers[$i].Status)`r`n$($blockers[$i].Explanation)`r`nCorrective action: $($blockers[$i].Actions[0])"};$body.Text=$blockerLines-join"`r`n`r`n";$layout.Controls.Add($body)
    $buttons=New-Object Windows.Forms.FlowLayoutPanel;$buttons.AutoSize=$true;$buttons.Dock='Fill';$buttons.WrapContents=$true;foreach($item in $blockers){$b=New-Object Windows.Forms.Button;$b.Text="Open $($item.Name) Details";$b.AutoSize=$true;$b.MinimumSize=New-Object Drawing.Size(160,40);$tileKey=$item.Key;$b.Add_Click({Show-StatusDetails $tileKey}.GetNewClosure());$buttons.Controls.Add($b)|Out-Null};$close=New-Object Windows.Forms.Button;$close.Text='Close';$close.MinimumSize=New-Object Drawing.Size(100,40);$close.Add_Click({$dialog.Close()});$buttons.Controls.Add($close)|Out-Null;$layout.Controls.Add($buttons);[void]$dialog.ShowDialog($form);$dialog.Dispose()
}

$form=New-Object Windows.Forms.Form
$form.Text="Radio Outdoors Project Manager";$form.Size=New-Object Drawing.Size(1180,800);$form.StartPosition="CenterScreen";$form.Font=New-Object Drawing.Font("Segoe UI",10)
$title=New-Object Windows.Forms.Label;$title.Text="RADIO OUTDOORS - DEVELOPMENT CONTROL PANEL";$title.Font=New-Object Drawing.Font("Segoe UI Semibold",16);$title.AutoSize=$true;$title.Location=New-Object Drawing.Point(18,12);$form.Controls.Add($title)
$overall=New-Object Windows.Forms.Label;$overall.Text="Checking...";$overall.Font=New-Object Drawing.Font("Segoe UI Semibold",13);$overall.AutoSize=$true;$overall.Location=New-Object Drawing.Point(760,18);$form.Controls.Add($overall)
$proj=New-Object Windows.Forms.Label;$proj.Text=$ProjectRoot;$proj.AutoSize=$true;$proj.ForeColor="DimGray";$proj.Location=New-Object Drawing.Point(20,46);$form.Controls.Add($proj)

$grid=New-Object Windows.Forms.TableLayoutPanel;$grid.Location=New-Object Drawing.Point(15,78);$grid.Size=New-Object Drawing.Size(1135,470);$grid.ColumnCount=4;$grid.RowCount=5
0..3|%{$grid.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle("Percent",25)))}
0..4|%{$grid.RowStyles.Add((New-Object Windows.Forms.RowStyle("Percent",20)))}
$form.Controls.Add($grid)
$labels=@{};$details=@{};$panels=@{};$last=@{};$script:TileNames=@{}
function Card($key,$name,$col,$row){
    $p=New-Object Windows.Forms.Panel;$p.Dock="Fill";$p.Margin=New-Object Windows.Forms.Padding(5);$p.BorderStyle="FixedSingle";$p.BackColor="White"
    $h=New-Object Windows.Forms.Label;$h.Text=$name;$h.AutoSize=$true;$h.ForeColor="DimGray";$h.Location=New-Object Drawing.Point(8,7);$p.Controls.Add($h)
    $v=New-Object Windows.Forms.Label;$v.Text="...";$v.Font=New-Object Drawing.Font("Segoe UI Semibold",11);$v.AutoSize=$true;$v.Location=New-Object Drawing.Point(8,30);$p.Controls.Add($v)
    $d=New-Object Windows.Forms.Label;$d.Text="";$d.AutoEllipsis=$true;$d.Size=New-Object Drawing.Size(250,18);$d.Location=New-Object Drawing.Point(8,56);$d.ForeColor="Gray";$p.Controls.Add($d)
    $tileKey=$key;$openTile={if($last[$tileKey]-and$last[$tileKey].State-in@('red','yellow')){Show-StatusDetails $tileKey}}.GetNewClosure();$p.Add_Click($openTile);$h.Add_Click($openTile);$v.Add_Click($openTile);$d.Add_Click($openTile)
    $labels[$key]=$v;$details[$key]=$d;$panels[$key]=$p;$script:TileNames[$key]=$name;$grid.Controls.Add($p,$col,$row)
}
$defs=@(
@("branch","Git branch",0,0),@("tree","Working tree",1,0),@("sync","GitHub sync",2,0),@("commit","Last commit",3,0),
@("django","Django check",0,1),@("migrations","Migrations",1,1),@("missing","Missing migrations",2,1),@("tests","Tests",3,1),
@("server","Port 8000 / Server",0,2),@("leftovers","Codex leftovers",1,2),@("python","Python",2,2),@("djver","Django version",3,2),
@("secrets","Secrets protected",0,3),@("db","Database backup",1,3),@("media","Media backup",2,3),@("disk","Disk space",3,3),
@("repo","Repository",0,4),@("venv","Virtual env",1,4),@("logs","Manager logs",2,4),@("safe","Checkpoint safety",3,4))
$defs|%{Card $_[0] $_[1] $_[2] $_[3]}

$flow=New-Object Windows.Forms.FlowLayoutPanel;$flow.Location=New-Object Drawing.Point(18,558);$flow.Size=New-Object Drawing.Size(1130,90);$flow.WrapContents=$true;$form.Controls.Add($flow)
function Btn($text,$code,$w=135){$b=New-Object Windows.Forms.Button;$b.Text=$text;$b.Width=$w;$b.Height=36;$b.Margin=New-Object Windows.Forms.Padding(4);$b.Add_Click($code);$flow.Controls.Add($b)}
Btn "Refresh Status" {Refresh}
Btn "Full Checkpoint & Push" {Checkpoint $false} 180
Btn "Quick Checkpoint" {Checkpoint $true} 145
Btn "Run Tests" {RunTests} 110
Btn "Apply Migrations" {ApplyMigrations} 140
Btn "Start Server" {StartServer;Start-Sleep -Milliseconds 500;Refresh} 115
Btn "Stop Server" {StopServer;Start-Sleep -Milliseconds 500;Refresh} 115
Btn "Backup Database" {BackupDB;Refresh} 140
Btn "Backup Media" {BackupMedia;Refresh} 125
Btn "Project Folder" {Start-Process explorer.exe $ProjectRoot} 120
Btn "Logs" {Start-Process explorer.exe $LogDir} 90

$detail=New-Object Windows.Forms.TextBox;$detail.Location=New-Object Drawing.Point(18,657);$detail.Size=New-Object Drawing.Size(1130,90);$detail.Multiline=$true;$detail.ReadOnly=$true;$detail.ScrollBars="Vertical";$detail.Font=New-Object Drawing.Font("Consolas",9);$form.Controls.Add($detail)

function SetM($k,$s){$last[$k]=$s;$labels[$k].Text=$s.Text;$details[$k].Text=(($s.Detail -split"`r?`n")[0]);$labels[$k].ForeColor=switch($s.State){"green"{"DarkGreen"}"yellow"{"DarkOrange"}"red"{"Firebrick"}default{"Black"}};$cursor=if($s.State-in@('red','yellow')){[Windows.Forms.Cursors]::Hand}else{[Windows.Forms.Cursors]::Default};$panels[$k].Cursor=$cursor;$labels[$k].Cursor=$cursor;$details[$k].Cursor=$cursor}
function Refresh(){
    $form.Cursor="WaitCursor"
    try{
        SetM "branch" (GitBranch);SetM "tree" (Tree);SetM "sync" (Sync);SetM "commit" (LastCommit)
        SetM "django" (DjCheck);SetM "migrations" (Migrations);SetM "missing" (MissingMig);SetM "tests" (Tests)
        SetM "server" (Server);SetM "leftovers" (Leftovers);SetM "python" (PythonVer);SetM "djver" (DjangoVer)
        SetM "secrets" (Secrets);SetM "db" (DbBackup);SetM "media" (MediaBackup);SetM "disk" (Disk)
        SetM "repo" (Status "green" (Split-Path $ProjectRoot -Leaf) $ProjectRoot)
        SetM "venv" (Status ($(if(Py){"green"}else{"red"})) ($(if(Py){".venv found"}else{".venv missing"})) (Py))
        SetM "logs" (Status "green" "Available" $LogDir)
        $blocked=@($last.GetEnumerator()|?{Test-StatusBlocksPush $_.Key $_.Value}).Count-gt0
        SetM "safe" (Status ($(if($blocked){"red"}elseif($last["tree"].State-eq"yellow"){"yellow"}else{"green"})) ($(if($blocked){"Blocked"}elseif($last["tree"].State-eq"yellow"){"Changes ready"}else{"Safe / clean"})) "")
        $reds=@($last.Values|?{$_.State-eq"red"}).Count;$y=@($last.Values|?{$_.State-eq"yellow"}).Count
        $overall.Text=if($reds){"DO NOT PUSH - $reds blocking issue(s)"}elseif($y){"ATTENTION REQUIRED - $y item(s)"}else{"READY"}
        $overall.ForeColor=if($reds){"Firebrick"}elseif($y){"DarkOrange"}else{"DarkGreen"}
        $detail.Text=($last.GetEnumerator()|sort Name|%{"$($_.Name): $($_.Value.Text)`r`n$($_.Value.Detail)"})-join"`r`n"
        Log "Dashboard refreshed: $($overall.Text)"
    }finally{$form.Cursor="Default"}
}
$form.Add_Shown({Refresh})
[void]$form.ShowDialog()
