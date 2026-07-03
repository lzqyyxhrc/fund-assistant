' 基金智能定投助手 - 静默启动（无黑色控制台窗口）
' 双击此文件即可启动 Streamlit，浏览器自动打开
Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' 0 = 隐藏窗口，False = 不等待返回
WshShell.Run "cmd /c cd /d """ & strPath & """ && python -m streamlit run project\app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false", 0, False
' 等 3 秒让服务起来，再打开浏览器
WScript.Sleep 3000
WshShell.Run "http://localhost:8501", 1, False
