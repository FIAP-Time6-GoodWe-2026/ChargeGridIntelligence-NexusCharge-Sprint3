# =============================================================================
#  ChargeGrid Intelligence — Persistência (SQLite / stdlib)
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Camada de persistência mínima usando apenas `sqlite3` da biblioteca padrão.

Guarda o que não pode desaparecer quando o processo Flask reinicia:
    carteira    — saldo de NexusCoin por usuário
    transacoes  — extrato (recarga, pagamento, cashback, sinal, taxa, estorno)
    reservas    — reservas de conector com sinal já cobrado
    sessoes     — histórico de sessões encerradas (relatório, CSV, análise)

Sessões ATIVAS continuam vivendo no SessionManager em memória: este módulo
não substitui o SessionManager, apenas arquiva o que já terminou.

Decisão de design — uma conexão nova por operação:
    SQLite abre um arquivo local em microssegundos. Abrir e fechar por chamada
    elimina qualquer problema de thread do servidor de desenvolvimento do
    Flask (cada request roda em uma thread diferente) sem precisar de
    `check_same_thread=False` nem de um pool de conexões.
"""

from __future__ import annotations

import pathlib
import sqlite3
from typing import Any, Iterable, Optional

# O arquivo do banco fica ao lado do código, para que `python app.py` funcione
# de qualquer diretório de trabalho.
DB_PATH: pathlib.Path = pathlib.Path(__file__).with_name("chargegrid.db")

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS carteira (
    usuario TEXT PRIMARY KEY,
    saldo   REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transacoes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario   TEXT NOT NULL,
    tipo      TEXT NOT NULL,   -- RECARGA|PAGAMENTO|CASHBACK|SINAL|ESTORNO|TAXA
    valor     REAL NOT NULL,   -- positivo credita, negativo debita
    descricao TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS reservas (
    charger_id TEXT PRIMARY KEY,
    usuario    TEXT NOT NULL,
    criada_em  TEXT NOT NULL,
    expira_em  TEXT NOT NULL,
    sinal_brl  REAL NOT NULL,
    status     TEXT NOT NULL   -- ATIVA|USADA|EXPIRADA|CANCELADA
);

CREATE TABLE IF NOT EXISTS sessoes (
    session_id    TEXT PRIMARY KEY,
    usuario       TEXT NOT NULL DEFAULT '',
    charger_id    TEXT NOT NULL,
    station_id    TEXT NOT NULL,
    vehicle_id    TEXT NOT NULL,
    user_name     TEXT NOT NULL DEFAULT '',
    user_type     TEXT NOT NULL,
    inicio        TEXT NOT NULL,
    fim           TEXT NOT NULL,
    hora_inicio   INTEGER NOT NULL DEFAULT 0,
    duracao_min   REAL NOT NULL,
    potencia_kw   REAL NOT NULL,
    energia_kwh   REAL NOT NULL,
    tarifa_kwh    REAL NOT NULL,
    custo_brl     REAL NOT NULL,
    metodo_pagto  TEXT NOT NULL DEFAULT '',
    sinal_abatido REAL NOT NULL DEFAULT 0,
    cashback_nc   REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_transacoes_usuario ON transacoes (usuario, id DESC);
CREATE INDEX IF NOT EXISTS idx_reservas_status    ON reservas   (status, usuario);
"""


def _conn() -> sqlite3.Connection:
    """Abre uma conexão com `row_factory` que devolve linhas indexáveis por nome."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """
    Cria as tabelas e índices caso ainda não existam.

    Idempotente: pode ser chamada a cada import do módulo `app` sem efeito
    colateral, inclusive nos reloads automáticos do Flask em modo debug.
    """
    with _conn() as conn:
        conn.executescript(SCHEMA)


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """
    Executa um comando de escrita (INSERT/UPDATE/DELETE).

    Args:
        sql    : comando SQL com placeholders `?`
        params : valores para os placeholders

    Returns:
        Número de linhas afetadas.
    """
    with _conn() as conn:
        return conn.execute(sql, tuple(params)).rowcount


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    """Executa um SELECT e devolve a primeira linha, ou None."""
    with _conn() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def query_all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    """Executa um SELECT e devolve todas as linhas."""
    with _conn() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def reset() -> None:
    """
    Apaga todo o conteúdo das tabelas, preservando o schema.

    Usado pelo atalho de demonstração e pelos testes. Não remove o arquivo,
    apenas esvazia — assim quem já tem uma conexão aberta não quebra.
    """
    with _conn() as conn:
        for tabela in ("transacoes", "carteira", "reservas", "sessoes"):
            conn.execute(f"DELETE FROM {tabela}")


if __name__ == "__main__":
    # Autoverificação: cria o banco, grava, lê e limpa.
    init()
    execute("INSERT OR REPLACE INTO carteira (usuario, saldo) VALUES (?, ?)",
            ("__teste__", 42.0))
    linha = query_one("SELECT saldo FROM carteira WHERE usuario = ?", ("__teste__",))
    assert linha is not None and linha["saldo"] == 42.0, "escrita/leitura falhou"
    execute("DELETE FROM carteira WHERE usuario = ?", ("__teste__",))
    assert query_one("SELECT 1 FROM carteira WHERE usuario = ?", ("__teste__",)) is None
    print(f"db.py OK — banco em {DB_PATH}")
