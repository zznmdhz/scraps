' Scraps launcher - double-click to start, no console window.
' Edit CANDIDATES below if your Python lives somewhere unusual.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
app = appDir & "\Scraps.pyw"
candidates = Array( _
  "C:\Python312\pythonw.exe", "C:\Python311\pythonw.exe", "C:\Python310\pythonw.exe", _
  "C:\Python313\pythonw.exe", "C:\Python314\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python311\pythonw.exe", _
  sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python310\pythonw.exe" )
py = ""
For Each c In candidates
  If fso.FileExists(c) Then py = c : Exit For
Next
If py = "" Then
  MsgBox "Python not found. Install Python 3 or edit this .vbs.", 16, "Scraps"
Else
  sh.Run """" & py & """ """ & app & """", 0, False
End If
