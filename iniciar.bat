@echo off
REM ============================================================================
REM  ChargeGrid Intelligence - NexusCharge
REM  Sprint 3 | FIAP + GoodWe EV Challenge 2026
REM
REM  Sobe o servidor e abre o navegador. Basta dar dois cliques neste arquivo.
REM ============================================================================

REM Pagina de codigo UTF-8: sem isto o banner e os acentos saem como lixo no
REM console do Windows, que por padrao usa cp1252.
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"

title ChargeGrid Intelligence - NexusCharge

REM Trabalha sempre na pasta deste .bat, nao na pasta de onde ele foi chamado.
cd /d "%~dp0"

echo.
echo  ChargeGrid Intelligence - NexusCharge
echo  Sprint 3 ^| FIAP + GoodWe EV Challenge 2026
echo  ----------------------------------------------------------

REM ---------------------------------------------------------------------------
REM  1. Localiza o Python
REM     O launcher "py" e o caminho padrao no Windows; "python" e o reserva.
REM ---------------------------------------------------------------------------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo.
    echo  [ERRO] Python nao encontrado.
    echo.
    echo  Instale a versao 3.10 ou superior em:
    echo      https://www.python.org/downloads/
    echo.
    echo  IMPORTANTE: marque "Add python.exe to PATH" na primeira tela
    echo  do instalador, senao o Windows nao acha o Python depois.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do set "VERSAO=%%v"
echo  Python   : %VERSAO%

REM ---------------------------------------------------------------------------
REM  2. Garante as dependencias
REM     Sao apenas duas: flask e pytest. O banco usa o sqlite3, que ja vem
REM     junto com o Python - nao ha nada a instalar por causa dele.
REM ---------------------------------------------------------------------------
%PY% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo  Flask    : instalando...
    %PY% -m pip install --quiet --disable-pip-version-check flask pytest
    if errorlevel 1 (
        echo.
        echo  [ERRO] Nao foi possivel instalar as dependencias.
        echo  Verifique a conexao com a internet e tente de novo, ou rode
        echo  manualmente:  pip install flask pytest
        echo.
        pause
        exit /b 1
    )
    echo  Flask    : instalado
) else (
    echo  Flask    : ok
)

REM ---------------------------------------------------------------------------
REM  3. Abre o navegador alguns segundos depois, ja com o servidor de pe.
REM     Roda em paralelo para nao travar a subida do Flask.
REM ---------------------------------------------------------------------------
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://localhost:5001'" >nul 2>&1

echo  Navegador: abrindo em http://localhost:5001
echo  ----------------------------------------------------------
echo.

REM ---------------------------------------------------------------------------
REM  4. Sobe o servidor. O proprio app.py imprime as contas de demonstracao.
REM ---------------------------------------------------------------------------
%PY% app.py

REM ---------------------------------------------------------------------------
REM  5. Saida - a janela fica aberta para o erro poder ser lido.
REM ---------------------------------------------------------------------------
echo.
echo  ----------------------------------------------------------
if errorlevel 1 (
    echo  Servidor encerrado com erro. A mensagem esta acima.
) else (
    echo  Servidor encerrado.
)
echo.
pause
