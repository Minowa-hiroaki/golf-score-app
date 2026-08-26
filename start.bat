@echo off
cd /d "%~dp0"
title Golf Score App

REM ============================================================
REM  golf-score-app  一発起動型（ローカル確認用）
REM  ・このファイルをダブルクリックするだけで起動します。
REM  ・初回だけ .venv を作り、requirements.txt を自動で入れます（数分）。
REM  ・コードページの切り替え(chcp)は書きません。
REM    このフォルダのパスに日本語(個人)が含まれるため、chcp を書くと
REM    cmd がバッチを見失い、何も表示せず即終了します（規約 BAT-6）。
REM    代わりに PYTHONIOENCODING で日本語表示をそろえます。
REM  ・専用ポート = 8590（個人/ポート台帳_個人.md で管理。業務アプリの台帳とは分離）
REM  ・本番は Streamlit Cloud。これは手元で動きを確かめるための起動口です。
REM    .streamlit/secrets.toml があれば本番と同じ Google スプレッドシートに
REM    つながります。書き込む操作は本番データに反映されるのでご注意ください。
REM ============================================================

set "PYTHONIOENCODING=cp932:replace"
set "PORT=8590"

REM --- Python を確認（py 優先、無ければ python） ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython

REM --- 初回のみ .venv を作り、必要なものを自動で入れる ---
if not exist ".venv" (
    echo 初回の準備をしています。数分かかることがあります。
    echo この画面は閉じずにお待ちください。
    echo.
    %PY% -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 goto :installfail
    echo.
    echo 準備が終わりました。
    echo.
) else (
    call ".venv\Scripts\activate.bat"
)

REM --- 同じポートで動いている古いものがあれば終了する ---
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>nul

echo ブラウザで http://localhost:%PORT% を開きます...
echo 終了するときは、この黒い画面を閉じてください。
echo.
streamlit run app.py --server.port %PORT%
pause
exit /b 0

:nopython
echo [エラー] Python が見つかりません。
echo   先に Python 3 をインストールしてください。
echo   ダウンロード: https://www.python.org/downloads/windows/
echo   ※インストール時に「Add python.exe to PATH」にチェックを入れてください。
echo.
pause
exit /b 1

:installfail
echo.
echo [エラー] 必要なものの準備に失敗しました。
echo   インターネットに接続できているかをご確認ください。
echo   .venv フォルダが途中まで作られている場合は、削除してからやり直してください。
echo.
pause
exit /b 1
