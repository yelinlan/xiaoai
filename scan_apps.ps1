$sh = New-Object -ComObject WScript.Shell
$dirs = @(
  "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
  "$env:AppData\Microsoft\Windows\Start Menu\Programs"
)
$seen = @{}
Get-ChildItem $dirs -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    $t = $sh.CreateShortcut($_.FullName).TargetPath
    if ($t -and $t.EndsWith('.exe') -and (Test-Path $t) -and -not $seen[$t.ToLower()]) {
      $seen[$t.ToLower()] = 1
      Write-Output ($_.BaseName + '|' + $t)
    }
  } catch {}
}
