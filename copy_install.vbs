Set objShell = CreateObject("Shell.Application")
Set objFSO = CreateObject("Scripting.FileSystemObject")

src = "C:\Users\tchic\lexio-player\dist\LexioStudyPlayer"
dst = "C:\Program Files\Lexio Study Player"

' Kill any running player
On Error Resume Next
CreateObject("WScript.Shell").Run "taskkill /f /im LexioStudyPlayer.exe", 0, True
On Error Goto 0

WScript.Sleep 1000

' Delete old installation
If objFSO.FolderExists(dst) Then
    On Error Resume Next
    objFSO.DeleteFolder dst, True
    On Error Goto 0
End If

WScript.Sleep 500

' Copy new build
objFSO.CopyFolder src, dst, True

WScript.Sleep 500

' Run the player
CreateObject("WScript.Shell").Run chr(34) & dst & "\LexioStudyPlayer.exe" & chr(34), 1, False

MsgBox "Lexio Study Player 3.9.6 installed!", vbInformation, "Instalado"
