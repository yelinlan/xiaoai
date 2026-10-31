$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut('C:\Users\Administrator\Desktop\快捷启动原神.lnk')
Write-Output ("目标: " + $s.TargetPath)
Write-Output ("参数: " + $s.Arguments)
Write-Output ("工作目录: " + $s.WorkingDirectory)
