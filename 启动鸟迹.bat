@echo off
rem 鸟迹 BirdTrace 开发运行脚本
cd /d "%~dp0"
if not exist .venv (
    echo [setup] creating venv...
    python -m venv .venv
    .venv\Scripts\python -m pip install -i https://pypi.org/simple -r requirements.txt
)
if not exist assets\models\BirdTraceRecognitionModel.onnx (
    echo [setup] extracting assets from apk...
    .venv\Scripts\python tools\extract_assets.py
)
.venv\Scripts\python -X utf8 -m app.main %*
