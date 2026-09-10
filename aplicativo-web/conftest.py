"""
Configuração do pytest para a suíte do ChargeGrid.

`gestao_sessoes.py` — a entrega de Estruturas de Dados — mora na pasta irmã
`estruturas-de-dados/`, e a classe `TestGestaoSessoes` importa dele. Sem esta
entrada no `sys.path`, os testes daquela classe falhariam com `ModuleNotFound`
dependendo de onde o `pytest` foi chamado.

O caminho é derivado deste arquivo, não do diretório de trabalho: assim
`pytest` funciona tanto de dentro de `aplicativo-web/` quanto da raiz.
"""

import pathlib
import sys

CLI = pathlib.Path(__file__).resolve().parent.parent / "estruturas-de-dados"
if CLI.is_dir() and str(CLI) not in sys.path:
    sys.path.insert(0, str(CLI))
