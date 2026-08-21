Option Explicit
Dim shell, fso, root, pythonw, app, updater, updateCommand
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(root, ".runtime\venv\Scripts\pythonw.exe")
app = fso.BuildPath(root, "apps\plugin-station\app.py")
updater = fso.BuildPath(root, "scripts\update-from-origin.ps1")
If Not fso.FileExists(pythonw) Then
  MsgBox "Run scripts\bootstrap.ps1 first.", 48, "Local Plugin Station"
  WScript.Quit 1
End If
If fso.FileExists(updater) Then
  updateCommand = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & updater & Chr(34) & " -Mode Apply"
  shell.Run updateCommand, 0, True
End If
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & app & Chr(34), 0, False
