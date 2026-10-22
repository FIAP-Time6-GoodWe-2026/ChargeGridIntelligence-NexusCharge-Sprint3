# =============================================================================
#  ChargeGrid Intelligence — Ponte com o totem físico (ESP32)
#  Homologação · Fases 1–2: leitura das portas e encerramento ao desplugar
# =============================================================================

"""
Estado das portas físicas do totem, reportado pelo ESP32.

O ESP32 mede a corrente de cada porta (INA219) e envia o resultado ao Flask
por HTTP/JSON. Este módulo guarda o último estado recebido e valida a
mensagem; não conhece Flask e usa só a biblioteca padrão, como o resto das
camadas de negócio.

Mapeamento (Fase 1): o totem simula fisicamente o posto da Paulista (P1) e
cada porta física corresponde a um conector desse posto.

    porta 1 → P1-C1     porta 2 → P1-C2     porta 3 → P1-C3

Plugar o cabo só aponta a tela do totem para o conector (a sessão nasce na
identificação do motorista); retirar o cabo encerra a recarga ativa
(`DetectorDesplugue`).

Formato da mensagem (POST /api/esp32/portas):

    {
      "fw": "0.3.0",                      # opcional: versão do firmware
      "portas": [
        {"porta": 1, "corrente_ma": 1000.0, "tensao_v": 5.02, "leitura_ok": true},
        {"porta": 2, "corrente_ma": 0.0,    "tensao_v": 5.05, "leitura_ok": true},
        {"porta": 3, "corrente_ma": 0.0,    "tensao_v": 0.0,  "leitura_ok": false}
      ]
    }

`leitura_ok` falso indica que o INA219 daquela porta não respondeu (fio solto,
módulo desligado): a porta é reportada como sem leitura, e não como livre.

A presença é decidida aqui, pela corrente (`LIMIAR_PRESENCA_MA`): calibrar não
exige regravar o firmware. O campo `presente` que o firmware ainda envia (ele
o usa no semáforo offline) é ignorado.

Celular no lugar do carro: 1 W medido na porta vale 1 kW na aplicação
(`KW_POR_W_MEDIDO`). Um carregador de 5 W vira 5 kW; o teto de 11 kW do
GW11K-HCA-20 é aplicado no SessionManager. Sem `tensao_v` (firmware antigo)
não há potência medida e a energia segue a potência alocada.
"""

from __future__ import annotations

import datetime
import hmac
import math
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

# Posto que o totem simula e a ordem dos conectores ligados às portas.
POSTO_FISICO: str = "P1"
CONECTORES_POR_PORTA: Dict[int, str] = {
    1: f"{POSTO_FISICO}-C1",
    2: f"{POSTO_FISICO}-C2",
    3: f"{POSTO_FISICO}-C3",
}
TOTAL_PORTAS: int = len(CONECTORES_POR_PORTA)

# Sem mensagem do ESP32 por mais que isso, o totem é dado como offline.
TIMEOUT_OFFLINE_S: float = 10.0

# Faixa aceita para a corrente medida. O INA219 com shunt de 0,1 Ω mede até
# ~3,2 A; qualquer coisa fora disso é lixo de comunicação, não medição.
CORRENTE_MIN_MA: float = -500.0
CORRENTE_MAX_MA: float = 5000.0
# Calibração padrão da biblioteca Adafruit (setCalibration_32V_2A).
TENSAO_MAX_V: float = 32.0

# Corrente mínima para considerar algo plugado. Ruído medido: ±0,4 mA.
LIMIAR_PRESENCA_MA: float = 20.0

# Escala da demonstração com celulares: 1 W medido = 1 kW na aplicação.
KW_POR_W_MEDIDO: float = 1.0

# Token de desenvolvimento. Serve para o primeiro teste, mas quem expõe o
# servidor a outras pessoas (hotspot na apresentação) define o próprio em
# CHARGEGRID_ESP32_TOKEN, para ninguém forjar o estado das portas.
TOKEN_PADRAO_DEV: str = "chargegrid-esp32-dev"


def token_configurado() -> str:
    """Token esperado no cabeçalho `X-ESP32-Token`."""
    return os.environ.get("CHARGEGRID_ESP32_TOKEN") or TOKEN_PADRAO_DEV


def usando_token_padrao() -> bool:
    """Verdadeiro quando o token de desenvolvimento está em uso."""
    return token_configurado() == TOKEN_PADRAO_DEV


def token_valido(recebido: Optional[str]) -> bool:
    """Compara o token em tempo constante (sem vazar prefixo por timing)."""
    if not recebido:
        return False
    return hmac.compare_digest(recebido.encode("utf-8"),
                               token_configurado().encode("utf-8"))


class MensagemInvalida(ValueError):
    """A mensagem do ESP32 não segue o formato esperado."""


def _porta_valida(bruto: Any) -> Dict[str, Any]:
    """Valida e normaliza uma porta da mensagem."""
    if not isinstance(bruto, dict):
        raise MensagemInvalida("cada porta deve ser um objeto JSON")

    numero = bruto.get("porta")
    # bool é subclasse de int em Python: `True` não pode passar por porta 1.
    if isinstance(numero, bool) or not isinstance(numero, int):
        raise MensagemInvalida("'porta' deve ser um inteiro")
    if numero not in CONECTORES_POR_PORTA:
        raise MensagemInvalida(f"'porta' deve estar entre 1 e {TOTAL_PORTAS}")

    leitura_ok = bruto.get("leitura_ok", True)
    if not isinstance(leitura_ok, bool):
        raise MensagemInvalida("'leitura_ok' deve ser booleano")

    corrente = bruto.get("corrente_ma")
    if isinstance(corrente, bool) or not isinstance(corrente, (int, float)):
        raise MensagemInvalida("'corrente_ma' deve ser numérico")
    corrente = float(corrente)
    if not math.isfinite(corrente):
        raise MensagemInvalida("'corrente_ma' deve ser um número finito")
    if not CORRENTE_MIN_MA <= corrente <= CORRENTE_MAX_MA:
        raise MensagemInvalida(
            f"'corrente_ma' fora da faixa [{CORRENTE_MIN_MA:g}, "
            f"{CORRENTE_MAX_MA:g}]")

    tensao = bruto.get("tensao_v")
    if tensao is not None:
        if isinstance(tensao, bool) or not isinstance(tensao, (int, float)):
            raise MensagemInvalida("'tensao_v' deve ser numérico")
        tensao = float(tensao)
        if not math.isfinite(tensao) or not 0.0 <= tensao <= TENSAO_MAX_V:
            raise MensagemInvalida(
                f"'tensao_v' fora da faixa [0, {TENSAO_MAX_V:g}]")

    # Sem leitura válida não há como afirmar presença.
    presente = leitura_ok and corrente >= LIMIAR_PRESENCA_MA

    # Potência só existe com tensão informada; porta livre ou muda é 0 kW
    # (o ruído de poucos mA não vira consumo).
    potencia_kw: Optional[float] = None
    if tensao is not None:
        potencia_kw = (round(tensao * corrente / 1000.0 * KW_POR_W_MEDIDO, 3)
                       if presente else 0.0)

    return {
        "porta": numero,
        "conector": CONECTORES_POR_PORTA[numero],
        "corrente_ma": round(corrente, 1),
        "tensao_v": None if tensao is None else round(tensao, 2),
        "potencia_kw": potencia_kw,
        "presente": presente,
        "leitura_ok": leitura_ok,
    }


def validar_mensagem(corpo: Any) -> Tuple[List[Dict[str, Any]], str]:
    """
    Valida a mensagem inteira e devolve `(portas, versao_do_firmware)`.

    Aceita 1 a 3 portas por mensagem, sem repetir número. Levanta
    `MensagemInvalida` com um texto que o firmware consegue exibir no Serial.
    """
    if not isinstance(corpo, dict):
        raise MensagemInvalida("o corpo deve ser um objeto JSON")

    bruto = corpo.get("portas")
    if not isinstance(bruto, list) or not bruto:
        raise MensagemInvalida("'portas' deve ser uma lista não vazia")
    if len(bruto) > TOTAL_PORTAS:
        raise MensagemInvalida(f"no máximo {TOTAL_PORTAS} portas por mensagem")

    portas = [_porta_valida(p) for p in bruto]
    numeros = [p["porta"] for p in portas]
    if len(set(numeros)) != len(numeros):
        raise MensagemInvalida("número de porta repetido na mensagem")

    fw = corpo.get("fw", "")
    if not isinstance(fw, str) or len(fw) > 32:
        raise MensagemInvalida("'fw' deve ser texto de até 32 caracteres")
    return portas, fw


class EstadoPortas:
    """
    Último estado conhecido das portas físicas, com acesso seguro entre threads.

    O Flask atende o ESP32 e o navegador do operador em threads diferentes;
    o `Lock` evita ler uma porta atualizada pela metade.
    """

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._portas: Dict[int, Dict[str, Any]] = {}
        self._ultimo_contato: Optional[datetime.datetime] = None
        self._fw: str = ""

    def atualizar(self, portas: List[Dict[str, Any]], fw: str = "",
                  agora: Optional[datetime.datetime] = None) -> None:
        """Grava as portas recebidas e marca o instante do contato."""
        agora = agora or datetime.datetime.now()
        with self._trava:
            for p in portas:
                self._portas[p["porta"]] = {**p, "atualizado_em": agora}
            self._ultimo_contato = agora
            if fw:
                self._fw = fw

    def online(self, agora: Optional[datetime.datetime] = None) -> bool:
        """O ESP32 falou nos últimos `TIMEOUT_OFFLINE_S` segundos?"""
        agora = agora or datetime.datetime.now()
        with self._trava:
            if self._ultimo_contato is None:
                return False
            idade = (agora - self._ultimo_contato).total_seconds()
        return idade <= TIMEOUT_OFFLINE_S

    def instantaneo(self, agora: Optional[datetime.datetime] = None
                    ) -> Dict[str, Any]:
        """Estado serializável (JSON) das 3 portas, em ordem."""
        agora = agora or datetime.datetime.now()
        online = self.online(agora)
        with self._trava:
            contato = self._ultimo_contato
            fw = self._fw
            copia = {n: dict(p) for n, p in self._portas.items()}

        saida: List[Dict[str, Any]] = []
        for numero in sorted(CONECTORES_POR_PORTA):
            p = copia.get(numero)
            if p is None:
                saida.append({
                    "porta": numero, "conector": CONECTORES_POR_PORTA[numero],
                    "estado": "sem_dados", "corrente_ma": None,
                    "potencia_kw": None, "idade_s": None,
                })
                continue
            idade = round((agora - p["atualizado_em"]).total_seconds(), 1)
            if not online:
                estado = "offline"
            elif not p["leitura_ok"]:
                estado = "sem_leitura"
            else:
                estado = "plugada" if p["presente"] else "livre"
            saida.append({
                "porta": numero, "conector": p["conector"],
                "estado": estado, "corrente_ma": p["corrente_ma"],
                "potencia_kw": p["potencia_kw"], "idade_s": idade,
            })

        return {
            "posto": POSTO_FISICO,
            "online": online,
            "firmware": fw or None,
            "ultimo_contato": contato.isoformat(timespec="seconds")
            if contato else None,
            "portas": saida,
        }

    def limpar(self) -> None:
        """Esquece o estado (usado pelo restaurar-demonstração e nos testes)."""
        with self._trava:
            self._portas.clear()
            self._ultimo_contato = None
            self._fw = ""


# ── Desplugue: quando uma recarga deve ser encerrada ───────────────────────

LEITURAS_LIVRE_PARA_ENCERRAR = 3   # ~4,5 s com o firmware a 1,5 s por ciclo


class DetectorDesplugue:
    """
    Decide quando o cabo foi retirado de uma porta que tem recarga ativa.

    Duas proteções contra encerrar por engano:

      - só vale para a recarga em que a porta já foi vista plugada: uma sessão
        aberta pelo app ou pelo operador, sem cabo físico, nunca é encerrada;
      - exige `LEITURAS_LIVRE_PARA_ENCERRAR` leituras livres seguidas, para um
        mau contato de um instante não derrubar a recarga.

    Leitura sem sensor (`leitura_ok` falso) não conta como livre: sem medir,
    não se sabe se o cabo saiu. Não conhece Flask nem o gerenciador de sessões.
    """

    def __init__(self, leituras_para_encerrar: int = LEITURAS_LIVRE_PARA_ENCERRAR):
        self._limite = leituras_para_encerrar
        self._visto: Dict[int, Dict[str, Any]] = {}
        self._trava = threading.Lock()

    def processar(self, portas: List[Dict[str, Any]],
                  sessao_ativa_em: Dict[str, str]) -> List[str]:
        """
        Args:
            portas          : portas da mensagem validada (`validar_mensagem`)
            sessao_ativa_em : conector → id da sessão ativa nele
        Returns:
            Conectores cuja recarga deve ser encerrada agora.
        """
        encerrar: List[str] = []
        with self._trava:
            for p in portas:
                numero, cid = p["porta"], p["conector"]
                sid = sessao_ativa_em.get(cid)
                if sid is None:
                    self._visto.pop(numero, None)
                    continue
                if not p["leitura_ok"]:
                    continue
                registro = self._visto.get(numero)
                if p["presente"]:
                    self._visto[numero] = {"sid": sid, "livres": 0}
                elif registro and registro["sid"] == sid:
                    registro["livres"] += 1
                    if registro["livres"] >= self._limite:
                        encerrar.append(cid)
                        self._visto.pop(numero, None)
        return encerrar

    def limpar(self) -> None:
        with self._trava:
            self._visto.clear()


# ── Semáforo do posto ──────────────────────────────────────────────────────

SEMAFORO_VERDE, SEMAFORO_AMARELO, SEMAFORO_VERMELHO = "verde", "amarelo", "vermelho"


def semaforo_do_posto(ocupacao_pct: float) -> str:
    """
    Cor do semáforo a partir da ocupação do posto (potência em uso / limite).

    Com 11 kW por conector e 33 kW no posto, isso reproduz a regra do
    protótipo de bancada: até 1 carro verde, 2 carros amarelo, 3 ou mais
    (posto no limite) vermelho. Vale para qualquer sessão do posto, venha do
    totem físico, do app ou do operador.
    """
    if ocupacao_pct >= 99.9:
        return SEMAFORO_VERMELHO
    if ocupacao_pct >= 50.0:
        return SEMAFORO_AMARELO
    return SEMAFORO_VERDE
