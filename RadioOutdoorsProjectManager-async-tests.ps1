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
    $p=New-Object System.Diagnostics.Process; $p.StartInfo=$psi; [void]$p.Start();$outTask=$p.StandardOutput.ReadToEndAsync();$errTask=$p.StandardError.ReadToEndAsync()
    if(-not $p.WaitForExit($timeout*1000)){$timedOutPid=$p.Id;try{Start-Process taskkill.exe -ArgumentList '/PID',"$timedOutPid",'/T','/F' -Wait -WindowStyle Hidden -ErrorAction Stop|Out-Null}catch{try{$p.Kill()}catch{}};if(!$p.HasExited){[void]$p.WaitForExit(15000)};return @{Exit=124;TimedOut=$true;ProcessId=$timedOutPid;Out=$outTask.GetAwaiter().GetResult().TrimEnd();Err=("Timed out after $timeout seconds; process tree PID $timedOutPid was terminated and awaited.`r`n"+$errTask.GetAwaiter().GetResult()).Trim()}}
    return @{Exit=$p.ExitCode;Out=$outTask.GetAwaiter().GetResult().TrimEnd();Err=$errTask.GetAwaiter().GetResult().Trim()}
}
function Py(){ $p=Join-Path $ProjectRoot ".venv\Scripts\python.exe"; if(Test-Path $p){$p}else{$null} }
function Django($args,[int]$timeout=120){$p=Py;if(!$p){return @{Exit=9001;Out="";Err=".venv Python missing"}};Run-Cmd "`"$p`" manage.py $args" $timeout}
function Log($m){Add-Content (Join-Path $LogDir ("manager-"+(Get-Date -Format "yyyyMMdd")+".log")) "[$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")] $m"}
function Status($state,$text,$detail=""){[pscustomobject]@{State=$state;Text=$text;Detail=$detail}}

function GitBranch(){ $r=Run-Cmd "git branch --show-current" 20; if($r.Exit-eq0){Status ($(if($r.Out-eq"main"){"green"}else{"yellow"})) $r.Out "Expected main"}else{Status "red" "Git failed" $r.Err}}
function Tree(){ $r=Run-Cmd "git status --porcelain" 30;if($r.Exit-ne0){return Status "red" "Git failed" $r.Err};if(!$r.Out){return Status "green" "Clean" "No uncommitted changes"};$n=@($r.Out -split "`r?`n"|?{$_}).Count;Status "yellow" "$n changed/new" $r.Out}
function Sync(){ $f=Run-Cmd "git fetch --quiet origin" 45;if($f.Exit-ne0){return Status "yellow" "Fetch unavailable" $f.Err};$r=Run-Cmd "git rev-list --left-right --count HEAD...origin/main" 20;if($r.Exit-ne0){return Status "yellow" "Unknown" $r.Err};$x=$r.Out -split '\s+';$a=[int]$x[0];$b=[int]$x[1];$s=if($b-gt0){"red"}elseif($a-gt0){"yellow"}else{"green"};Status $s "Ahead $a / Behind $b" "origin/main"}
function LastCommit(){ $r=Run-Cmd 'git log -1 --format="%h %ad %s" --date=format:"%Y-%m-%d %H:%M"' 20;if($r.Exit-eq0){Status "green" ($r.Out.Substring(0,[Math]::Min(32,$r.Out.Length))) $r.Out}else{Status "yellow" "Unavailable" $r.Err}}
function DjCheck(){ $r=Django "check" 90;if($r.Exit-eq0){Status "green" "Passed" ($r.Out+" "+$r.Err).Trim()}else{Status "red" "Failed" ($r.Out+"`r`n"+$r.Err).Trim()}}
function Migrations(){ $r=Django "showmigrations --plan" 90;if($r.Exit-ne0){return Status "red" "Check failed" $r.Err};$u=@($r.Out -split "`r?`n"|?{$_ -match '^\s*\[\s\]'});if($u.Count){Status "yellow" "$($u.Count) unapplied" ($u-join"`r`n")}else{Status "green" "All applied" ""}}
function MissingMig(){ $r=Django "makemigrations --check --dry-run" 90;if($r.Exit-eq0){Status "green" "None" ($r.Out+" "+$r.Err).Trim()}else{Status "red" "Migration needed" ($r.Out+"`r`n"+$r.Err).Trim()}}
function PythonVer(){ $p=Py;if(!$p){return Status "red" ".venv missing" ""};$r=Run-Cmd "`"$p`" --version" 15;if($r.Exit-eq0){Status "green" $r.Out $p}else{Status "red" "Python failed" $r.Err}}
function DjangoVer(){ $p=Py;if(!$p){return Status "red" "Unavailable" ""};$r=Run-Cmd "`"$p`" -m django --version" 15;if($r.Exit-eq0){Status "green" "Django $($r.Out)" ""}else{Status "red" "Unavailable" $r.Err}}
function Listeners(){
    $a=@()
    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue|%{
        $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue
        $a += [pscustomobject]@{PID=$_.OwningProcess;Cmd=if($p){$p.CommandLine}else{""};RO=($p.CommandLine -like "*radiooutdoors-platform*" -and $p.CommandLine -like "*manage.py*runserver*")}
    };,$a
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

function BackupDB(){ $db=Join-Path $ProjectRoot "db.sqlite3";if(!(Test-Path $db)){[Windows.Forms.MessageBox]::Show("db.sqlite3 not found.")|Out-Null;return};$to=Join-Path $BackupDir ("db-"+(Get-Date -Format "yyyyMMdd-HHmmss")+".sqlite3");Copy-Item $db $to;Log "Database backup: $to";[Windows.Forms.MessageBox]::Show("Backup created:`r`n$to")|Out-Null}
function BackupMedia(){ $m=Join-Path $ProjectRoot "media";if(!(Test-Path $m)){[Windows.Forms.MessageBox]::Show("No media folder.")|Out-Null;return};$to=Join-Path $BackupDir ("media-"+(Get-Date -Format "yyyyMMdd-HHmmss")+".zip");Compress-Archive (Join-Path $m "*") $to -Force;Log "Media backup: $to";[Windows.Forms.MessageBox]::Show("Backup created:`r`n$to")|Out-Null}
function StartServer(){if(@(Listeners).Count){[Windows.Forms.MessageBox]::Show("Port 8000 is already occupied. Server not started.")|Out-Null;return};$p=Py;if(!$p){[Windows.Forms.MessageBox]::Show(".venv Python missing.")|Out-Null;return};$cmd="cd /d `"$ProjectRoot`" && `"$p`" manage.py runserver 127.0.0.1:8000 --noreload";Start-Process cmd.exe -ArgumentList "/k",$cmd -WorkingDirectory $ProjectRoot;Log "Server started"}
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

function Remove-TimedOutStagingLock($stagingStarted){
    $gitDir=Join-Path $ProjectRoot '.git';$lockPath=Join-Path $gitDir 'index.lock';$indexPath=Join-Path $gitDir 'index';$deadline=(Get-Date).AddSeconds(10)
    do{$gitProcesses=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|?{$_.Name-match'^(git|git-lfs)(\.exe)?$'});if(!$gitProcesses.Count){break};Start-Sleep -Milliseconds 200}while((Get-Date)-lt$deadline)
    if($gitProcesses.Count){return "Lock not removed: Git process(es) still active: $($gitProcesses.ProcessId-join', ')"}
    $markers=@(@('rebase-apply','rebase-merge','MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','BISECT_LOG','BISECT_START','sequencer')|?{Test-Path -LiteralPath (Join-Path $gitDir $_)});if($markers.Count){return "Lock not removed: active Git operation marker(s): $($markers-join', ')"}
    if(!(Test-Path -LiteralPath $lockPath)){return 'No index lock remained after the terminated staging process.'};$lock=Get-Item -LiteralPath $lockPath
    if($lock.Length-ne0-or$lock.LastWriteTime-lt$stagingStarted.AddSeconds(-2)){return "Lock not removed: it was not identified as the zero-byte lock created by this staging attempt ($($lock.LastWriteTime))."}
    if(!(Test-Path -LiteralPath $indexPath)){return 'Lock not removed: .git/index could not be confirmed.'};$expected=[IO.Path]::GetFullPath((Join-Path $gitDir 'index.lock'));if($lock.FullName-ne$expected){return 'Lock not removed: resolved lock path did not match .git/index.lock.'}
    try{Remove-Item -LiteralPath $expected -Force -ErrorAction Stop}catch{return "Stale lock removal failed: $($_.Exception.Message)"};if(Test-Path -LiteralPath $expected){return 'Stale lock removal was attempted but the lock still exists.'};'Confirmed no Git process or operation owned the lock; removed the stale .git/index.lock and preserved .git/index.'
}

function Checkpoint([bool]$quick=$false){
    $sec=Secrets;if($sec.State-eq"red"){[Windows.Forms.MessageBox]::Show($sec.Detail,"DO NOT PUSH")|Out-Null;return}
    if(!$quick){
        $d=DjCheck;if($d.State-eq"red"){[Windows.Forms.MessageBox]::Show($d.Detail,"Django Check Failed")|Out-Null;return}
        $m=MissingMig;if($m.State-eq"red"){[Windows.Forms.MessageBox]::Show($m.Detail,"Migration Required")|Out-Null;return}
        $a=Migrations;if($a.State-ne"green"){[Windows.Forms.MessageBox]::Show("Unapplied migrations exist.","Checkpoint Blocked")|Out-Null;return}
        $x=Run-Cmd "git diff --check" 60;if($x.Exit-ne0){[Windows.Forms.MessageBox]::Show(($x.Out+"`r`n"+$x.Err),"Diff Check Failed")|Out-Null;return}
    }
    $s=Run-Cmd "git status --short --untracked-files=all" 30;if(!$s.Out){[Windows.Forms.MessageBox]::Show("Working tree is clean.")|Out-Null;return}
    $intentional=@();$excluded=@()
    foreach($line in @($s.Out -split "`r?`n"|?{$_})){
        # Preserve a leading period: porcelain columns 0-1 are status and
        # column 2 is the separator, so only trailing whitespace is trimmed.
        $path=if($line.Length-ge4){$line.Substring(3).TrimEnd().Replace('\','/')}else{''};if($path.StartsWith('./')){$path=$path.Substring(2)};if($path-match' -> '){$path=($path-split' -> ',2)[1]}
        $leaf=[IO.Path]::GetFileName($path);$reason=$null
        if(!$path-or($path.StartsWith('"')-and$path.EndsWith('"'))){$reason='path could not be safely decoded'}
        elseif($leaf-match'(?i)\.bak$'){$reason='backup file (*.bak)'}
        elseif($leaf-match'(?i)^RO-.*\.ps1$'){$reason='local RO tool script'}
        elseif($leaf-match'(?i)(^RO-.*|source[-_ ]collection.*)\.zip$'-or$leaf-match'(?i)\.zip$'){$reason='generated/archive ZIP'}
        elseif($path-match'(?i)(^|/)(local-backups|project-manager-logs|media|media[-_ ]?backups?)(/|$)'){$reason='local backup, log, or media file'}
        elseif($leaf-match'(?i)^(db\.sqlite3|.*\.(sqlite3?|db))$'){$reason='database file'}
        elseif($path-match'(?i)(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|htmlcov|tmp|temp)(/|$)'-or$leaf-match'(?i)\.(pyc|pyo|tmp|temp|swp)$'){$reason='cache or temporary/generated file'}
        elseif($leaf-match'(?i)^\.env($|\.)'-or$leaf-match'(?i)(api[-_]?key|secret|credential|password).*\.(txt|key|pem|json)$'){$reason='secret or API-key file'}
        $rootGitIgnore=[string]::Equals($path,'.gitignore',[StringComparison]::OrdinalIgnoreCase)
        $approved=($rootGitIgnore-or$leaf-in@('manage.py','requirements.txt','README.txt','RadioOutdoorsProjectManager.ps1','RadioOutdoorsProjectManager-async-tests.ps1','RadioOutdoorsProjectManager-classification-tests.ps1','Start-Project-Manager.bat','Start-RadioOutdoors-Project-Manager.bat')-or($path-match'^(adventures|backend|core|static|templates|docs|tools)/'-and$leaf-match'(?i)\.(py|html|css|js|json|md|txt|bat|ps1|yml|yaml|toml)$'))
        if(!$reason-and!$approved){$reason='not an approved source/config/migration/test/template/static path'}
        $item=[pscustomobject]@{Status=$line.Substring(0,[Math]::Min(2,$line.Length));Path=$path;Reason=$reason};if($reason){$excluded+=$item}else{$intentional+=$item}
    }
    if(!$intentional.Count){[Windows.Forms.MessageBox]::Show("No intentional files remain after exclusions. No commit was created.","Nothing to Checkpoint")|Out-Null;return}
    $dialog=New-Object Windows.Forms.Form;$dialog.Text='Confirm Full Checkpoint Push';$work=[Windows.Forms.Screen]::PrimaryScreen.WorkingArea;$dialog.Size=New-Object Drawing.Size([Math]::Min(960,[int]($work.Width*.88)),[Math]::Min(760,[int]($work.Height*.88)));$dialog.StartPosition='CenterScreen';$dialog.KeyPreview=$true
    $layout=New-Object Windows.Forms.TableLayoutPanel;$layout.Dock='Fill';$layout.Padding=New-Object Windows.Forms.Padding(12);$layout.RowCount=4;$layout.ColumnCount=1;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize')))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent',50)))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent',50)))|Out-Null;$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle('AutoSize')))|Out-Null;$dialog.Controls.Add($layout)
    $notice=New-Object Windows.Forms.Label;$notice.AutoSize=$true;$notice.Text="Full Checkpoint Push commits intentional files and pushes to GitHub (origin/main). Excluded files are not staged.";$layout.Controls.Add($notice)
    foreach($group in @(@('Intentional files to checkpoint',$intentional,$false),@('Excluded files (not staged)',$excluded,$true))){$box=New-Object Windows.Forms.TextBox;$box.Multiline=$true;$box.ReadOnly=$true;$box.WordWrap=$false;$box.ScrollBars='Both';$box.Dock='Fill';$box.Text=(($group[1]|%{if($group[2]){"$($_.Status)  $($_.Path)  [$($_.Reason)]"}else{"$($_.Status)  $($_.Path)"}})-join"`r`n");$container=New-Object Windows.Forms.GroupBox;$container.Text="$($group[0]) ($($group[1].Count))";$container.Dock='Fill';$container.Controls.Add($box);$layout.Controls.Add($container)}
    $buttons=New-Object Windows.Forms.FlowLayoutPanel;$buttons.AutoSize=$true;$buttons.Dock='Fill';$buttons.FlowDirection='RightToLeft';$cancel=New-Object Windows.Forms.Button;$cancel.Text='Cancel';$cancel.MinimumSize=New-Object Drawing.Size(110,36);$cancel.DialogResult='Cancel';$confirm=New-Object Windows.Forms.Button;$confirm.Text='Checkpoint and Push';$confirm.MinimumSize=New-Object Drawing.Size(165,36);$confirm.Add_Click({$dialog.DialogResult='OK';$dialog.Close()});$buttons.Controls.Add($cancel);$buttons.Controls.Add($confirm);$layout.Controls.Add($buttons);$dialog.CancelButton=$cancel;$dialog.AcceptButton=$null;$dialog.Add_Shown({$cancel.Select()});$dialog.Add_KeyDown({param($sender,$e)if($e.KeyCode-eq'Escape'){$cancel.PerformClick();$e.SuppressKeyPress=$true}elseif($e.KeyCode-eq'Enter'){if($confirm.Focused){$confirm.PerformClick()}else{$cancel.PerformClick()};$e.SuppressKeyPress=$true}})
    try{$confirmed=($dialog.ShowDialog()-eq'OK')}finally{$dialog.Dispose()};if(!$confirmed){return}
    $reset=Run-Cmd "git reset" 30;if($reset.Exit-ne0){[Windows.Forms.MessageBox]::Show($reset.Err,"Could Not Prepare Staging")|Out-Null;return}
    $pathspec=Join-Path ([IO.Path]::GetTempPath()) ("radiooutdoors-stage-"+[guid]::NewGuid().ToString('N')+'.paths')
    $displayCommand='git add --pathspec-from-file=<temporary-approved-path-list> --pathspec-file-nul';Log "Staging started: $($intentional.Count) approved paths; command: $displayCommand";foreach($item in $intentional){Log "Staging approved path: $($item.Path)"}
    $stagingStarted=Get-Date;try{$stream=New-Object IO.MemoryStream;foreach($item in $intentional){$bytes=[Text.Encoding]::UTF8.GetBytes($item.Path);$stream.Write($bytes,0,$bytes.Length);$stream.WriteByte(0)};[IO.File]::WriteAllBytes($pathspec,$stream.ToArray());$stream.Dispose();$a=Run-Cmd "git add --pathspec-from-file=`"$pathspec`" --pathspec-file-nul" 300;if($a.Exit-eq124){$a.LockCleanup=Remove-TimedOutStagingLock $stagingStarted;Log "Timed-out staging cleanup: $($a.LockCleanup)"}}finally{if(Test-Path -LiteralPath $pathspec){Remove-Item -LiteralPath $pathspec -Force}}
    $a.Command=$displayCommand;$a.Paths=@($intentional|%{$_.Path});$stagedResult=Run-Cmd 'git diff --cached --name-only' 60;$staged=@($stagedResult.Out-split"`r?`n"|?{$_});Log "Staging finished: exit=$($a.Exit); approved=$($intentional.Count); staged=$($staged.Count)"
    if($a.Exit-ne0){Log "Staging failed: command=$displayCommand; affected paths=$($a.Paths-join', '); staged before failure=$($staged-join', '); cleanup=$($a.LockCleanup); error=$($a.Err)";[Windows.Forms.MessageBox]::Show("Command: $displayCommand`r`nAffected paths: all $($a.Paths.Count) approved paths (listed in the Project Manager log).`r`nStaged before failure: $(if($staged.Count){$staged-join', '}else{'(none)'})`r`nLock cleanup: $($a.LockCleanup)`r`n`r`n$($a.Err)`r`nCommit and push were blocked.","Staging Failed")|Out-Null;return}
    $approved=@($intentional|%{$_.Path.Replace('\','/')}|sort -Unique);$actual=@($staged|%{$_.Replace('\','/')}|sort -Unique);$missing=@(Compare-Object $approved $actual -PassThru|?{$_.SideIndicator-eq'<='});$unexpected=@(Compare-Object $approved $actual -PassThru|?{$_.SideIndicator-eq'=>'})
    if($stagedResult.Exit-ne0-or$missing.Count-or$unexpected.Count){Log "Staged-set mismatch; commit blocked. Missing=$($missing-join', '); unexpected=$($unexpected-join', ')";$reconcile=Run-Cmd 'git reset' 60;Log "Index reconciled after staged-set mismatch: git reset exit=$($reconcile.Exit); working-tree content preserved";[Windows.Forms.MessageBox]::Show("Staged files do not exactly match the approved list. Commit and push were blocked, and the index was cleared without changing working-tree files.`r`nMissing: $($missing-join', ')`r`nUnexpected: $($unexpected-join', ')","Staging Verification Failed")|Out-Null;return}
    Log "Staged-set verification passed: $($actual.Count) paths exactly match the approved list"
    $sec=Secrets;if($sec.State-eq"red"){Run-Cmd "git reset" 30|Out-Null;[Windows.Forms.MessageBox]::Show($sec.Detail+"`r`n`r`nStaging reset.","DO NOT PUSH")|Out-Null;return}
    $x=Run-Cmd "git diff --cached --check" 60;if($x.Exit-ne0){Run-Cmd "git reset" 30|Out-Null;[Windows.Forms.MessageBox]::Show("Staged diff check failed; staging reset.")|Out-Null;return}
    $msg="Radio Outdoors checkpoint - "+(Get-Date -Format "yyyy-MM-dd HH:mm")
    $c=Run-Cmd "git commit -m `"$msg`"" 180;if($c.Exit-ne0){[Windows.Forms.MessageBox]::Show(($c.Out+"`r`n"+$c.Err),"Commit Failed")|Out-Null;return}
    $p=Run-Cmd "git push origin main" 300;if($p.Exit-ne0){[Windows.Forms.MessageBox]::Show(($p.Out+"`r`n"+$p.Err),"Push Failed")|Out-Null;return}
    Log "Checkpoint pushed: $msg";[Windows.Forms.MessageBox]::Show("Checkpoint pushed.`r`n$msg","Success")|Out-Null;Refresh
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
$labels=@{};$details=@{};$last=@{}
function Card($key,$name,$col,$row){
    $p=New-Object Windows.Forms.Panel;$p.Dock="Fill";$p.Margin=New-Object Windows.Forms.Padding(5);$p.BorderStyle="FixedSingle";$p.BackColor="White"
    $h=New-Object Windows.Forms.Label;$h.Text=$name;$h.AutoSize=$true;$h.ForeColor="DimGray";$h.Location=New-Object Drawing.Point(8,7);$p.Controls.Add($h)
    $v=New-Object Windows.Forms.Label;$v.Text="...";$v.Font=New-Object Drawing.Font("Segoe UI Semibold",11);$v.AutoSize=$true;$v.Location=New-Object Drawing.Point(8,30);$p.Controls.Add($v)
    $d=New-Object Windows.Forms.Label;$d.Text="";$d.AutoEllipsis=$true;$d.Size=New-Object Drawing.Size(250,18);$d.Location=New-Object Drawing.Point(8,56);$d.ForeColor="Gray";$p.Controls.Add($d)
    $labels[$key]=$v;$details[$key]=$d;$grid.Controls.Add($p,$col,$row)
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

function SetM($k,$s){$last[$k]=$s;$labels[$k].Text=$s.Text;$details[$k].Text=(($s.Detail -split"`r?`n")[0]);$labels[$k].ForeColor=switch($s.State){"green"{"DarkGreen"}"yellow"{"DarkOrange"}"red"{"Firebrick"}default{"Black"}}}
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
        $blocked=($last["secrets"].State-eq"red" -or $last["django"].State-eq"red" -or $last["missing"].State-eq"red")
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
