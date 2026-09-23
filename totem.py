# =============================================================================
#  ChargeGrid Intelligence — Totem do conector
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Regras do totem físico: uma tela vertical, de toque, ao lado de um conector.

O totem não é o app em outra resolução. Três diferenças mudam o desenho:

1. **Um totem, um conector.** Ele não mostra mapa nem outros postos; só o
   conector ao lado dele, do início ao recibo.
2. **Ninguém digita senha num terminal público.** Entrar com a conta é pelo
   celular: o totem mostra um QR, o celular lê e confirma, e o totem entra.
3. **O totem esquece quem usou.** Ao terminar, a sessão de login é encerrada —
   o próximo motorista não pode herdar a conta do anterior.

Este módulo guarda o pareamento totem ↔ celular. As rotas ficam no `app.py`.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Dict, Optional

# Conector que o totem controla quando ninguém configurou outro. É um conector
# livre na demonstração (Faria Lima), para o fluxo começar sem preparo.
CONECTOR_PADRAO: str = "P2-C1"

# Quanto tempo o QR de login vale. Curto de propósito: é um QR exibido numa
# tela pública, e quem o fotografasse não deveria poder usá-lo depois.
VALIDADE_PAREAMENTO_S: int = 180

# ponytail: pareamentos em memória, com um lock global. Suficiente para um
# processo só; com vários workers precisaria ir para o banco ou para um cache
# compartilhado, porque o celular e o totem podem cair em processos diferentes.
_pareamentos: Dict[str, dict] = {}
_trava = threading.Lock()


def _limpar_vencidos(agora: float) -> None:
    for token in [t for t, p in _pareamentos.items() if p["expira"] < agora]:
        del _pareamentos[token]


def criar_pareamento(charger_id: str) -> str:
    """Abre um pareamento para o totem de `charger_id` e devolve o token do QR."""
    token = secrets.token_urlsafe(9)
    agora = time.time()
    with _trava:
        _limpar_vencidos(agora)
        _pareamentos[token] = {"charger_id": charger_id, "usuario": None,
                               "expira": agora + VALIDADE_PAREAMENTO_S}
    return token


def pareamento(token: str) -> Optional[dict]:
    """O pareamento vigente do token, ou None se não existe ou venceu."""
    with _trava:
        _limpar_vencidos(time.time())
        p = _pareamentos.get(token)
        return dict(p) if p else None


def confirmar(token: str, usuario: str) -> bool:
    """
    O celular confirma: amarra a conta ao pareamento.

    Returns:
        False se o token venceu ou já foi confirmado por outra conta.
    """
    with _trava:
        _limpar_vencidos(time.time())
        p = _pareamentos.get(token)
        if p is None or (p["usuario"] and p["usuario"] != usuario):
            return False
        p["usuario"] = usuario
        return True


def consumir(token: str) -> Optional[str]:
    """
    O totem pergunta se já foi confirmado. Se sim, devolve a conta e apaga o
    pareamento — um QR serve para um login só.
    """
    with _trava:
        p = _pareamentos.get(token)
        if p is None or p["expira"] < time.time() or not p["usuario"]:
            return None
        del _pareamentos[token]
        return p["usuario"]
