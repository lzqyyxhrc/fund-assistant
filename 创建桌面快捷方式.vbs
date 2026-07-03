' 一键在桌面创建"基金助手"快捷方式（带图标）
' 双击运行本文件即可
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

strPath    = fso.GetParentFolderName(WScript.ScriptFullName)
strDesktop = WshShell.SpecialFolders("Desktop")

' ------- 启动快捷方式 -------
Set link1 = WshShell.CreateShortcut(strDesktop & "\基金智能定投助手.lnk")
link1.TargetPath       = strPath & "\启动基金助手.vbs"
link1.WorkingDirectory = strPath
link1.WindowStyle      = 1
link1.Description      = "启动 基金智能定投再平衡（Streamlit）"
' 使用系统自带图标（Windows Shell32.dll 中的钱袋/图表图标）
' 索引 137 = 蓝色图表；44 = 钱袋；13 = 硬币
link1.IconLocation     = "%SystemRoot%\System32\SHELL32.dll,137"
link1.Save

' ------- 停止快捷方式 -------
Set link2 = WshShell.CreateShortcut(strDesktop & "\停止基金助手.lnk")
link2.TargetPath       = strPath & "\停止基金助手.bat"
link2.WorkingDirectory = strPath
link2.WindowStyle      = 1
link2.Description      = "停止 基金智能定投助手（Streamlit）"
link2.IconLocation     = "%SystemRoot%\System32\SHELL32.dll,131"
link2.Save

MsgBox "桌面快捷方式已创建：" & vbCrLf & vbCrLf & _
       "① 基金智能定投助手（启动）" & vbCrLf & _
       "② 停止基金助手", _
       64, "创建成功"
