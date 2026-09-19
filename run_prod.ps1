# Script de inicio para Producción - JamuyWasi API
# Detecta los núcleos del CPU y levanta Uvicorn con múltiples workers
$cpuCores = [System.Environment]::ProcessorCount
# IMPORTANTE: 1 solo worker mientras no haya Redis.
# El WebSocket, la caché y el límite de intentos viven en la memoria de cada worker:
# con varios workers, un comerciante conectado al worker A NO recibe los pedidos creados en el worker B.
# FastAPI es asíncrono: 1 worker atiende sin problema cientos de usuarios simultáneos.
$workers = 1

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Iniciando JamuyWasi API en modo Produccion Multi-Worker" -ForegroundColor Green
Write-Host "Cores detectados: $cpuCores | Workers configurados: $workers" -ForegroundColor Cyan
Write-Host "Puerto: http://0.0.0.0:8000" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green

& ".\.venv\Scripts\uvicorn.exe" app.main:app --host 0.0.0.0 --port 8000 --workers $workers --loop asyncio
