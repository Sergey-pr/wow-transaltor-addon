' Launches the overlay with no console window at all.
'
' run.bat cannot do this: Windows creates cmd's console before the script gets
' a say, so a .bat always flashes for a moment. wscript is a GUI host and never
' opens one, which also means a startup failure would be silent -- hence the
' message box on the way out.

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
script = """" & here & "\main.py"""

On Error Resume Next
shell.Run "pythonw " & script, 0, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run "pyw " & script, 0, False
End If
If Err.Number <> 0 Then
    MsgBox "Could not start Python." & vbCrLf & vbCrLf & _
           "Install Python 3 from python.org and make sure it is on PATH.", _
           16, "WoW Chat Translator"
End If
