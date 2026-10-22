#!/bin/bash
# ============================================================================
#  ChargeGrid Intelligence - NexusCharge
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
#
#  Versão macOS do iniciar.bat: dois cliques neste arquivo no Finder.
#  Na primeira vez, se o macOS bloquear: botão direito > Abrir > Abrir.
# ============================================================================

# Trabalha sempre na pasta deste arquivo, não na de onde ele foi chamado.
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1

echo
echo "  ChargeGrid Intelligence - NexusCharge"
echo "  Sprint 3 | FIAP + GoodWe EV Challenge 2026"
echo "  ----------------------------------------------------------"

fim() {
    echo
    echo "  ----------------------------------------------------------"
    if [ "$1" -ne 0 ]; then echo "  Encerrado com erro. A mensagem está acima."; else echo "  Encerrado."; fi
    echo
    read -r -p "  Enter para fechar..." _
    exit "$1"
}

# ---------------------------------------------------------------------------
#  1. Localiza o Python (3.11+)
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1 \
   || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    echo
    echo "  [ERRO] Python 3.11 ou superior não encontrado."
    echo "  Instale em https://www.python.org/downloads/ (ou: brew install python)"
    fim 1
fi

# ---------------------------------------------------------------------------
#  2. Dependências (flask e pytest) num ambiente virtual próprio, .venv/
#     O Python do Homebrew recusa "pip install" fora de um venv (PEP 668).
# ---------------------------------------------------------------------------
if [ ! -x .venv/bin/python ]; then
    echo "  Ambiente : criando .venv..."
    python3 -m venv .venv || fim 1
fi
PY=.venv/bin/python
echo "  Python   : $($PY --version 2>&1)"

if ! $PY -c "import flask, pytest" >/dev/null 2>&1; then
    echo "  Pacotes  : instalando flask e pytest..."
    if ! $PY -m pip install --quiet --disable-pip-version-check flask pytest; then
        echo
        echo "  [ERRO] Não foi possível instalar as dependências."
        echo "  Verifique a internet e tente de novo."
        fim 1
    fi
    echo "  Pacotes  : instalados"
else
    echo "  Pacotes  : ok"
fi

# ---------------------------------------------------------------------------
#  3. Menu
# ---------------------------------------------------------------------------
while true; do
    echo "  ----------------------------------------------------------"
    echo
    echo "   [1]  Aplicativo web        mapa, recarga, carteira e pagamento"
    echo "   [2]  Gestão de sessões     menu de terminal (Estruturas de Dados)"
    echo "   [3]  Rodar os testes       suíte completa no terminal"
    echo "   [4]  Sair"
    echo
    read -r -p "  Escolha [1]: " OPCAO
    case "${OPCAO:-1}" in
        1)
            # Abre o navegador alguns segundos depois, já com o servidor de pé.
            (sleep 4; open "http://localhost:5001") &
            echo
            echo "  Navegador: abrindo em http://localhost:5001"
            echo "  Se o macOS perguntar sobre conexões de entrada, clique em Permitir"
            echo "  (o celular e o ESP32 acessam o Mac pela rede)."
            echo "  Para parar o servidor: Ctrl+C"
            echo "  ----------------------------------------------------------"
            echo
            $PY app.py; fim $? ;;
        2) echo; $PY menu.py; fim $? ;;
        3) echo; $PY -m pytest test_chargegrid.py -q; fim $? ;;
        4) exit 0 ;;
        *) echo; echo "  Opção inválida: \"$OPCAO\". Escolha de 1 a 4."; echo ;;
    esac
done
