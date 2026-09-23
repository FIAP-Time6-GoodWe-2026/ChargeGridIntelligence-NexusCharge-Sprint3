# =============================================================================
#  ChargeGrid Intelligence — Carros salvos por conta
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Carros cadastrados em cada conta.

Quem vai carregar escolhe um carro salvo ou informa um novo, e decide se o
novo fica salvo. Não salvar existe de propósito: é o caso de quem usa a
própria conta para carregar o carro de um amigo, e não quer esse carro na
lista para sempre.

Se um carro está carregando ou não, este módulo não guarda: isso é derivado
das sessões ativas, que já são a fonte da verdade. Guardar aqui seria uma
segunda cópia do mesmo fato, pronta para divergir da primeira.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import db

# Um carro por conta, e dois para a Amanda: o primeiro já está carregando no
# P1-C4 quando o servidor sobe, o segundo fica livre para iniciar outra recarga.
INICIAIS: Dict[str, List[Tuple[str, str]]] = {
    "amanda": [("BRA2E19", "BYD Dolphin"), ("RIO4F22", "Renault Kwid E-Tech")],
    "allan":  [("SPA7C31", "Volvo EX30")],
    "jose":   [("JSF1A23", "BYD Dolphin Mini")],
    "mylon":  [("MYL0N26", "BYD Seal")],
    "luiz":   [("LUZ9B87", "GWM Ora 03")],
}


def garantir_iniciais() -> None:
    """Cadastra os carros iniciais que ainda não estiverem no banco."""
    for usuario, carros in INICIAIS.items():
        for placa, modelo in carros:
            db.execute(
                "INSERT OR IGNORE INTO veiculos (usuario, placa, modelo) "
                "VALUES (?, ?, ?)", (usuario, placa, modelo))


def do_usuario(usuario: str) -> List[dict]:
    """Carros da conta, na ordem em que foram cadastrados."""
    return [dict(linha) for linha in db.query_all(
        "SELECT placa, modelo FROM veiculos WHERE usuario = ? ORDER BY id",
        (usuario,))]


def pertence(usuario: str, placa: str) -> bool:
    """Indica se a placa está salva nesta conta."""
    return db.query_one(
        "SELECT 1 FROM veiculos WHERE usuario = ? AND placa = ?",
        (usuario, placa)) is not None


def salvar(usuario: str, placa: str, modelo: str = "") -> None:
    """
    Salva um carro na conta. Salvar de novo a mesma placa não duplica.

    A placa já deve chegar validada e normalizada (sem hífen, maiúscula) —
    quem valida é a rota, com a mesma regra de todos os outros formulários.
    """
    db.execute(
        "INSERT OR IGNORE INTO veiculos (usuario, placa, modelo) VALUES (?, ?, ?)",
        (usuario, placa, (modelo or "").strip()[:40]))


def placa_inicial(usuario: str, indice: int = 0) -> str:
    """Placa do N-ésimo carro inicial da conta — usada pelo seed da demonstração."""
    return INICIAIS[usuario][indice][0]
