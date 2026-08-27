@echo off
cd /d "%~dp0"
echo [start] %date% %time% >> pull.log
docker compose -f docker-compose.milvus.yml pull >> pull.log 2>&1
echo [done] exit=%errorlevel% >> pull.log
