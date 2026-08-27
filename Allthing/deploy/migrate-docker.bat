@echo off
cd /d "%~dp0"
echo [start] %date% %time% > robocopy.log
robocopy "C:\Users\13714\AppData\Local\Docker\wsl" "D:\ZZB\work\Linux数据库\wsl" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL >> robocopy.log 2>&1
echo [done] exit=%errorlevel% >> robocopy.log
