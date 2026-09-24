# =============================================================================
#  ChargeGrid Intelligence — Servidor Web Flask
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Servidor Flask: camada de apresentação e roteamento HTTP.

Nenhuma regra de negócio vive aqui. Todas as decisões são delegadas:
    SessionManager  → ciclo de vida das sessões
    PowerManager    → controle de demanda de potência
    PricingEngine   → tarifação dinâmica em 3 eixos
    ModbusSimulator → log de frames Modbus TCP (registradores HCA G2)

Nota de arquitetura — estado global (#11):
    Os objetos sm/pm/pe/mb são globais de módulo. Isso funciona corretamente
    em modo debug (single-process, single-thread do Flask). Em produção com
    múltiplos workers (gunicorn), cada worker teria seu próprio estado,
    causando divergência de sessões entre requests. A solução definitiva é
    o Sprint 3, onde SessionManager será substituído por um repositório com
    SQLAlchemy + PostgreSQL, tornando o estado compartilhado via banco.

    Um threading.Lock protege as operações críticas do SessionManager contra
    condições de corrida em modo single-process com múltiplas threads (#12).

Rotas do Sprint 1 (mantidas):
    GET  /                          → mapa de postos
    GET  /posto/<id>                → carregadores do posto
    GET  /posto/<id>/carregador/<id>→ formulário de sessão
    POST /sessao                    → processar nova sessão (Sprint 1 flow)

Rotas novas do Sprint 2:
    GET  /dashboard                 → painel central de gerenciamento
    POST /dashboard/nova-sessao     → criar sessão via dashboard
    POST /dashboard/encerrar        → encerrar sessão via dashboard
    GET  /api/status                → JSON com estado atual (polling JS)
    GET  /relatorio                 → relatório consolidado de todas as sessões
    GET  /modbus-log                → log de frames Modbus
"""

import csv
import datetime
import io
import logging
import os
import re
import threading

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, url_for)
# IMPORTANTE: o `session` do Flask é importado com outro nome. Várias rotas
# deste arquivo usam a variável local `session` para uma ChargingSession, e a
# colisão produziria erros difíceis de rastrear.
from flask import session as user_session

import auth
import avulso
import billing
import db
import reservations
import totem
import veiculos
import wallet
from logica_recarga import processar_sessao   # Sprint 1 — intacto
from models import UserType, SessionStatus
from qr import qr_svg
from session_manager import SessionManager
from power_manager import PowerManager
from pricing_engine import PricingEngine
from modbus_simulator import ModbusSimulator

# ---------------------------------------------------------------------------
# App e logging
# ---------------------------------------------------------------------------

app = Flask(__name__)

# #13 — SECRET_KEY lida de variável de ambiente.
# Em desenvolvimento, usa o fallback hardcoded.
# Em produção: export CHARGEGRID_SECRET_KEY="<valor-aleatorio-seguro>"
app.config["SECRET_KEY"] = os.environ.get(
    "CHARGEGRID_SECRET_KEY",
    "chargegrid-intelligence-fiap-goodwe-2026-dev-only",
)


# Tradução dos tipos de usuário para exibição em português.
# Aceita o nome do enum (STANDARD), o código (P/A/C) ou o próprio Enum.
_TIPO_USUARIO_PT = {
    "STANDARD": "Padrão",
    "SUBSCRIBER": "Assinante",
    "CORPORATE": "Corporativo",
    "P": "Padrão",
    "A": "Assinante",
    "C": "Corporativo",
}


@app.template_filter("brl")
def _brl(valor, casas: int = 2) -> str:
    """Formata um número no padrão brasileiro: 1234.5 → '1.234,50'.

    Uso no template: {{ 6.54 | brl }} → "6,54"; {{ tarifa | brl(4) }} → "1,0200".
    Não inclui o "R$" — o template decide se o símbolo aparece.
    """
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{numero:,.{casas}f}"                      # 1,234.50 (padrão en-US)
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


@app.template_filter("datahora_br")
def _datahora_br(valor: str) -> str:
    """Converte 'AAAA-MM-DD HH:MM:SS' (formato do SQLite) para 'DD/MM/AAAA HH:MM'."""
    try:
        dt = datetime.datetime.strptime(str(valor)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(valor)
    return dt.strftime("%d/%m/%Y %H:%M")


@app.template_filter("tipo_pt")
def _tipo_pt(valor) -> str:
    """Filtro Jinja: traduz um tipo de usuário para português.

    Uso no template: {{ s.user_type.name | tipo_pt }} → "Padrão".
    Tolera o nome do enum, o código de uma letra ou um objeto Enum.
    """
    if hasattr(valor, "name"):        # objeto UserType
        valor = valor.name
    return _TIPO_USUARIO_PT.get(str(valor).upper(), str(valor).title())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("chargegrid.log", encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Estado global da aplicação (Sprint 3 → banco de dados via ORM)
# ---------------------------------------------------------------------------

# Limite por posto: 3 × GW11K-HCA-20 de 11 kW = 33 kW.
# Com 5 conectores, throttle ativa a partir do 3º carro (33/5 < 11kW cada).
# Cada posto tem seu próprio PowerManager — throttle é isolado por posto,
# não afetando sessões de outros postos.
LIMITE_POR_POSTO_KW = 33.0

# Sprint 3 — cria as tabelas do SQLite na primeira execução. Idempotente.
db.init()
veiculos.garantir_iniciais()

sm = SessionManager()

# Um PowerManager por posto — isolamento de throttle por instalação física
# O PowerManager recebe um SessionManager filtrado via adaptador leve
class _PostoSM:
    """Adaptador que expõe ao PowerManager apenas as sessões de um posto."""
    def __init__(self, sm_global: SessionManager, posto_id: str) -> None:
        self._sm       = sm_global
        self._posto_id = posto_id

    def list_active(self):
        return [s for s in self._sm.list_active()
                if s.charger_id.startswith(self._posto_id)]

    def list_chargers(self):
        return {k: v for k, v in self._sm.list_chargers().items()
                if k.startswith(self._posto_id)}

    def total_allocated_power_kw(self) -> float:
        return round(sum(s.allocated_power_kw for s in self.list_active()), 2)

    def active_count(self) -> int:
        return len(self.list_active())

    def occupancy_ratio(self) -> float:
        # Conectores ocupados, não sessões ativas — ver SessionManager (#B44).
        chargers = self.list_chargers()
        ocupados = sum(1 for sid in chargers.values() if sid is not None)
        return ocupados / max(len(chargers), 1)

    def get_session(self, session_id):
        return self._sm.get_session(session_id)

    def accrue_energy(self, session_id):
        return self._sm.accrue_energy(session_id)

    def restore_session(self, session_id, power_kw):
        return self._sm.restore_session(session_id, power_kw)

    def throttle_session(self, session_id, power_kw):
        return self._sm.throttle_session(session_id, power_kw)

    def finish_session(self, session_id, **kwargs):
        return self._sm.finish_session(session_id, **kwargs)

# Instância um PowerManager por posto
_posto_sms = {pid: _PostoSM(sm, pid) for pid in ["P1", "P2", "P3"]}
posto_pms  = {pid: PowerManager(_posto_sms[pid], limit_kw=LIMITE_POR_POSTO_KW)
              for pid in ["P1", "P2", "P3"]}

# pm global para compatibilidade com código legado (relatório, etc.)
# Aponta para P1 como default; as rotas usam _get_pm(posto_id)
pm = posto_pms["P1"]

def _get_pm(posto_id: str) -> PowerManager:
    """Retorna o PowerManager do posto. Fallback para P1 se inválido."""
    return posto_pms.get(posto_id, posto_pms["P1"])

pe = PricingEngine(sm)
mb = ModbusSimulator(verbose=False)

# #12 — Lock global para serializar operações críticas de estado
# (create_session / finish_session) em ambientes multi-thread.
# Não resolve o problema de multi-process (gunicorn) — isso é Sprint 3.
_state_lock = threading.Lock()

mb.on_breaker_config(breaker_current_a=50)

# ---------------------------------------------------------------------------
# Dados simulados de postos (do Sprint 1 — mantidos)
# ---------------------------------------------------------------------------

POSTOS = {
    "P1": {
        "id": "P1", "nome": "ChargeGrid Paulista",
        "endereco": "Av. Paulista, 1578 — São Paulo, SP",
        "lat_px": 45, "lng_px": 40,
        "lat": -23.561414, "lng": -46.655881,   # Av. Paulista (MASP)
        "disponivel": True, "total_carregadores": 5,
        "carregadores_livres": 5, "distancia": "3.5 km",
        "em_throttle": False,
    },
    "P2": {
        "id": "P2", "nome": "ChargeGrid Faria Lima",
        "endereco": "Av. Brigadeiro Faria Lima, 3477 — São Paulo, SP",
        "lat_px": 25, "lng_px": 60,
        "lat": -23.586368, "lng": -46.682606,   # Av. Faria Lima (Itaim)
        "disponivel": True, "total_carregadores": 5,
        "carregadores_livres": 5, "distancia": "0.6 km",
        "em_throttle": False,
    },
    "P3": {
        "id": "P3", "nome": "ChargeGrid Berrini",
        "endereco": "Av. Eng. Luís Carlos Berrini, 1681 — São Paulo, SP",
        "lat_px": 65, "lng_px": 70,
        "lat": -23.609678, "lng": -46.694540,   # Av. Berrini (Brooklin)
        "disponivel": True, "total_carregadores": 5,
        "carregadores_livres": 5, "distancia": "3.2 km",
        "em_throttle": False,
    },
}

USER_TYPE_MAP = {
    "P": UserType.STANDARD,
    "A": UserType.SUBSCRIBER,
    "C": UserType.CORPORATE,
}

# Sufixo do conector VIP, exclusivo para assinantes (um por posto).
CONECTOR_VIP = "C5"


def _eh_conector_vip(charger_id: str) -> bool:
    """
    Indica se o conector é o VIP (C5), exclusivo para assinantes.

    Aceita tanto o id completo (\"P1-C5\") quanto o sufixo (\"C5\").
    """
    return charger_id.upper().endswith(CONECTOR_VIP)

# ---------------------------------------------------------------------------
# Validação de entrada compartilhada (#B30, #B31)
# ---------------------------------------------------------------------------

# Placa Mercosul (ABC1D23) ou padrão antigo (ABC1234 / ABC-1234).
# Aceita hífen opcional e normaliza para maiúsculas sem hífen.
_PLACA_REGEX = re.compile(r"^[A-Z]{3}-?\d[A-Z0-9]\d{2}$")


def _validar_placa(raw: str) -> str:
    """
    Normaliza e valida a placa do veículo.

    Aceita os formatos brasileiros antigo (ABC1234) e Mercosul (ABC1D23),
    com ou sem hífen, em qualquer caixa. Retorna a placa normalizada
    (maiúsculas, sem hífen).

    Raises:
        ValueError : se o formato não corresponder a uma placa válida.
    """
    placa = raw.strip().upper().replace("-", "")
    if not placa:
        raise ValueError("Placa do veículo é obrigatória.")
    # Reinsere o hífen na posição canônica só para validar o padrão
    candidato = f"{placa[:3]}-{placa[3:]}" if len(placa) == 7 else placa
    if not _PLACA_REGEX.match(candidato):
        raise ValueError(
            f"Placa '{raw}' inválida. Use o formato ABC1234 ou ABC1D23 (Mercosul)."
        )
    return placa


def _validar_hora(raw: str) -> int:
    """
    Valida e converte a hora de início (0–23).

    String vazia retorna a hora atual do sistema. Qualquer valor não inteiro
    ou fora do intervalo levanta ValueError, tratado pelo chamador como flash.

    Raises:
        ValueError : hora não inteira ou fora de [0, 23].
    """
    if not raw:
        return datetime.datetime.now().hour
    hora = int(raw)   # ValueError se não for inteiro
    if not (0 <= hora <= 23):
        raise ValueError("Hora de início deve estar entre 0 e 23.")
    return hora


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atualizar_carregadores_livres() -> None:
    """
    Sincroniza o contador de carregadores livres, o flag 'disponivel' e
    o flag 'em_throttle' nos dados de postos com o estado real do SM.

    - disponivel=False quando todos os conectores estão ocupados (Lotado).
      O posto continua clicável — o template usa <a> em ambos os casos.
    - em_throttle=True quando há pelo menos uma sessão THROTTLED no posto,
      indicando que o controle dinâmico de carga está ativo.
    """
    chargers = sm.list_chargers()
    sessoes_ativas = {s.charger_id: s for s in sm.list_active()}

    for posto_id, posto in POSTOS.items():
        # #S3 — um conector reservado não pode ser anunciado como livre: o posto
        # estaria oferecendo uma vaga que já tem dono e sinal pago.
        reservados = reservations.ativas_do_posto(posto_id)

        livres = sum(
            1 for cid, sid in chargers.items()
            if cid.startswith(posto_id) and sid is None and cid not in reservados
        )
        posto["carregadores_livres"] = livres
        posto["disponivel"] = livres > 0
        posto["reservados"] = len(reservados)
        # #B47 — "ocupados" precisa ser contado, não deduzido de
        # total − livres: essa subtração jogava os reservados no balde de
        # ocupados e o topo da página contradizia os cards logo abaixo.
        posto["ocupados"] = sum(
            1 for cid, sid in chargers.items()
            if cid.startswith(posto_id) and sid is not None
        )

        # Conector VIP (C5) disponível? Usado pelo filtro "Assinantes" no mapa.
        cid_vip = f"{posto_id}-{CONECTOR_VIP}"
        posto["vip_livre"] = (chargers.get(cid_vip) is None
                              and cid_vip not in reservados)

        # Verifica se alguma sessão do posto está em throttle
        posto["em_throttle"] = any(
            s.status == SessionStatus.THROTTLED
            for cid, s in sessoes_ativas.items()
            if cid.startswith(posto_id)
        )


# ---------------------------------------------------------------------------
# ── SPRINT 3 · AUTENTICAÇÃO E AUTORIZAÇÃO ─────────────────────────────────
# ---------------------------------------------------------------------------

# Endpoints acessíveis sem autenticação.
ROTAS_PUBLICAS: set[str] = {
    "login", "static",
    # O bilhete da recarga sem conta, aberto no celular pelo QR do totem.
    # As telas do totem entram mais abaixo, junto com o modo totem.
    "avulso_sessao",
}

# Endpoints restritos ao perfil staff (dono do posto).
ROTAS_STAFF: set[str] = {
    "admin_home", "dashboard", "dashboard_nova_sessao", "dashboard_encerrar",
    "relatorio_consolidado", "modbus_log", "testes", "api_testes_run",
    "export_csv", "demo_reset", "liberar_conector",
}


@app.before_request
def _guarda_de_acesso():
    """
    Guarda global de autenticação e autorização.

    Aplicada a todas as rotas de uma vez, em vez de um decorador por rota:
    assim uma rota nova nasce protegida por padrão, e liberar o acesso exige
    adicioná-la explicitamente a ROTAS_PUBLICAS — o erro seguro é negar.
    """
    endpoint = request.endpoint
    desvio = _guarda_de_modo()
    if desvio is not None:
        return desvio
    if endpoint is None or endpoint in ROTAS_PUBLICAS:
        return None

    if "usuario" not in user_session:
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    if endpoint in ROTAS_STAFF and not user_session.get("staff"):
        flash("Esta área é restrita à equipe do posto.", "error")
        return redirect(url_for("mapa"))

    return None


@app.context_processor
def _injetar_perfil():
    """
    Disponibiliza dados do usuário logado em qualquer template.

    Evita repetir `saldo=...` em cada `render_template` e mantém o menu de
    perfil correto em telas que não sabem nada sobre a carteira.
    """
    if "usuario" not in user_session:
        return {"saldo_nc": 0.0, "reserva_ativa": None, "pendencia": None}
    usuario = user_session["usuario"]
    return {
        "saldo_nc": wallet.saldo(usuario),
        "reserva_ativa": reservations.ativa_do_usuario(usuario),
        "cashback_pct": int(wallet.CASHBACK_NEXUSCOIN * 100),
        "pendencia": _pendencia_do_usuario(usuario),
    }


def _pendencia_do_usuario(usuario: str):
    """
    Recarga encerrada do usuário que ainda não foi paga, ou None.

    Sem isto, quem fecha a aba na tela de pagamento não teria como voltar à
    própria cobrança (#B41) — o débito existiria sem nenhum caminho até ele.

    ponytail: varredura linear sobre as sessões em memória, uma consulta por
    candidata. Se o histórico quente crescer, indexar por owner.
    """
    for s in sm.list_all():
        if (s.owner == usuario and not s.is_active
                and not _sessao_arquivada(s.session_id)):
            return s
    return None


def _destino_seguro(bruto: str | None) -> str:
    """
    Valida o parâmetro `next` do login.

    Só aceita caminhos internos: um `next` absoluto (`//evil.com`) seria um
    open redirect, transformando a tela de login numa ponte para phishing.
    """
    if bruto and bruto.startswith("/") and not bruto.startswith("//"):
        return bruto
    return url_for("mapa")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Tela de login com as contas de demonstração pré-cadastradas."""
    if request.method == "POST":
        chave = auth.autenticar(
            request.form.get("usuario", ""), request.form.get("senha", "")
        )
        if chave is None:
            flash("Usuário ou senha incorretos.", "error")
            return redirect(url_for("login", next=request.form.get("next", "")))

        perfil = auth.conta(chave)
        user_session["usuario"] = chave
        user_session["nome"]    = perfil["nome"]
        user_session["tipo"]    = perfil["tipo"].value
        user_session["staff"]   = perfil["staff"]
        wallet.garantir_conta(chave, perfil["saldo_inicial"])

        logger.info("Login: %s (staff=%s)", chave, perfil["staff"])
        flash(f"Bem-vindo, {auth.nome_curto(chave)}.", "success")
        return redirect(_destino_seguro(request.form.get("next")))

    if "usuario" in user_session:
        return redirect(url_for("mapa"))

    return render_template(
        "login.html",
        contas=auth.CONTAS,
        senha_demo=auth.SENHA_PADRAO,
        next=request.args.get("next", ""),
    )


@app.route("/logout")
def logout():
    """Encerra a sessão do usuário."""
    user_session.clear()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# ── ROTAS DO SPRINT 1 (mantidas) ──────────────────────────────────────────
# ---------------------------------------------------------------------------

@app.route("/")
def mapa():
    """Página inicial: mapa com postos de recarga."""
    _atualizar_carregadores_livres()
    return render_template("mapa.html", postos=POSTOS)


@app.route("/posto/<posto_id>")
def posto(posto_id: str):
    """Carregadores do posto — agora reflete estado real do SessionManager."""
    if posto_id not in POSTOS:
        flash("Posto não encontrado!", "error")
        return redirect(url_for("mapa"))

    posto_info = POSTOS[posto_id]
    chargers_raw = sm.list_chargers()

    # #R5/#B34 — acumula energia das sessões deste posto sob o lock, evitando
    # corrida com finish_session concorrente (antes _simular_tick rodava solto).
    with _state_lock:
        for cid, sid in chargers_raw.items():
            if sid and cid.startswith(posto_id):
                sess = sm.get_session(sid)
                if sess and sess.is_active:
                    sm.accrue_energy(sid)

    # Estado das reservas vem do servidor, não do localStorage: assim o
    # countdown sobrevive a refresh, troca de aba e troca de máquina.
    reservados  = reservations.ativas_do_posto(posto_id)
    usuario     = user_session.get("usuario", "")
    eh_staff    = bool(user_session.get("staff"))

    # Monta estrutura de carregadores compatível com o template do Sprint 1
    carregadores = {}
    for cid, sid in chargers_raw.items():
        if not cid.startswith(posto_id):
            continue
        num = cid.split("-")[1]
        session = sm.get_session(sid) if sid else None
        reserva = reservados.get(cid)

        # Sessão encerrada que ainda segura o conector: aguardando pagamento.
        aguardando = bool(session and not session.is_active)

        if aguardando:
            status = "aguardando"
        elif sid:
            status = "ocupado"
        elif reserva:
            status = "reservado"
        else:
            status = "livre"

        carregadores[num] = {
            "id":            num,
            "nome":          f"Carregador {num}",
            "status":        status,
            "tipo":          "assinante" if num == "C5" else "publico",
            "usuario_atual": session.user_name if session else None,
            # #B48 — este número é tempo DECORRIDO, não tempo restante: o
            # sistema não sabe quando o motorista vai desplugar. O rótulo no
            # template dizia "Disponível em" e prometia o que não podia
            # cumprir.
            "tempo_em_uso": (
                f"{int(session.duration_minutes)} min"
                if session else None
            ),
            "session_id":    sid,
            "energia_kwh":   round(session.energy_kwh, 2) if session else None,
            "potencia_kw":   session.allocated_power_kw if session else None,
            "custo_brl":     round(session.total_cost_brl, 2) if session else None,
            # True quando este conector específico está com throttle ativo
            "em_throttle":   (
                session.status == SessionStatus.THROTTLED
                if session else False
            ),
            # Sprint 3 — quem pode agir neste card
            "minha_sessao":  bool(session and session.owner == usuario),
            "pode_encerrar": bool(session and not aguardando
                                  and (session.owner == usuario or eh_staff)),
            # Encerrada e não paga: o dono paga, a equipe libera à força.
            "aguardando":    aguardando,
            "pode_pagar":    bool(aguardando and session.owner == usuario),
            "pode_liberar":  bool(aguardando and eh_staff),
            "reservado":     reserva is not None,
            "minha_reserva": bool(reserva and reserva.usuario == usuario),
            "reserva_segundos": reserva.segundos_restantes if reserva else 0,
            "reserva_de":    reserva.usuario if reserva else None,
        }

    # Flag global do posto: True se qualquer conector está throttled
    _atualizar_carregadores_livres()
    posto_em_throttle = posto_info.get("em_throttle", False)

    return render_template(
        "index.html",
        posto=posto_info,
        carregadores=carregadores,
        posto_em_throttle=posto_em_throttle,
        limite_posto_kw=LIMITE_POR_POSTO_KW,
        sinal_reserva=wallet.SINAL_RESERVA_BRL,
        duracao_reserva=reservations.DURACAO_MIN,
        eh_assinante=auth.conta(user_session["usuario"])["tipo"] == UserType.SUBSCRIBER,
    )


@app.route("/posto/<posto_id>/carregador/<carregador_id>")
def formulario(posto_id: str, carregador_id: str):
    """Formulário de nova sessão de recarga em um conector livre."""
    if posto_id not in POSTOS:
        flash("Posto não encontrado!", "error")
        return redirect(url_for("mapa"))

    chargers = sm.list_chargers()
    cid_full = f"{posto_id}-{carregador_id}"

    if cid_full not in chargers:
        flash("Carregador inválido!", "error")
        return redirect(url_for("posto", posto_id=posto_id))

    if chargers[cid_full] is not None:
        flash(f"Carregador {carregador_id} está ocupado!", "error")
        return redirect(url_for("posto", posto_id=posto_id))

    # Recusa aqui, e não depois de o formulário inteiro ser preenchido: quem
    # não é assinante só descobria que o C5 não era para ele ao enviar.
    if (_eh_conector_vip(cid_full)
            and auth.conta(user_session["usuario"])["tipo"] != UserType.SUBSCRIBER):
        flash("O conector C5 é exclusivo para assinantes. "
              "Use um conector de C1 a C4.", "error")
        return redirect(url_for("posto", posto_id=posto_id))

    return render_template(
        "formulario.html",
        posto=POSTOS[posto_id],
        carregador={"id": carregador_id, "nome": f"Carregador {carregador_id}",
                    "tipo": "publico"},
        posto_em_throttle=POSTOS[posto_id].get("em_throttle", False),
        carros=_carros_com_estado(user_session["usuario"]),
    )


def _veiculo_do_formulario(usuario: str) -> tuple[str, bool]:
    """
    Lê o carro escolhido no formulário de início de recarga.

    Returns:
        (placa normalizada, deve_salvar_na_conta)

    Raises:
        ValueError : placa inválida, ou placa "salva" que não é da conta
    """
    escolha = request.form.get("veiculo", "").strip()
    if escolha and escolha != "novo":
        placa = _validar_placa(escolha)
        # Sem esta checagem, bastava editar o HTML para "escolher" um carro
        # salvo em outra conta.
        if usuario and not veiculos.pertence(usuario, placa):
            raise ValueError("Esse carro não está salvo na sua conta.")
        return placa, False

    placa = _validar_placa(request.form.get("placa", ""))
    salvar = bool(usuario) and request.form.get("salvar_veiculo") == "1"
    return placa, salvar


def _carros_com_estado(usuario: str) -> list[dict]:
    """
    Carros da conta, cada um com o conector onde está carregando agora.

    O estado vem das sessões ativas, não do cadastro: é a mesma fonte que o
    `create_session` consulta para recusar o carro que já está carregando.
    """
    carros = veiculos.do_usuario(usuario)
    for carro in carros:
        ativa = sm.sessao_ativa_do_veiculo(carro["placa"])
        carro["carregando_em"] = ativa.charger_id if ativa else None
    return carros


@app.route("/sessao", methods=["POST"])
def processar():
    """
    Processa o formulário do Sprint 1 e cria sessão via SessionManager.
    Mantém compatibilidade com relatorio.html do Sprint 1 para sessão única.
    """
    try:
        posto_id      = request.form.get("posto_id", "P1")
        carregador_id = request.form.get("carregador_id", "C1")
        # Sprint 3 — nome e categoria vêm da conta logada, não do formulário.
        # Antes era possível logar como Amanda e abrir sessão em nome de outro.
        owner         = user_session.get("usuario", "")
        nome_usuario  = user_session.get("nome") or "Usuário Anônimo"
        tipo_str      = user_session.get("tipo", "P").upper()
        hora          = int(request.form.get("hora", 9))
        minuto        = int(request.form.get("minuto", 0))
        duracao_min   = int(request.form.get("duracao", 30))

        if not (0 <= hora <= 23 and 0 <= minuto <= 59):
            raise ValueError("Horário inválido.")
        if not (5 <= duracao_min <= 240):
            raise ValueError("Duração deve ser entre 5 e 240 minutos.")

        user_type = USER_TYPE_MAP.get(tipo_str, UserType.STANDARD)
        cid_full  = f"{posto_id}-{carregador_id}"
        pm_posto  = _get_pm(posto_id)

        # Conector VIP (C5): exclusivo para assinantes.
        if _eh_conector_vip(cid_full) and user_type != UserType.SUBSCRIBER:
            flash(
                "O conector C5 é exclusivo para assinantes. "
                "Usuários Padrão e Corporativo devem usar os conectores C1 a C4.",
                "error",
            )
            return redirect(url_for("posto", posto_id=posto_id))

        # O carro vem de duas formas: um salvo na conta (o campo `veiculo`
        # traz a placa) ou um novo, digitado agora (`veiculo` = "novo").
        vehicle_id, salvar_novo = _veiculo_do_formulario(owner)

        # Conector reservado por outra pessoa não pode ser iniciado.
        reserva_conector = reservations.ativa_do_conector(cid_full)
        if reserva_conector and reserva_conector.usuario != owner:
            flash(
                f"O conector {carregador_id} está reservado por outro usuário.",
                "error",
            )
            return redirect(url_for("posto", posto_id=posto_id))

        # Cria sessão no SessionManager (protegido por lock)
        with _state_lock:
            session = sm.create_session(
                charger_id=cid_full,
                vehicle_id=vehicle_id,
                user_name=nome_usuario,
                user_type=user_type,
                requested_power_kw=11.0,
                owner=owner,
            )
            result = pm_posto.allocate(session)

            if result.rejected:
                sm.finish_session(session.session_id, status=SessionStatus.FAULTED)
                flash(result.message, "error")
                return redirect(url_for("posto", posto_id=posto_id))

            # #B28 — tarifa de demanda usa a ocupação do POSTO da sessão
            tariff = pe.calculate(
                user_type, hora=hora, minuto=minuto,
                occupancy_override=_posto_sms[posto_id].occupancy_ratio()
                if posto_id in _posto_sms else None,
            )
            sm.start_charging(session.session_id, result.granted_kw, tariff.tariff_kwh)
            if result.redistributed and result.granted_kw < 11.0:
                sm.throttle_session(session.session_id, result.granted_kw)
            mb.on_session_start(session)
            # #B24 — emite frames Modbus da redistribuição (ver dashboard_nova_sessao)
            if result.redistributed and result.throttle_events:
                mb.on_throttle(session, result)

        # Só salva o carro novo depois que a recarga começou de fato: se o
        # conector estivesse ocupado, o carro não entraria na conta à toa.
        if salvar_novo:
            veiculos.salvar(owner, vehicle_id, request.form.get("modelo", ""))

        # O usuário compareceu: a reserva é honrada e o sinal vira crédito,
        # que será abatido na tela de pagamento ao encerrar a recarga.
        sinal = reservations.consumir(owner, cid_full)
        if sinal:
            flash(
                f"Reserva honrada — R$ {sinal:.2f} de sinal serão abatidos "
                f"no pagamento.".replace(".", ","),
                "info",
            )

        # Também roda a lógica do Sprint 1 para manter o relatório visual
        sessao_s1 = processar_sessao(
            nome_usuario=nome_usuario,
            tipo_usuario=tipo_str,
            hora_inicio=hora,
            minuto_inicio=minuto,
            duracao_min=duracao_min,
            carregador_id=carregador_id,
        )

        # Injeta dados do Sprint 2 no dicionário do Sprint 1
        sessao_s1["session_id_s2"]    = session.session_id
        sessao_s1["vehicle_id"]       = session.vehicle_id
        sessao_s1["potencia_alocada"] = result.granted_kw
        sessao_s1["tarifa_label"]     = pe.tariff_label(tariff)
        sessao_s1["throttle_msg"]     = result.message if result.redistributed else None
        sessao_s1["tipo_usuario_nome"] = user_type.name

        return render_template(
            "relatorio.html",
            sessao=sessao_s1,
            carregador={"id": carregador_id, "nome": f"Carregador {carregador_id}",
                        "tipo": "publico"},
            posto=POSTOS.get(posto_id, {}),
        )

    except ValueError as e:
        # Volta ao formulário do mesmo conector, e não ao mapa: o erro mais
        # comum aqui é o carro escolhido já estar carregando em outro lugar,
        # e a pessoa só precisa trocar de carro.
        flash(str(e), "error")
        posto_id = request.form.get("posto_id", "")
        carregador_id = request.form.get("carregador_id", "")
        if posto_id in POSTOS and carregador_id:
            return redirect(url_for("formulario", posto_id=posto_id,
                                    carregador_id=carregador_id))
        return redirect(url_for("mapa"))
    except Exception:
        # A mensagem da exceção não vai para a tela: pode conter detalhe
        # interno, e não diz ao motorista nada que ele possa fazer.
        logger.exception("Erro inesperado em /sessao")
        flash("Não foi possível iniciar a recarga. Tente de novo.", "error")
        return redirect(url_for("mapa"))


# ---------------------------------------------------------------------------
# ── ROTAS DO SPRINT 2 ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@app.route("/dashboard")
def dashboard():
    """
    Painel central do Sprint 2.
    Exibe: sessões ativas, painel de potência, log Modbus, tarifas.
    """
    # #B34 — acumula energia sob o lock para evitar corrida com finish_session.
    with _state_lock:
        for s in sm.list_active():
            sm.accrue_energy(s)

    ativas = sm.list_active()
    # #B46 — o painel do operador não pode oferecer conector reservado: o
    # sinal já foi debitado de alguém, e iniciar uma sessão de terceiro ali
    # retinha os R$ 10 como se o dono da reserva não tivesse aparecido.
    reservados_agora = {r.charger_id for r in reservations.todas_ativas()}
    disponíveis = [c for c in sm.available_chargers()
                   if c not in reservados_agora]

    tariff_table_rows = []
    for ut in UserType:
        row = {"tipo": ut.name, "label": ut.value, "tarifas": {}}

        class _LowSM:
            def occupancy_ratio(self): return 0.0

        class _HighSM:
            def occupancy_ratio(self): return 0.85

        pe_low  = PricingEngine(_LowSM())
        pe_high = PricingEngine(_HighSM())

        row["tarifas"]["normal"] = pe_low.calculate(ut, hora=10).tariff_kwh
        row["tarifas"]["pico"]   = pe_low.calculate(ut, hora=19).tariff_kwh
        row["tarifas"]["pico_demanda"] = pe_high.calculate(ut, hora=19).tariff_kwh
        tariff_table_rows.append(row)

    # Dados de potência por posto — cada PM é isolado por instalação física
    NOMES_POSTOS = {
        "P1": "Paulista",
        "P2": "Faria Lima",
        "P3": "Berrini",
    }
    postos_power = []
    total_em_uso   = 0.0
    total_limite   = 0.0
    total_sessions = 0
    for pid in ["P1", "P2", "P3"]:
        pm_p = posto_pms[pid]
        em_uso = round(_posto_sms[pid].total_allocated_power_kw(), 2)
        limite = pm_p.limit_kw
        # max(0) evita o "-0.0 kW" que aparecia quando a soma das potências
        # alocadas estourava o limite por fração de kW (erro de float).
        disponivel = round(max(limite - em_uso, 0.0), 2)
        pct = round((em_uso / limite) * 100, 1) if limite > 0 else 0.0
        n_sessoes = _posto_sms[pid].active_count()
        postos_power.append({
            "id":         pid,
            "nome":       NOMES_POSTOS[pid],
            "em_uso_kw":  em_uso,
            "limite_kw":  limite,
            "disponivel_kw": disponivel,
            "ocupacao_pct": pct,
            "sessoes":    n_sessoes,
            "em_throttle": POSTOS[pid].get("em_throttle", False),
        })
        total_em_uso   += em_uso
        total_limite   += limite
        total_sessions += n_sessoes

    total_em_uso  = round(total_em_uso, 2)
    total_limite  = round(total_limite, 2)
    total_disponivel_kw = round(max(total_limite - total_em_uso, 0.0), 2)
    total_pct = round((total_em_uso / total_limite) * 100, 1) if total_limite > 0 else 0.0

    # Histórico consolidado de todos os PowerManagers (últimas 5 decisões)
    historico_consolidado = []
    for pid in ["P1", "P2", "P3"]:
        historico_consolidado.extend(posto_pms[pid].history)
    historico_consolidado.sort(key=lambda r: r.message)  # estável sem timestamp; Sprint 3 adiciona ts

    # Detalhamento por posto: sessões ativas e decisões de potência agrupadas,
    # para que o painel mostre claramente o que acontece em cada instalação.
    postos_detalhe = []
    for pid in ["P1", "P2", "P3"]:
        sessoes_posto = sorted(
            _posto_sms[pid].list_active(),
            key=lambda s: s.charger_id,
        )
        decisoes_posto = list(posto_pms[pid].history)[-5:]
        postos_detalhe.append({
            "id":         pid,
            "nome":       NOMES_POSTOS[pid],
            "sessoes":    sessoes_posto,
            "decisoes":   decisoes_posto,
            "em_uso_kw":  round(_posto_sms[pid].total_allocated_power_kw(), 2),
            "limite_kw":  posto_pms[pid].limit_kw,
            "ocupacao_pct": round(
                (_posto_sms[pid].total_allocated_power_kw() / posto_pms[pid].limit_kw) * 100, 1
            ) if posto_pms[pid].limit_kw > 0 else 0.0,
            "em_throttle": POSTOS[pid].get("em_throttle", False),
        })

    return render_template(
        "dashboard.html",
        sessoes_ativas=ativas,
        disponiveis=disponíveis[:8],
        total_disponivel=len(disponíveis),
        # Agregado global (soma coerente dos 3 postos)
        potencia_em_uso=total_em_uso,
        potencia_limite=total_limite,
        ocupacao_pct=total_pct,
        available_kw=total_disponivel_kw,
        total_sessoes=total_sessions,
        # Por posto (para os mini-cards)
        postos_power=postos_power,
        # Detalhamento por posto (sessões + decisões agrupadas)
        postos_detalhe=postos_detalhe,
        historico_pm=historico_consolidado[-5:],
        frames_modbus=mb.get_log()[-10:],
        total_frames=mb.frame_count(),
        tariff_rows=tariff_table_rows,
        ocupacao_rede=round(sm.occupancy_ratio() * 100, 1),
    )


@app.route("/dashboard/nova-sessao", methods=["POST"])
def dashboard_nova_sessao():
    """Cria sessão via formulário do dashboard."""
    try:
        charger_id = request.form.get("charger_id", "").strip()
        vehicle_id = request.form.get("vehicle_id", "").strip().upper()
        user_name  = request.form.get("user_name", "").strip() or "Usuário Anônimo"
        tipo_str   = request.form.get("user_type", "P").upper()
        hora_str   = request.form.get("hora", "")
        pot_str    = request.form.get("potencia", "11.0")

        if not charger_id:
            flash("Selecione um carregador.", "error")
            return redirect(url_for("dashboard"))

        # #B31 — valida e normaliza a placa (formato BR antigo ou Mercosul)
        vehicle_id = _validar_placa(vehicle_id)

        # #B30 — valida a hora de início (0–23); vazio = hora atual
        hora      = _validar_hora(hora_str)
        potencia  = float(pot_str) if pot_str else 11.0
        user_type = USER_TYPE_MAP.get(tipo_str, UserType.STANDARD)
        # Extrai o posto_id do charger_id (ex: "P1-C3" → "P1")
        posto_id  = charger_id.split("-")[0] if "-" in charger_id else "P1"
        pm_posto  = _get_pm(posto_id)

        # Conector VIP (C5): exclusivo para assinantes. Usuários Padrão e
        # Corporativo devem usar os conectores públicos (C1–C4).
        if _eh_conector_vip(charger_id) and user_type != UserType.SUBSCRIBER:
            flash(
                "O conector C5 é exclusivo para assinantes. "
                "Usuários Padrão e Corporativo devem usar os conectores C1 a C4.",
                "error",
            )
            return redirect(url_for("dashboard"))

        # #B46 — mesma guarda do fluxo do motorista: iniciar sessão em cima
        # de uma reserva paga faria o dono dela perder o sinal sem ter
        # deixado de comparecer.
        reserva = reservations.ativa_do_conector(charger_id)
        if reserva:
            flash(
                f"O conector {charger_id} está reservado por {reserva.usuario} "
                f"até {reserva.expira_em.strftime('%H:%M')}. "
                f"Cancele a reserva antes de iniciar outra sessão.",
                "error",
            )
            return redirect(url_for("dashboard"))

        with _state_lock:
            session = sm.create_session(charger_id, vehicle_id, user_name,
                                        user_type, potencia)
            result  = pm_posto.allocate(session)

            if result.rejected:
                sm.finish_session(session.session_id, status=SessionStatus.FAULTED)
                flash(result.message, "error")
                return redirect(url_for("dashboard"))

            # #B28 — tarifa de demanda usa a ocupação do POSTO da sessão
            tariff = pe.calculate(
                user_type, hora=hora,
                occupancy_override=_posto_sms[posto_id].occupancy_ratio()
                if posto_id in _posto_sms else None,
            )
            sm.start_charging(session.session_id, result.granted_kw, tariff.tariff_kwh)
            # Se a potência concedida é menor que a solicitada (redistribuição),
            # o novo conector também entra como THROTTLED — não só os existentes.
            if result.redistributed and result.granted_kw < potencia:
                sm.throttle_session(session.session_id, result.granted_kw)
            mb.on_session_start(session)
            # #B24 — emite os frames Modbus de redistribuição (reescritas do
            # registrador 10029 nas sessões existentes que foram throttled).
            # Sem isso, a redistribuição não aparecia no log do protocolo.
            if result.redistributed and result.throttle_events:
                mb.on_throttle(session, result)

        flash(
            f"Sessão {session.session_id} iniciada — "
            f"{result.granted_kw:.1f} kW | {pe.tariff_label(tariff)}",
            "success",
        )

        if result.redistributed:
            flash(
                f"Redistribuição automática: {result.message}",
                "warning",
            )

    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        logger.exception("Erro em /dashboard/nova-sessao")
        flash(f"Erro inesperado: {e}", "error")

    return redirect(url_for("dashboard"))


@app.route("/dashboard/encerrar", methods=["POST"])
def dashboard_encerrar():
    """Encerra sessão e rebalanceia potência."""
    session_id = request.form.get("session_id", "").strip()
    if not session_id:
        flash("ID de sessão inválido.", "error")
        return redirect(url_for("dashboard"))

    try:
        session = sm.get_session(session_id)
        if not session:
            flash(f"Sessão {session_id} não encontrada.", "error")
            return redirect(url_for("dashboard"))

        posto_id = session.charger_id.split("-")[0]
        pm_posto = _get_pm(posto_id)

        with _state_lock:
            # #B33 — finish_session já chama accrue_energy internamente; o
            # _simular_tick anterior era redundante e foi removido.
            sm.finish_session(session_id)
            mb.on_session_end(session)
            rb = pm_posto.rebalance()
            # #B34 — emite o Modbus de rebalanceamento ainda dentro do lock,
            # mantendo a ordem dos frames consistente com o estado das sessões.
            if rb:
                mb.on_rebalance(rb)

        if rb:
            flash(f"{rb.message}", "info")

        flash(
            f"Sessão {session_id} encerrada — "
            f"{session.energy_kwh:.3f} kWh | R$ {session.total_cost_brl:.2f}",
            "success",
        )
    except Exception as e:
        logger.exception("Erro em /dashboard/encerrar")
        flash(f"Erro: {e}", "error")

    return redirect(url_for("dashboard"))


@app.route("/api/status")
def api_status():
    """
    Endpoint JSON para polling do dashboard (atualização em tempo real).
    Chamado a cada 2 segundos pelo JavaScript do dashboard e do relatório.
    """
    # #B34 — acumula energia das sessões ativas sob o lock, evitando corrida
    # com finish_session concorrente em modo multi-thread.
    # #B25 — emite a leitura de medidores (MeterRead) de cada sessão ativa, de
    # modo que os registradores Modbus 10015 (potência) e 10016 (energia)
    # reflitam o estado em tempo real durante o polling — antes só atualizavam
    # no início e no fim da sessão.
    with _state_lock:
        ativas = sm.list_active()
        for s in ativas:
            sm.accrue_energy(s)
            mb.on_meter_read(s)

    sessoes_json = []
    for s in ativas:
        sessoes_json.append({
            "session_id":       s.session_id,
            "charger_id":       s.charger_id,
            "user_name":        s.user_name,
            "user_type":        s.user_type.value,
            "vehicle_id":       s.vehicle_id,
            "status":           s.status.value,
            "allocated_kw":     s.allocated_power_kw,
            "energy_kwh":       round(s.energy_kwh, 3),
            "cost_brl":         round(s.total_cost_brl, 2),
            "tariff_kwh":       round(s.tariff_kwh, 4),
            "duration_min":     round(s.duration_minutes, 1),
        })

    # Agrega dados por posto para o polling do dashboard
    postos_status = {}
    total_em_uso_api  = 0.0
    total_limite_api  = 0.0
    for pid in ["P1", "P2", "P3"]:
        pm_p   = posto_pms[pid]
        em_uso = round(_posto_sms[pid].total_allocated_power_kw(), 2)
        limite = pm_p.limit_kw
        postos_status[pid] = {
            "em_uso_kw":     em_uso,
            "limite_kw":     limite,
            "disponivel_kw": round(max(limite - em_uso, 0.0), 2),
            "ocupacao_pct":  round((em_uso / limite) * 100, 1) if limite > 0 else 0.0,
            "sessoes":       _posto_sms[pid].active_count(),
        }
        total_em_uso_api += em_uso
        total_limite_api += limite

    total_em_uso_api  = round(total_em_uso_api, 2)
    total_limite_api  = round(total_limite_api, 2)
    total_pct_api     = round((total_em_uso_api / total_limite_api) * 100, 1) if total_limite_api > 0 else 0.0

    return jsonify({
        "sessoes_ativas":   sessoes_json,
        "total_ativas":     sm.active_count(),
        "potencia_em_uso":  total_em_uso_api,
        "potencia_limite":  total_limite_api,
        "ocupacao_pct":     total_pct_api,
        "available_kw":     round(max(total_limite_api - total_em_uso_api, 0.0), 2),
        "postos":           postos_status,
        "total_frames":     mb.frame_count(),
        "timestamp":        datetime.datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/relatorio")
def relatorio_consolidado():
    """Relatório completo de todas as sessões (ativas e encerradas)."""
    # #B34 — acumula energia sob o lock para evitar corrida com finish_session.
    with _state_lock:
        for s in sm.list_active():
            sm.accrue_energy(s)

    todas  = sm.list_all()

    # #B35 — separa receita realizada (sessões encerradas, custo final) de
    # receita projetada (sessões ativas, custo parcial que ainda cresce).
    # #B45 — "realizada" passou a exigir pagamento confirmado. Encerrada não
    # é sinônimo de paga desde que o motorista pode fechar a aba na tela de
    # pagamento (#B41): esse dinheiro é pendente, não receita, e contá-lo aqui
    # fazia este relatório divergir para sempre do KPI do /admin.
    encerradas = [s for s in todas if not s.is_active]
    ativas_lst = [s for s in todas if s.is_active]
    # Uma consulta só para todas as encerradas, em vez de uma conexão SQLite
    # por sessão. A separação depois é por session_id: comparar as próprias
    # dataclasses faria o `in` percorrer os 17 campos de cada objeto.
    arquivadas = _sessoes_arquivadas(s.session_id for s in encerradas)
    pagas      = [s for s in encerradas if s.session_id in arquivadas]
    pendentes  = [s for s in encerradas if s.session_id not in arquivadas]
    receita_realizada = round(sum(s.total_cost_brl for s in pagas), 2)
    receita_pendente  = round(sum(s.total_cost_brl for s in pendentes), 2)
    receita_projetada = round(sum(s.total_cost_brl for s in ativas_lst), 2)

    # 'decisoes' soma o histórico dos 3 PowerManagers (antes só contava P1).
    total_decisoes = sum(len(posto_pms[pid].history) for pid in ["P1", "P2", "P3"])

    # O relatório mostra o estado quente (memória); o histórico pago vive no
    # SQLite e é o que o painel do operador soma. Os dois números divergem por
    # construção, então a tela diz de onde cada um vem em vez de deixar o
    # operador supor que são a mesma coisa.
    hist = db.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(custo_brl), 0) AS t FROM sessoes")

    totais = {
        "sessoes":            len(todas),
        "historico_sessoes":  hist["n"] if hist else 0,
        "historico_receita":  round(hist["t"], 2) if hist else 0.0,
        "ativas":             sm.active_count(),
        "energia":            round(sum(s.energy_kwh for s in todas), 3),
        # 'receita' mantida para compatibilidade com o template = total geral
        "receita":            round(receita_realizada + receita_pendente
                                    + receita_projetada, 2),
        "receita_realizada":  receita_realizada,
        "receita_pendente":   receita_pendente,
        "receita_projetada":  receita_projetada,
        "frames":             mb.frame_count(),
        "decisoes":           total_decisoes,
    }

    historico_pm_todos = []
    for pid in ["P1", "P2", "P3"]:
        historico_pm_todos.extend(posto_pms[pid].history)

    return render_template(
        "relatorio_consolidado.html",
        sessoes=todas,
        totais=totais,
        historico_pm=historico_pm_todos,
        reg_snapshot=mb.register_snapshot(),
    )


@app.route("/modbus-log")
def modbus_log():
    """Página dedicada ao log de frames Modbus TCP."""
    return render_template(
        "modbus_log.html",
        frames=mb.get_log(),
        summary=mb.print_summary(),
        total_frames=mb.frame_count(),
        reg_snapshot=mb.register_snapshot(),
    )


_suites_cache: list[dict] | None = None


def _suites_de_teste() -> list[dict]:
    """
    Lê do pytest as classes de teste e quantos casos cada uma tem.

    Antes esta lista era escrita à mão no template, com o total fixo em 61 —
    um número que envelheceu junto com a suíte e passou a mostrar ao operador
    uma contagem que não batia com nada. Agora a tela pergunta ao pytest.

    O resultado é guardado em memória: a coleta leva cerca de um segundo e o
    conjunto de testes não muda enquanto o servidor está de pé.
    """
    global _suites_cache
    if _suites_cache is not None:
        return _suites_cache

    import pathlib
    import re
    import subprocess
    import sys

    try:
        saida = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--collect-only"],
            cwd=pathlib.Path(__file__).parent, capture_output=True,
            text=True, timeout=120,
        ).stdout
    except (subprocess.SubprocessError, OSError) as erro:
        # A tela continua utilizável sem a lista: o botão "Todos" sempre roda.
        logger.warning("Não consegui coletar as suítes de teste: %s", erro)
        _suites_cache = []
        return _suites_cache

    contagem: dict[str, int] = {}
    for linha in saida.splitlines():
        achado = re.match(r"test_chargegrid\.py::(\w+)::", linha)
        if achado:
            contagem[achado.group(1)] = contagem.get(achado.group(1), 0) + 1

    def rotulo(classe: str) -> str:
        """TestPowerManagerAlocacao → 'Power Manager Alocação'."""
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", classe[4:]) or classe

    _suites_cache = [{"classe": c, "rotulo": rotulo(c), "casos": n}
                     for c, n in sorted(contagem.items(),
                                        key=lambda kv: (-kv[1], kv[0]))]
    return _suites_cache


@app.route("/testes")
def testes():
    """Página de execução de testes automatizados no navegador."""
    suites = _suites_de_teste()
    return render_template("testes.html", suites=suites,
                           total_casos=sum(s["casos"] for s in suites))


@app.route("/api/testes/run", methods=["POST"])
def api_testes_run():
    """
    Executa os testes automatizados do pytest e retorna o resultado como JSON.
    Permite rodar os testes diretamente no navegador sem precisar do terminal.
    """
    import subprocess
    import sys

    modulo = request.json.get("modulo", "") if request.is_json else ""
    cmd = [
        sys.executable, "-m", "pytest",
        "-v", "--tb=short", "--no-header",
        "--color=no",
    ]
    if not modulo:
        # Sem filtro: roda o arquivo inteiro.
        cmd.append("test_chargegrid.py")
    elif " or " in modulo:
        # Expressão -k (várias classes agrupadas): roda o arquivo filtrando por -k.
        cmd.extend(["test_chargegrid.py", "-k", modulo])
    else:
        # Classe única: usa a sintaxe ::Classe (sem o arquivo base, que anularia
        # o filtro e coletaria todos os testes).
        cmd.append(f"test_chargegrid.py::{modulo}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        output   = proc.stdout + proc.stderr
        passed   = output.count(" PASSED")
        failed   = output.count(" FAILED")
        errors   = output.count(" ERROR")
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        output     = "Timeout: os testes demoraram mais de 60 segundos."
        passed     = failed = errors = 0
        returncode = -1
    except Exception as e:
        output     = f"Erro ao executar pytest: {e}"
        passed     = failed = errors = 0
        returncode = -1

    return jsonify({
        "output":     output,
        "passed":     passed,
        "failed":     failed,
        "errors":     errors,
        "returncode": returncode,
        "ok":         returncode == 0,
    })


# ---------------------------------------------------------------------------
# ── SPRINT 3 · CARTEIRA NEXUSCOIN ─────────────────────────────────────────
# ---------------------------------------------------------------------------

VALORES_RECARGA = [20.0, 50.0, 100.0, 200.0]


@app.route("/carteira")
def carteira():
    """Saldo, extrato e recarga da carteira NexusCoin do usuário logado."""
    usuario = user_session["usuario"]
    perfil  = auth.conta(usuario)
    return render_template(
        "carteira.html",
        saldo=wallet.saldo(usuario),
        extrato=wallet.extrato(usuario),
        cashback_total=wallet.total_cashback(usuario),
        valores=VALORES_RECARGA,
        cartao_final=perfil["cartao_final"],
        cartao_bandeira=perfil["cartao_bandeira"],
        volta_para=request.args.get("next", ""),
    )


@app.route("/carteira/recarregar", methods=["POST"])
def carteira_recarregar():
    """
    Simula a compra de NexusCoin por Pix ou cartão salvo.

    Nenhum gateway real é acionado: a confirmação é imediata, como esperado
    de um ambiente de demonstração. O valor entra como uma transação do tipo
    RECARGA, visível no extrato.
    """
    destino = _destino_seguro(request.form.get("next")) \
        if request.form.get("next") else url_for("carteira")
    try:
        bruto  = request.form.get("valor", "0").replace(".", "").replace(",", ".")
        valor  = round(float(bruto), 2)
        metodo = billing.normalizar_metodo(request.form.get("metodo", "PIX"))
        if metodo == billing.METODO_NEXUSCOIN:
            raise ValueError("Não é possível comprar NexusCoin com NexusCoin.")
        if not (wallet.RECARGA_MINIMA <= valor <= wallet.RECARGA_MAXIMA):
            raise ValueError(
                f"O valor da recarga deve estar entre "
                f"R$ {wallet.RECARGA_MINIMA:,.2f} e R$ {wallet.RECARGA_MAXIMA:,.2f}."
            )

        novo = wallet.creditar(
            user_session["usuario"], valor, "RECARGA",
            f"Recarga via {billing.rotulo(metodo)}",
        )
        flash(
            f"{_brl(valor)} NC adicionados. Saldo: {_brl(novo)} NC.",
            "success",
        )
    except ValueError as e:
        flash(str(e), "error")
    except Exception:
        logger.exception("Erro em /carteira/recarregar")
        flash("Não foi possível concluir a recarga. Tente novamente.", "error")

    return redirect(destino)


# ---------------------------------------------------------------------------
# ── SPRINT 3 · RESERVA DE CONECTOR ────────────────────────────────────────
# ---------------------------------------------------------------------------

@app.route("/api/reservar", methods=["POST"])
def api_reservar():
    """
    Cria uma reserva de conector, debitando o sinal em NexusCoin.

    Respostas:
        200 → {ok: true, segundos, saldo}
        400 → conector ocupado/reservado ou usuário já com reserva
        402 → saldo insuficiente (a interface redireciona para a carteira)
    """
    dados      = request.get_json(silent=True) or {}
    posto_id   = str(dados.get("posto_id", "")).strip()
    conector   = str(dados.get("carregador_id", "")).strip()
    charger_id = f"{posto_id}-{conector}"
    usuario    = user_session["usuario"]

    try:
        if posto_id not in POSTOS or charger_id not in sm.list_chargers():
            raise ValueError("Conector inválido.")
        if not sm.is_charger_available(charger_id):
            raise ValueError("Este conector já está em uso.")
        # O C5 só aceita assinante. Sem esta checagem a reserva era criada e o
        # sinal debitado, mas /sessao recusava o início depois — o dinheiro
        # ficava preso numa reserva impossível de usar, e virava taxa por
        # não comparecimento quando os 15 minutos venciam.
        if (_eh_conector_vip(charger_id)
                and auth.conta(usuario)["tipo"] != UserType.SUBSCRIBER):
            raise ValueError(
                "O conector C5 é exclusivo para assinantes. "
                "Reserve um conector de C1 a C4."
            )

        reserva = reservations.criar(usuario, charger_id)
        return jsonify({
            "ok": True,
            "segundos": reserva.segundos_restantes,
            "saldo": wallet.saldo(usuario),
            "sinal": reserva.sinal_brl,
        })
    except wallet.SaldoInsuficiente as e:
        return jsonify({
            "ok": False, "erro": str(e), "acao": "recarregar",
            "url": url_for("carteira", next=request.referrer or url_for("mapa")),
        }), 402
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    except Exception:
        logger.exception("Erro em /api/reservar")
        return jsonify({"ok": False, "erro": "Erro interno do servidor."}), 500


@app.route("/api/reserva/cancelar", methods=["POST"])
def api_reserva_cancelar():
    """Cancela a reserva dentro do prazo e estorna o sinal integralmente."""
    dados      = request.get_json(silent=True) or {}
    charger_id = f"{dados.get('posto_id', '')}-{dados.get('carregador_id', '')}"
    usuario    = user_session["usuario"]

    try:
        estornado = reservations.cancelar(usuario, charger_id)
        return jsonify({
            "ok": True, "estornado": estornado, "saldo": wallet.saldo(usuario),
        })
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    except Exception:
        logger.exception("Erro em /api/reserva/cancelar")
        return jsonify({"ok": False, "erro": "Erro interno do servidor."}), 500


# ---------------------------------------------------------------------------
# ── SPRINT 3 · ENCERRAMENTO E PAGAMENTO ───────────────────────────────────
# ---------------------------------------------------------------------------

def _sessao_arquivada(session_id: str):
    """Linha da tabela `sessoes` para esta sessão, ou None se ainda não paga."""
    return db.query_one("SELECT * FROM sessoes WHERE session_id = ?", (session_id,))


def _sessoes_arquivadas(session_ids) -> set:
    """
    Quais dos IDs informados já estão arquivados (isto é, pagos).

    Existe para o relatório não abrir uma conexão SQLite por sessão em tela.
    Devolve um set para que a checagem de pertencimento seja O(1).
    """
    ids = list(session_ids)
    if not ids:
        return set()
    marcadores = ",".join("?" * len(ids))
    linhas = db.query_all(
        f"SELECT session_id FROM sessoes WHERE session_id IN ({marcadores})",
        ids,
    )
    return {linha["session_id"] for linha in linhas}


def _sinal_da_reserva(usuario: str, charger_id: str) -> float:
    """
    Sinal de reserva a abater no pagamento deste conector.

    Resolve os dois estados possíveis da reserva no momento do pagamento:
      - ainda ATIVA  → `consumir` a marca como usada e devolve o valor
      - já USADA     → `sinal_creditado` relê o valor

    Precisa estar nas duas rotas de pagamento. Só na renderização da tela não
    basta: um POST de confirmação que chegasse sem a tela ter sido carregada
    (retomada de sessão, back/forward, cliente automatizado) perderia o
    abatimento silenciosamente — o usuário pagaria os R$ 10 duas vezes.
    """
    return (reservations.consumir(usuario, charger_id)
            or reservations.sinal_creditado(usuario, charger_id))


def _arquivar_sessao(sessao, usuario: str, metodo: str,
                     sinal: float, cashback: float) -> None:
    """
    Grava a sessão encerrada e paga no histórico.

    `INSERT OR IGNORE` torna a operação idempotente: um duplo-clique em
    "Confirmar pagamento" não gera uma segunda linha nem uma segunda cobrança
    (a rota confere `_sessao_arquivada` antes de debitar).
    """
    db.execute(
        "INSERT OR IGNORE INTO sessoes ("
        " session_id, usuario, charger_id, station_id, vehicle_id, user_name,"
        " user_type, inicio, fim, hora_inicio, duracao_min, potencia_kw,"
        " energia_kwh, tarifa_kwh, custo_brl, metodo_pagto, sinal_abatido,"
        " cashback_nc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sessao.session_id, usuario, sessao.charger_id, sessao.station_id,
            sessao.vehicle_id, sessao.user_name, sessao.user_type.value,
            sessao.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            (sessao.end_time or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
            sessao.start_time.hour,
            round(sessao.duration_minutes, 2),
            sessao.allocated_power_kw,
            round(sessao.energy_kwh, 3),
            round(sessao.tariff_kwh, 4),
            round(sessao.total_cost_brl, 2),
            metodo, round(sinal, 2), round(cashback, 2),
        ),
    )


@app.route("/sessao/<session_id>/encerrar", methods=["POST"])
def encerrar_recarga(session_id: str):
    """
    Encerra a recarga do usuário e o envia para a tela de pagamento.

    Dois fluxos distintos, decididos por quem clicou:

      - motorista na própria recarga → a energia para, mas o conector CONTINUA
        ocupado até o pagamento. Sair da tela de pagamento não devolve a vaga
        de graça (#B41).
      - equipe do posto numa recarga de terceiro → é operação, não compra:
        encerra e libera o conector ali mesmo, como /dashboard/encerrar. A
        cobrança fica pendente para o dono da sessão (#B42).
    """
    sessao = sm.get_session(session_id)
    if sessao is None:
        flash("Sessão não encontrada.", "error")
        return redirect(url_for("mapa"))

    usuario   = user_session["usuario"]
    eh_staff  = bool(user_session.get("staff"))
    minha     = sessao.owner == usuario
    if not minha and not eh_staff:
        flash("Esta recarga pertence a outro usuário.", "error")
        return redirect(url_for("posto", posto_id=sessao.station_id))

    # Operação da equipe: libera o conector sem passar pelo caixa.
    operacao = eh_staff and not minha

    posto_id = sessao.charger_id.split("-")[0]
    try:
        with _state_lock:
            sm.finish_session(session_id, liberar=operacao)
            mb.on_session_end(sessao)
            rb = _get_pm(posto_id).rebalance()
            if rb:
                mb.on_rebalance(rb)
        # A mensagem do rebalanceamento é linguagem de operação ("3 sessões
        # restauradas, carga 32.3/33.0 kW"). Útil para a equipe do posto,
        # ruído para quem só quer pagar e ir embora.
        if rb and eh_staff:
            flash(rb.message, "info")
    except Exception:
        logger.exception("Erro ao encerrar sessão %s", session_id)
        flash("Não foi possível encerrar a recarga.", "error")
        return redirect(url_for("posto", posto_id=posto_id))

    if operacao:
        flash(
            f"Conector {sessao.charger_id} liberado. "
            f"R$ {sessao.total_cost_brl:.2f} seguem pendentes para "
            f"{sessao.user_name}.",
            "info",
        )
        return redirect(url_for("posto", posto_id=posto_id))

    return redirect(url_for("pagamento", session_id=session_id))


@app.route("/sessao/<session_id>/liberar", methods=["POST"])
def liberar_conector(session_id: str):
    """Equipe do posto desocupa um conector cuja sessão terminou sem pagamento."""
    sessao = sm.get_session(session_id)
    if sessao is None:
        flash("Sessão não encontrada.", "error")
        return redirect(url_for("mapa"))

    posto_id = sessao.charger_id.split("-")[0]
    with _state_lock:
        sm.release_charger(session_id)
        rb = _get_pm(posto_id).rebalance()
        if rb:
            mb.on_rebalance(rb)

    flash(f"Conector {sessao.charger_id} liberado.", "info")
    return redirect(url_for("posto", posto_id=posto_id))


@app.route("/pagamento/<session_id>")
def pagamento(session_id: str):
    """Tela de pagamento: resumo da recarga e os três métodos disponíveis."""
    sessao = sm.get_session(session_id)
    if sessao is None:
        flash("Sessão não encontrada.", "error")
        return redirect(url_for("mapa"))
    if sessao.is_active:
        flash("Encerre a recarga antes de pagar.", "warning")
        return redirect(url_for("posto", posto_id=sessao.station_id))

    usuario = user_session["usuario"]
    if sessao.owner and sessao.owner != usuario and not user_session.get("staff"):
        flash("Esta recarga pertence a outro usuário.", "error")
        return redirect(url_for("mapa"))

    if _sessao_arquivada(session_id):
        return redirect(url_for("recibo", session_id=session_id))

    sinal    = _sinal_da_reserva(usuario, sessao.charger_id)
    cobranca = billing.calcular(sessao, sinal)
    perfil   = auth.conta(usuario)

    return render_template(
        "totem_pagamento.html" if _modo() == "totem" else "pagamento.html",
        sessao=sessao,
        posto=POSTOS.get(sessao.station_id, {}),
        cobranca=cobranca,
        saldo=wallet.saldo(usuario),
        tem_saldo=wallet.pode_pagar(usuario, cobranca.total_brl),
        cartao_final=perfil["cartao_final"],
        cartao_bandeira=perfil["cartao_bandeira"],
        qr_svg=qr_svg(f"CGI|{session_id}|{cobranca.total_brl:.2f}",
                      rotulo="QR Code do Pix"),
    )


def _url_do_recibo(session_id: str) -> str:
    """O recibo do app, ou o do totem quando o pagamento foi feito no totem."""
    if _modo() == "totem":
        return url_for("totem_recibo", session_id=session_id)
    return url_for("recibo", session_id=session_id)


@app.route("/pagamento/<session_id>/confirmar", methods=["POST"])
def pagamento_confirmar(session_id: str):
    """
    Efetiva o pagamento pelo método escolhido e emite o recibo.

    NexusCoin debita a carteira e credita 10% de cashback. Pix e cartão são
    pagamentos externos simulados: não tocam a carteira e não geram cashback.
    Em todos os casos a sessão é arquivada no histórico.
    """
    sessao = sm.get_session(session_id)
    if sessao is None:
        flash("Sessão não encontrada.", "error")
        return redirect(url_for("mapa"))

    usuario = user_session["usuario"]

    # A mesma guarda do GET desta tela. Sem ela o POST aceitava pagar a recarga
    # de outra pessoa: a carteira de quem chamava era debitada e a sessão ia
    # para o histórico com o nome errado. Também é o que impede uma sessão
    # avulsa, cujo dono é um token, de ser arquivada por um usuário logado
    # fora do fluxo do totem, que é quem devolve a caução.
    if sessao.owner and sessao.owner != usuario and not user_session.get("staff"):
        flash("Esta recarga pertence a outro usuário.", "error")
        return redirect(url_for("mapa"))

    # Idempotência: sessão já paga vai direto ao recibo, sem nova cobrança.
    if _sessao_arquivada(session_id):
        return redirect(_url_do_recibo(session_id))

    try:
        metodo   = billing.normalizar_metodo(request.form.get("metodo", ""))
        sinal    = _sinal_da_reserva(usuario, sessao.charger_id)
        cobranca = billing.calcular(sessao, sinal)
        cashback = 0.0

        if metodo == billing.METODO_NEXUSCOIN and cobranca.total_brl > 0:
            wallet.debitar(
                usuario, cobranca.total_brl, "PAGAMENTO",
                f"Recarga {sessao.charger_id} · {sessao.session_id}",
            )
            cashback = cobranca.cashback_nc
            if cashback > 0:
                wallet.creditar(
                    usuario, cashback, "CASHBACK",
                    f"Cashback {int(wallet.CASHBACK_NEXUSCOIN * 100)}% · "
                    f"{sessao.session_id}",
                )

        _arquivar_sessao(sessao, usuario, metodo, cobranca.sinal_brl, cashback)

        # Pago: agora sim o carro sai e a vaga volta para a fila (#B41).
        with _state_lock:
            sm.release_charger(session_id)
            rb = _get_pm(sessao.station_id).rebalance()
            if rb:
                mb.on_rebalance(rb)

        logger.info("Pagamento confirmado: %s | %s | R$ %.2f | cashback %.2f",
                    session_id, metodo, cobranca.total_brl, cashback)
        return redirect(_url_do_recibo(session_id))

    except wallet.SaldoInsuficiente as e:
        flash(str(e), "error")
        return redirect(url_for("pagamento", session_id=session_id))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("pagamento", session_id=session_id))
    except Exception:
        logger.exception("Erro em /pagamento/confirmar")
        flash("Não foi possível concluir o pagamento.", "error")
        return redirect(url_for("pagamento", session_id=session_id))


@app.route("/recibo/<session_id>")
def recibo(session_id: str):
    """Comprovante da recarga paga."""
    linha = _sessao_arquivada(session_id)
    if linha is None:
        flash("Recibo indisponível: esta sessão ainda não foi paga.", "warning")
        return redirect(url_for("mapa"))

    usuario = user_session["usuario"]
    if linha["usuario"] != usuario and not user_session.get("staff"):
        flash("Este recibo pertence a outro usuário.", "error")
        return redirect(url_for("mapa"))

    dados  = dict(linha)
    pago   = round(dados["custo_brl"] - dados["sinal_abatido"], 2)
    return render_template(
        "recibo.html",
        r=dados,
        pago=pago,
        metodo_label=billing.rotulo(dados["metodo_pagto"]),
        saldo=wallet.saldo(usuario),
        cashback_total=wallet.total_cashback(usuario),
        posto=POSTOS.get(dados["station_id"], {}),
    )


def _ip_local() -> str:
    """IP local para o QR Code — prioriza LAN física sobre túnel de VPN."""
    import socket
    candidatos = []
    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
        candidatos.extend(ips)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        candidatos.insert(0, s.getsockname()[0])
        s.close()
    except OSError:
        pass
    for ip in candidatos:
        if ip.startswith("192.168.") or ip.startswith("10."):
            return ip
    for ip in candidatos:
        if not ip.startswith("127."):
            return ip
    return "127.0.0.1"


# ---------------------------------------------------------------------------
# ── SPRINT 3 · MODO APP / MODO TOTEM ──────────────────────────────────────
# ---------------------------------------------------------------------------
#
# O mesmo sistema tem duas caras. O **app** é o celular do motorista: login,
# mapa, reserva, carteira. O **totem** é a tela de toque ao lado de um
# conector: controla só aquele conector, entra com a conta pelo QR do celular
# ou libera sem conta mediante caução, e esquece quem usou ao terminar.
#
# Numa instalação real seriam dois clientes. Aqui são dois modos do mesmo
# servidor, alternados por um botão — o que permite demonstrar os dois lados
# no mesmo navegador.

MODOS: tuple[str, ...] = ("app", "totem")
COOKIE_MODO: str = "modo"
COOKIE_TOTEM: str = "totem_cid"

# Telas do totem. No modo totem, qualquer outra rota volta para o início do
# totem; no modo app, estas voltam para o login.
ROTAS_TOTEM: set[str] = {
    "totem_home", "totem_configurar", "totem_entrar", "totem_entrar_estado",
    "totem_veiculo", "totem_sem_conta", "totem_sinal", "totem_carregando",
    "totem_carregando_status", "totem_encerrar", "totem_recibo", "totem_sair",
}
# O fluxo com conta no totem reaproveita estas rotas do app: a regra de
# encerrar e de pagar é a mesma, só a tela muda.
ROTAS_TOTEM_EMPRESTADAS: set[str] = {
    "encerrar_recarga", "pagamento", "pagamento_confirmar",
}
# Valem nos dois modos: são o celular do motorista, não a tela do totem.
ROTAS_DOS_DOIS_MODOS: set[str] = {
    "static", "trocar_modo", "celular_parear", "celular_parear_status",
    "celular_parear_encerrar", "avulso_sessao", "avulso_status", "avulso_encerrar", "avulso_pagar_excedente",
}
ROTAS_PUBLICAS |= ROTAS_TOTEM | {
    "trocar_modo", "celular_parear", "celular_parear_status",
    "celular_parear_encerrar", "avulso_status", "avulso_encerrar", "avulso_pagar_excedente",
}




def _modo() -> str:
    """Modo atual deste navegador: "app" (padrão) ou "totem"."""
    modo = request.cookies.get(COOKIE_MODO, "app")
    return modo if modo in MODOS else "app"


def _conectores_de_totem() -> list[str]:
    """
    Conectores que podem ter um totem configurado.

    O C5 fica de fora: é exclusivo de assinante, e um totem nele teria de
    recusar quem chega sem conta — o caminho que o totem existe para oferecer.
    """
    return [cid for cid in sorted(sm.list_chargers()) if not _eh_conector_vip(cid)]


def _conector_do_totem() -> str:
    """O conector que este totem controla."""
    cid = request.cookies.get(COOKIE_TOTEM, totem.CONECTOR_PADRAO)
    return cid if cid in _conectores_de_totem() else totem.CONECTOR_PADRAO


def _url_na_rede(endpoint: str, **valores) -> str:
    """
    URL absoluta com o IP da rede, e não `localhost`.

    É o endereço que vai dentro de um QR: quem o lê é o celular, e `localhost`
    no celular é o próprio celular.
    """
    porta = request.host.rsplit(":", 1)[1] if ":" in request.host else "80"
    return f"http://{_ip_local()}:{porta}{url_for(endpoint, **valores)}"


def _guarda_de_modo():
    """
    Mantém cada modo nas suas telas.

    Chamada no início da guarda de acesso, antes da checagem de login: no
    totem, o mapa não deve nem pedir login — deve voltar para o totem. Sem
    esta guarda, o totem mostraria o mapa de postos a quem digitasse o
    endereço, e o totem não é um navegador livre.
    """
    endpoint = request.endpoint
    if endpoint is None or endpoint in ROTAS_DOS_DOIS_MODOS:
        return None
    if _modo() == "totem":
        if endpoint in ROTAS_TOTEM or endpoint in ROTAS_TOTEM_EMPRESTADAS:
            return None
        return redirect(url_for("totem_home"))
    if endpoint in ROTAS_TOTEM:
        return redirect(url_for("login"))
    return None


@app.context_processor
def _injetar_modo():
    """`modo` e `conector_totem` disponíveis em qualquer template."""
    if request.endpoint is None:
        return {}
    return {
        "modo": _modo(),
        "conector_totem": _conector_do_totem(),
        "postos_nomes": {pid: p["nome"].replace("ChargeGrid ", "")
                         for pid, p in POSTOS.items()},
    }


@app.route("/modo/<modo>")
def trocar_modo(modo: str):
    """
    Alterna entre o modo app e o modo totem.

    Trocar de modo é trocar de aparelho: o totem não pode herdar o login de
    quem estava no app, nem o app o de quem usou o totem. Por isso a sessão
    de login é encerrada na troca.
    """
    if modo not in MODOS:
        return redirect(url_for("login"))
    user_session.clear()
    resposta = redirect(url_for("totem_home") if modo == "totem" else url_for("login"))
    resposta.set_cookie(COOKIE_MODO, modo, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resposta


# ── Início de recarga, compartilhado pelos dois caminhos do totem ──────────

def _iniciar_recarga(cid: str, placa: str, nome: str, tipo: UserType, dono: str):
    """
    Cria, aloca e inicia uma recarga no conector.

    A mesma sequência de `processar`: sessão, alocação de potência, tarifa
    fixada na conexão e os quadros Modbus. Honra a reserva de quem está
    iniciando e recusa a de outra pessoa.

    Raises:
        ValueError : conector ocupado ou reservado, carro já carregando em
                     outro lugar, ou alocação recusada pelo limite físico
    """
    posto_id = cid.split("-")[0]
    with _state_lock:
        reserva = reservations.ativa_do_conector(cid)
        if reserva and reserva.usuario != dono:
            raise ValueError("Este conector está reservado por outro motorista.")

        sessao = sm.create_session(
            charger_id=cid, vehicle_id=placa, user_name=nome,
            user_type=tipo, requested_power_kw=11.0, owner=dono,
        )
        resultado = _get_pm(posto_id).allocate(sessao)
        if resultado.rejected:
            sm.finish_session(sessao.session_id, status=SessionStatus.FAULTED)
            raise ValueError(resultado.message)

        tarifa = pe.calculate(
            tipo, occupancy_override=_posto_sms[posto_id].occupancy_ratio())
        sm.start_charging(sessao.session_id, resultado.granted_kw, tarifa.tariff_kwh)
        if resultado.redistributed and resultado.granted_kw < 11.0:
            sm.throttle_session(sessao.session_id, resultado.granted_kw)
        mb.on_session_start(sessao)
        if resultado.redistributed and resultado.throttle_events:
            mb.on_throttle(sessao, resultado)

    if reserva:
        reservations.consumir(dono, cid)
    logger.info("Recarga iniciada pelo totem: %s | %s | %s",
                sessao.session_id, cid, placa)
    return sessao


def _dono_no_totem() -> str:
    """Quem está usando o totem agora: a conta logada ou o token da recarga avulsa."""
    return user_session.get("usuario") or user_session.get("totem_avulso", "")


def _sessao_do_totem():
    """
    A recarga deste totem que pertence a quem está nele, se houver.

    Inclui a recarga já encerrada e ainda não paga — é o estado entre apertar
    "Encerrar" e confirmar o pagamento.
    """
    dono = _dono_no_totem()
    if not dono:
        return None
    cid = _conector_do_totem()
    for sessao in reversed(sm.list_all()):
        if sessao.charger_id == cid and sessao.owner == dono \
                and not _sessao_arquivada(sessao.session_id):
            return sessao
    return None


def _entrar_como(chave: str, *, no_totem: bool = False) -> None:
    """Grava o login no cookie de sessão — o mesmo que a tela de login faz."""
    perfil = auth.conta(chave)
    user_session.clear()
    user_session["usuario"] = chave
    user_session["nome"]    = perfil["nome"]
    user_session["tipo"]    = perfil["tipo"].value
    user_session["staff"]   = perfil["staff"]
    if no_totem:
        user_session["totem"] = True
    wallet.garantir_conta(chave, perfil["saldo_inicial"])


# ── Telas do totem ─────────────────────────────────────────────────────────

@app.route("/totem")
def totem_home():
    """Início do totem: entrar com a conta ou usar sem conta."""
    if _sessao_do_totem() is not None:
        return redirect(url_for("totem_carregando"))

    cid = _conector_do_totem()
    ocupado = sm.list_chargers().get(cid) is not None
    reservado = reservations.ativa_do_conector(cid) is not None
    posto_id = cid.split("-")[0]
    tarifa = pe.calculate(UserType.STANDARD,
                          occupancy_override=_posto_sms[posto_id].occupancy_ratio())
    return render_template(
        "totem_home.html", cid=cid, posto=POSTOS[posto_id],
        ocupado=ocupado, reservado=reservado, tarifa=tarifa,
        caucao=avulso.CAUCAO_BRL,
    )


@app.route("/totem/configurar", methods=["GET", "POST"])
def totem_configurar():
    """
    Escolhe qual conector este totem controla.

    Num posto real é uma configuração de instalação, feita uma vez. Aqui fica
    a um toque, para a demonstração poder trocar de conector.
    """
    if request.method == "POST":
        cid = request.form.get("charger_id", "")
        resposta = redirect(url_for("totem_home"))
        if cid in _conectores_de_totem():
            user_session.clear()
            resposta.set_cookie(COOKIE_TOTEM, cid, max_age=60 * 60 * 24 * 365,
                                samesite="Lax")
        return resposta

    ocupados = {s.charger_id for s in sm.list_active()}
    return render_template(
        "totem_configurar.html",
        postos=POSTOS,
        conectores=_conectores_de_totem(),
        ocupados=ocupados,
    )


@app.route("/totem/entrar")
def totem_entrar():
    """
    Mostra o QR que o celular lê para entrar no totem com a conta.

    Ninguém digita senha num terminal público: a senha fica no celular, e o
    totem só recebe a confirmação de que a conta autorizou.
    """
    cid = _conector_do_totem()
    token = totem.criar_pareamento(cid)
    url = _url_na_rede("celular_parear", token=token)
    return render_template(
        "totem_entrar.html", token=token, url_celular=url,
        url_celular_local=url_for("celular_parear", token=token),
        qr=qr_svg(url, rotulo="QR Code para entrar com a conta pelo celular"),
        validade=totem.VALIDADE_PAREAMENTO_S,
    )


@app.route("/totem/entrar/<token>/estado")
def totem_entrar_estado(token: str):
    """O totem pergunta, a cada segundo e meio, se o celular já confirmou."""
    usuario = totem.consumir(token)
    if usuario:
        _entrar_como(usuario, no_totem=True)
        return jsonify({"pronto": True, "url": url_for("totem_veiculo")})
    if totem.pareamento(token) is None:
        return jsonify({"pronto": False, "expirado": True})
    return jsonify({"pronto": False})


def _sessao_conector_usuario(charger_id: str, usuario: Optional[str]):
    """Localiza a sessão ativa ou recém-finalizada no conector vinculada ao usuário."""
    if not charger_id:
        return None
    for sessao in reversed(sm.list_all()):
        if sessao.charger_id == charger_id and (not usuario or sessao.owner == usuario) \
                and not _sessao_arquivada(sessao.session_id):
            return sessao
    return None


@app.route("/celular/parear/<token>", methods=["GET", "POST"])
def celular_parear(token: str):
    """
    A tela que abre no celular ao ler o QR do totem.

    Na demonstração o celular está sempre logado como a conta
    `auth.CONTA_DO_CELULAR`. Num app real seria a conta do próprio celular.
    Após confirmar no celular, a tela acompanha a recarga em tempo real assim
    que ela for iniciada no totem.
    """
    chave = auth.CONTA_DO_CELULAR
    info = totem.info_pareamento(token)
    if info is None:
        return render_template("celular_parear.html", estado="expirado", token=token)

    cid = info["charger_id"]
    posto = POSTOS.get(cid.split("-")[0], {})

    if request.method == "POST":
        if not totem.confirmar(token, chave):
            return render_template("celular_parear.html", estado="expirado", token=token)
        return redirect(url_for("celular_parear", token=token))

    # Se for GET: se já confirmou antes, exibe pronto/acompanhamento; senão, confirmar
    estado = "pronto" if (info and info.get("usuario")) else "confirmar"

    sessao = None
    cobranca = None
    if estado == "pronto":
        usuario = (info.get("usuario") if info else None) or chave
        sessao = _sessao_conector_usuario(cid, usuario)
        if sessao and sessao.is_active:
            with _state_lock:
                sm.accrue_energy(sessao)
            cobranca = billing.calcular(sessao)

    return render_template(
        "celular_parear.html",
        estado=estado,
        token=token,
        conta=auth.conta(chave),
        charger_id=cid,
        posto=posto,
        sessao=sessao,
        cobranca=cobranca,
    )


@app.route("/celular/parear/<token>/status")
def celular_parear_status(token: str):
    """Retorna o status em tempo real da recarga vinculada a este token para o celular."""
    info = totem.info_pareamento(token)
    if info is None:
        return jsonify({"status": "expirado"})

    cid = info["charger_id"]
    posto = POSTOS.get(cid.split("-")[0], {})
    usuario = info.get("usuario") or auth.CONTA_DO_CELULAR

    sessao = _sessao_conector_usuario(cid, usuario)
    if not sessao:
        return jsonify({
            "status": "aguardando",
            "charger_id": cid,
            "posto_nome": posto.get("nome", "Posto Nexus"),
            "usuario": usuario,
        })

    if not sessao.is_active:
        return jsonify({
            "status": "concluido",
            "charger_id": cid,
            "posto_nome": posto.get("nome", "Posto Nexus"),
            "veiculo": sessao.vehicle_id,
        })

    with _state_lock:
        sm.accrue_energy(sessao)
    cobranca = billing.calcular(sessao)

    return jsonify({
        "status": "carregando",
        "charger_id": cid,
        "posto_nome": posto.get("nome", "Posto Nexus"),
        "veiculo": sessao.vehicle_id,
        "potencia_kw": round(sessao.allocated_power_kw, 1),
        "energia_kwh": round(sessao.energy_kwh, 2),
        "duracao_min": round(cobranca.duracao_min),
        "subtotal_brl": f"{cobranca.subtotal_brl:.2f}".replace(".", ","),
        "tarifa_kwh": f"{cobranca.tarifa_kwh:.4f}".replace(".", ","),
        "em_throttle": sessao.status.value == "THROTTLED",
        "status_texto": "Potência ajustada pela rede" if sessao.status.value == "THROTTLED" else "Recarregando",
    })


@app.route("/celular/parear/<token>/encerrar", methods=["POST"])
def celular_parear_encerrar(token: str):
    """Encerra a recarga pelo celular e redireciona para a tela de pagamento do app."""
    info = totem.info_pareamento(token)
    if info is None:
        flash("Pareamento expirado ou não encontrado.", "error")
        return redirect(url_for("mapa"))

    cid = info["charger_id"]
    usuario = info.get("usuario") or auth.CONTA_DO_CELULAR
    sessao = _sessao_conector_usuario(cid, usuario)

    if not sessao or not sessao.is_active:
        flash("Nenhuma recarga ativa encontrada para este conector.", "warning")
        return redirect(url_for("celular_parear", token=token))

    with _state_lock:
        sm.finish_session(sessao.session_id, liberar=False)
        mb.on_session_end(sessao)

    _entrar_como(usuario)
    flash("Recarga finalizada! Escolha a forma de pagamento para liberar o conector.", "info")
    return redirect(url_for("pagamento", session_id=sessao.session_id))



@app.route("/totem/veiculo", methods=["GET", "POST"])
def totem_veiculo():
    """Com a conta no totem: escolhe um carro salvo ou informa outro."""
    usuario = user_session.get("usuario")
    if not usuario or not user_session.get("totem"):
        return redirect(url_for("totem_home"))
    if _sessao_do_totem() is not None:
        return redirect(url_for("totem_carregando"))

    cid = _conector_do_totem()
    if request.method == "POST":
        try:
            placa, salvar = _veiculo_do_formulario(usuario)
            perfil = auth.conta(usuario)
            _iniciar_recarga(cid, placa, perfil["nome"], perfil["tipo"], usuario)
            if salvar:
                veiculos.salvar(usuario, placa, request.form.get("modelo", ""))
            return redirect(url_for("totem_carregando"))
        except ValueError as erro:
            flash(str(erro), "error")
            return redirect(url_for("totem_veiculo"))

    return render_template(
        "totem_veiculo.html", cid=cid, carros=_carros_com_estado(usuario),
        conta=auth.conta(usuario),
    )


@app.route("/totem/sem-conta", methods=["GET", "POST"])
def totem_sem_conta():
    """
    Sem conta: informa a placa e vê o aviso da caução antes de pagar.

    A caução é o que substitui o cadastro. A garantia do pagamento é o valor
    pré-autorizado, não a identidade de quem carrega — por isso não há senha,
    CPF nem liberação por alguém do posto.
    """
    if _sessao_do_totem() is not None:
        return redirect(url_for("totem_carregando"))
    cid = _conector_do_totem()

    if request.method == "POST":
        try:
            placa = _validar_placa(request.form.get("placa", ""))
            em_uso = sm.sessao_ativa_do_veiculo(placa)
            if em_uso is not None:
                raise ValueError(f"O veículo {placa} já está carregando em "
                                 f"{em_uso.charger_id}.")
            if sm.list_chargers().get(cid) is not None:
                raise ValueError("Este conector acabou de ser ocupado.")
        except ValueError as erro:
            flash(str(erro), "error")
            return redirect(url_for("totem_sem_conta"))
        user_session.clear()
        user_session["totem_pendente"] = {
            "placa": placa, "modelo": request.form.get("modelo", "").strip()[:40]}
        return redirect(url_for("totem_sinal"))

    posto_id = cid.split("-")[0]
    tarifa = pe.calculate(UserType.STANDARD,
                          occupancy_override=_posto_sms[posto_id].occupancy_ratio())
    return render_template("totem_sem_conta.html", cid=cid, tarifa=tarifa,
                           caucao=avulso.CAUCAO_BRL)


@app.route("/totem/sem-conta/pagar", methods=["GET", "POST"])
def totem_sinal():
    """Pagamento da caução, por cartão (aproximação) ou Pix, e início da recarga."""
    pendente = user_session.get("totem_pendente")
    if not pendente:
        return redirect(url_for("totem_sem_conta"))
    cid = _conector_do_totem()

    if request.method == "POST":
        metodo = billing.normalizar_metodo(request.form.get("metodo", ""))
        if metodo == billing.METODO_NEXUSCOIN:
            flash("NexusCoin exige conta. Use cartão ou Pix.", "error")
            return redirect(url_for("totem_sinal"))
        dono = avulso.novo_dono()
        try:
            _iniciar_recarga(cid, pendente["placa"], "Sem cadastro",
                             UserType.STANDARD, dono)
        except ValueError as erro:
            # A caução é autorizada e só capturada se a recarga começar: se o
            # conector não liberou, não há o que estornar.
            flash(f"{erro} Nenhum valor foi cobrado.", "error")
            user_session.pop("totem_pendente", None)
            return redirect(url_for("totem_home"))
        user_session.pop("totem_pendente", None)
        user_session["totem_avulso"] = dono
        user_session["avulso_metodo"] = metodo
        return redirect(url_for("totem_carregando"))

    return render_template(
        "totem_sinal.html", cid=cid, placa=pendente["placa"],
        caucao=avulso.CAUCAO_BRL,
        qr_pix=qr_svg(f"CGI|CAUCAO|{cid}|{avulso.CAUCAO_BRL:.2f}",
                      rotulo="QR Code do Pix da caução"),
    )


@app.route("/totem/carregando")
def totem_carregando():
    """A recarga em andamento neste totem, com o botão de encerrar."""
    sessao = _sessao_do_totem()
    if sessao is None:
        return redirect(url_for("totem_home"))
    if not sessao.is_active:
        # Encerrada e não paga: só existe no fluxo com conta.
        return redirect(url_for("pagamento", session_id=sessao.session_id))

    with _state_lock:
        sm.accrue_energy(sessao)

    eh_avulso = avulso.eh_avulso(sessao.owner)
    cobranca = billing.calcular(sessao, avulso.CAUCAO_BRL if eh_avulso else 0.0)
    qr_celular = None
    if eh_avulso:
        url = _url_na_rede("avulso_sessao", token=sessao.owner.split(":", 1)[1])
        qr_celular = qr_svg(url, rotulo="QR Code para acompanhar a recarga pelo celular")
    return render_template(
        "totem_carregando.html", s=sessao, cobranca=cobranca,
        eh_avulso=eh_avulso, caucao=avulso.CAUCAO_BRL, qr_celular=qr_celular,
        conta=auth.conta(sessao.owner) if not eh_avulso else None,
    )


@app.route("/totem/carregando/status")
def totem_carregando_status():
    """Retorna dados de telemetria da sessão atual do totem em JSON sem recarregar a tela."""
    sessao = _sessao_do_totem()
    if sessao is None:
        return jsonify({"ativo": False, "redirect": url_for("totem_home")})
    if not sessao.is_active:
        return jsonify({
            "ativo": False,
            "redirect": url_for("pagamento", session_id=sessao.session_id)
        })

    with _state_lock:
        sm.accrue_energy(sessao)
    eh_avulso = avulso.eh_avulso(sessao.owner)
    cobranca = billing.calcular(sessao, avulso.CAUCAO_BRL if eh_avulso else 0.0)

    return jsonify({
        "ativo": True,
        "energia": f"{sessao.energy_kwh:.2f}".replace(".", ","),
        "potencia": f"{sessao.allocated_power_kw:.1f}".replace(".", ","),
        "tempo": f"{sessao.duration_minutes:.0f}",
        "subtotal": f"{cobranca.subtotal_brl:.2f}".replace(".", ","),
        "em_throttle": sessao.status.value == "THROTTLED",
        "status_texto": "Potência ajustada" if sessao.status.value == "THROTTLED" else "Em andamento",
    })


@app.route("/totem/encerrar", methods=["POST"])
def totem_encerrar():
    """
    Encerra a recarga deste totem.

    Com conta, segue para a tela de pagamento — a mesma regra do app, em que
    o conector só é liberado quando o pagamento é confirmado. Sem conta, a
    caução já está retida: encerrar e acertar são o mesmo passo.
    """
    sessao = _sessao_do_totem()
    if sessao is None or not sessao.is_active:
        return redirect(url_for("totem_home"))
    if avulso.eh_avulso(sessao.owner):
        _acertar_avulso(sessao, user_session.get("avulso_metodo", billing.METODO_PIX))
        return redirect(url_for("totem_recibo", session_id=sessao.session_id))
    return encerrar_recarga(sessao.session_id)


@app.route("/totem/recibo/<session_id>")
def totem_recibo(session_id: str):
    """Recibo no totem. Some sozinho: o próximo motorista não deve vê-lo."""
    linha = _sessao_arquivada(session_id)
    dono = _dono_no_totem()
    if linha is None or not dono or linha["usuario"] not in (dono, _usuario_do_arquivo(dono)):
        return redirect(url_for("totem_home"))
    eh_avulso = avulso.eh_avulso(dono)
    qr_celular = None
    if eh_avulso:
        url = _url_na_rede("avulso_sessao", token=dono.split(":", 1)[1])
        qr_celular = qr_svg(url, rotulo="QR Code do comprovante no celular")
    return render_template(
        "totem_recibo.html", r=dict(linha), eh_avulso=eh_avulso,
        caucao=avulso.CAUCAO_BRL, estorno=avulso.estorno(linha["sinal_abatido"]),
        metodo_label=billing.rotulo(linha["metodo_pagto"]), qr_celular=qr_celular,
        saldo=wallet.saldo(dono) if not eh_avulso else None,
    )


@app.route("/totem/sair", methods=["POST"])
def totem_sair():
    """Encerra o uso do totem: apaga o login e volta ao início."""
    user_session.clear()
    return redirect(url_for("totem_home"))


# ── Recarga sem conta: o bilhete no celular e o acerto da caução ───────────

def _sessao_avulsa(token: str):
    """
    Localiza a sessão avulsa de um token, ativa ou já encerrada.

    Procura em `list_all` e não em `list_active` porque o comprovante continua
    acessível depois do encerramento, pelo mesmo link.
    """
    dono = avulso.dono_do_token(token)
    return next((s for s in sm.list_all() if s.owner == dono), None)


def _usuario_do_arquivo(dono: str) -> str:
    """Como o dono aparece na tabela `sessoes`: conta, ou `avulso:<placa>`."""
    if not avulso.eh_avulso(dono):
        return dono
    sessao = next((s for s in sm.list_all() if s.owner == dono), None)
    return f"avulso:{sessao.vehicle_id}" if sessao else ""


def _acertar_avulso(sessao, metodo: str) -> None:
    """
    Encerra a recarga avulsa e acerta a caução na mesma operação.

    Não existe tela de pagamento separada: a caução já foi pré-autorizada,
    então encerrar e acertar são o mesmo passo — e o conector volta para a
    fila na hora, sem o risco de alguém encerrar e sumir sem pagar.
    """
    with _state_lock:
        sm.finish_session(sessao.session_id, liberar=False)
        mb.on_session_end(sessao)

    cobranca = billing.calcular(sessao, avulso.CAUCAO_BRL)
    _arquivar_sessao(sessao, f"avulso:{sessao.vehicle_id}", metodo,
                     cobranca.sinal_brl, 0.0)

    with _state_lock:
        sm.release_charger(sessao.session_id)
        rb = _get_pm(sessao.station_id).rebalance()
        if rb:
            mb.on_rebalance(rb)

    logger.info("Recarga avulsa encerrada: %s | consumo R$ %.2f | estorno R$ %.2f "
                "| a pagar R$ %.2f", sessao.session_id, cobranca.subtotal_brl,
                avulso.estorno(cobranca.sinal_brl), cobranca.total_brl)


@app.route("/avulso/<token>")
def avulso_sessao(token: str):
    """
    O bilhete da recarga sem conta, aberto no celular pelo QR do totem.

    Mostra a recarga em andamento e, depois de encerrada, o comprovante com
    o acerto da caução. Sem conta, é este link que identifica a recarga.
    """
    sessao = _sessao_avulsa(token)
    if sessao is None:
        return render_template("avulso.html", s=None), 404

    if sessao.is_active:
        with _state_lock:
            sm.accrue_energy(sessao)

    cobranca = billing.calcular(sessao, avulso.CAUCAO_BRL)
    linha = _sessao_arquivada(sessao.session_id)
    metodo = linha["metodo_pagto"] if linha else billing.METODO_PIX
    qr_pix_excedente = None
    if cobranca.total_brl > 0 and not linha:
        qr_pix_excedente = qr_svg(
            f"CGI|AVULSO|{sessao.charger_id}|{cobranca.total_brl:.2f}",
            rotulo=f"QR Code Pix para pagar o excedente de R$ {cobranca.total_brl:.2f}",
        )
    return render_template(
        "avulso.html", s=sessao, token=token, cobranca=cobranca,
        caucao=avulso.CAUCAO_BRL, estorno=avulso.estorno(cobranca.sinal_brl),
        posto=POSTOS.get(sessao.station_id, {}),
        metodo_label=billing.rotulo(metodo),
        qr_pix_excedente=qr_pix_excedente,
        sessao_arquivada=bool(linha),
    )


@app.route("/avulso/<token>/status")
def avulso_status(token: str):
    """Retorna os dados de telemetria em tempo real para a recarga sem conta no celular."""
    sessao = _sessao_avulsa(token)
    if sessao is None:
        return jsonify({"status": "nao_encontrado"})
    if sessao.is_active:
        with _state_lock:
            sm.accrue_energy(sessao)
    cobranca = billing.calcular(sessao, avulso.CAUCAO_BRL)
    linha = _sessao_arquivada(sessao.session_id)
    return jsonify({
        "ativo": sessao.is_active,
        "concluido": not sessao.is_active,
        "energia_kwh": f"{cobranca.energia_kwh:.2f}".replace(".", ","),
        "potencia_kw": f"{sessao.allocated_power_kw:.1f}".replace(".", ","),
        "duracao_min": f"{cobranca.duracao_min:.0f}",
        "subtotal_brl": f"{cobranca.subtotal_brl:.2f}".replace(".", ","),
        "tarifa_kwh": f"{cobranca.tarifa_kwh:.4f}".replace(".", ","),
        "total_brl": f"{cobranca.total_brl:.2f}".replace(".", ","),
        "estorno_brl": f"{avulso.estorno(cobranca.sinal_brl):.2f}".replace(".", ","),
        "arquivada": bool(linha),
    })


@app.route("/avulso/<token>/encerrar", methods=["POST"])
def avulso_encerrar(token: str):
    """
    Encerra a recarga avulsa pelo celular.

    Se o consumo for menor ou igual ao sinal de R$ 50,00:
        Deduz do sinal, agenda o estorno da diferença e libera o conector na hora.
    Se o consumo ultrapassar o sinal de R$ 50,00:
        Encerra a medição e exige o pagamento da diferença antes de liberar o conector.
    """
    sessao = _sessao_avulsa(token)
    if not sessao:
        flash("Recarga não encontrada.", "error")
        return redirect(url_for("avulso_sessao", token=token))

    if not sessao.is_active:
        return redirect(url_for("avulso_sessao", token=token))

    with _state_lock:
        sm.accrue_energy(sessao)

    cobranca = billing.calcular(sessao, avulso.CAUCAO_BRL)

    if cobranca.total_brl <= 0:
        metodo = user_session.get("avulso_metodo", billing.METODO_PIX)
        _acertar_avulso(sessao, metodo)
        flash("Recarga encerrada com sucesso! Conector liberado e sinal acertado.", "success")
        return redirect(url_for("avulso_sessao", token=token))
    else:
        with _state_lock:
            sm.finish_session(sessao.session_id, liberar=False)
            mb.on_session_end(sessao)
        flash("Recarga encerrada! Pague o excedente para liberar o conector.", "warning")
        return redirect(url_for("avulso_sessao", token=token))


@app.route("/avulso/<token>/pagar-excedente", methods=["POST"])
def avulso_pagar_excedente(token: str):
    """Recebe o pagamento do excedente (quando consumo > R$ 50) e libera o conector."""
    sessao = _sessao_avulsa(token)
    if not sessao:
        flash("Recarga não encontrada.", "error")
        return redirect(url_for("avulso_sessao", token=token))

    if _sessao_arquivada(sessao.session_id):
        return redirect(url_for("avulso_sessao", token=token))

    metodo = billing.normalizar_metodo(request.form.get("metodo", billing.METODO_PIX))
    _acertar_avulso(sessao, metodo)
    flash("Pagamento do excedente confirmado! O conector foi liberado.", "success")
    return redirect(url_for("avulso_sessao", token=token))



# ---------------------------------------------------------------------------
# ── SPRINT 3 · PAINEL DO OPERADOR ─────────────────────────────────────────
# ---------------------------------------------------------------------------

@app.route("/admin")
def admin_home():
    """Hub do painel administrativo (dono do posto)."""
    _atualizar_carregadores_livres()
    receita = db.query_one("SELECT COALESCE(SUM(custo_brl), 0) AS t FROM sessoes")
    total   = db.query_one("SELECT COUNT(*) AS n FROM sessoes")

    return render_template(
        "admin.html",
        postos=POSTOS,
        total_ativas=sm.active_count(),
        total_frames=mb.frame_count(),
        sessoes_historico=total["n"] if total else 0,
        receita_historico=round(receita["t"], 2) if receita else 0.0,
        receita_retida=reservations.receita_retida(),
        reservas_ativas=reservations.todas_ativas(),
        potencia_em_uso=round(sum(
            _posto_sms[p].total_allocated_power_kw() for p in ("P1", "P2", "P3")
        ), 2),
        potencia_limite=round(LIMITE_POR_POSTO_KW * 3, 2),
    )


@app.route("/admin/export.csv")
def export_csv():
    """
    Exporta o histórico de sessões em CSV.

    É a base das análises estatísticas da disciplina de Modelagem Linear e a
    entrada do sistema de gerenciamento em linha de comando.
    """
    linhas = db.query_all("SELECT * FROM sessoes ORDER BY fim")
    buffer = io.StringIO()

    if linhas:
        writer = csv.DictWriter(buffer, fieldnames=list(linhas[0].keys()))
        writer.writeheader()
        writer.writerows(dict(linha) for linha in linhas)
    else:
        buffer.write("session_id\n")

    # utf-8-sig: o Excel em português abre acentos corretamente com o BOM.
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=chargegrid_sessoes.csv"},
    )


@app.route("/admin/demo-reset", methods=["POST"])
def demo_reset():
    """
    Restaura o estado de demonstração: zera carteiras, reservas e histórico.

    Existe para salvar uma segunda rodada de apresentação sem reiniciar o
    processo. Só a equipe do posto tem acesso.
    """
    db.reset()
    for chave, perfil in auth.CONTAS.items():
        wallet.garantir_conta(chave, perfil["saldo_inicial"])
    veiculos.garantir_iniciais()
    flash("Estado de demonstração restaurado: saldos, reservas e histórico.",
          "success")
    return redirect(url_for("admin_home"))


# ---------------------------------------------------------------------------
# Seed de demonstração — popula postos com sessões já em andamento
# ---------------------------------------------------------------------------

def _seed_demo() -> None:
    """
    Pré-popula o estado com sessões de demonstração, para que os cenários de
    ocupação e throttling apareçam imediatamente no mapa e no dashboard, sem
    precisar criá-los manualmente.

    Cenários montados:
      • Berrini (P3): 5 conectores ocupados → posto LOTADO e em THROTTLE.
          C5 (VIP) = assinante (Yan); C3 = corporativo (Felipe); demais = padrão.
      • Paulista (P1): 4 conectores (C1–C4) carregando, C5 (VIP) livre.
          4×11 kW excede o limite de 33 kW → cenário de THROTTLE pré-montado.
          Composição: 2 padrão, 1 corporativo (Allan) e 1 assinante (Amanda).

    Cada sessão recebe um tempo de início recuado (alguns minutos atrás), de
    modo que já exibam minutos de recarga e energia acumulada. A função é
    idempotente: se já houver sessões ativas, não faz nada (evita duplicar
    em reloads do Flask no modo debug).
    """
    if sm.active_count() > 0:
        return

    import random

    def _placa_aleatoria() -> str:
        """Gera uma placa no padrão Mercosul (ABC1D23)."""
        letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return (
            "".join(random.choice(letras) for _ in range(3))
            + str(random.randint(0, 9))
            + random.choice(letras)
            + f"{random.randint(0, 99):02d}"
        )

    # (charger, nome, tipo, minutos já carregando, owner)
    # O campo `owner` amarra a sessão a uma conta de login: ao entrar como
    # Amanda, ela já encontra a própria recarga em andamento e pode encerrar
    # e pagar — o fluxo principal da demonstração não precisa de preparo.
    plano = [
        # Berrini — 5 conectores: lota e entra em throttle
        ("P3-C1", "Patrick",  UserType.STANDARD,   18, ""),
        ("P3-C2", "Carolina", UserType.STANDARD,   14, ""),
        ("P3-C3", "Felipe",   UserType.CORPORATE,  11, ""),
        ("P3-C4", "Henrique", UserType.STANDARD,    7, ""),
        ("P3-C5", "Yan",      UserType.SUBSCRIBER,  4, ""),   # VIP → assinante
        # Paulista — 4 conectores (C1–C4) carregando; C5 (VIP) fica LIVRE.
        # 4×11 kW projetado excede 33 kW → cenário de throttle pré-montado.
        ("P1-C1", "Damaceno",       UserType.STANDARD,   22, ""),
        ("P1-C2", "Caio",           UserType.STANDARD,   16, ""),
        ("P1-C3", "Allan Souza",    UserType.CORPORATE,   9, "allan"),
        ("P1-C4", "Amanda Ribeiro", UserType.SUBSCRIBER,  5, "amanda"),
    ]

    agora = datetime.datetime.now()

    for charger_id, nome, tipo, minutos, owner in plano:
        posto_id = charger_id.split("-")[0]
        pm_posto = _get_pm(posto_id)
        try:
            with _state_lock:
                # Sessões de conta usam o primeiro carro salvo da conta: é assim
                # que o carro da Amanda aparece como "carregando agora" na tela
                # de escolha do veículo, em vez de um carro que ela não tem.
                placa = veiculos.placa_inicial(owner) if owner else _placa_aleatoria()
                session = sm.create_session(
                    charger_id, placa, nome, tipo, 11.0, owner=owner
                )
                result = pm_posto.allocate(session)
                if result.rejected:
                    sm.finish_session(session.session_id,
                                      status=SessionStatus.FAULTED)
                    continue

                tariff = pe.calculate(
                    tipo,
                    occupancy_override=_posto_sms[posto_id].occupancy_ratio(),
                )
                sm.start_charging(session.session_id,
                                  result.granted_kw, tariff.tariff_kwh)
                if result.redistributed and result.granted_kw < 11.0:
                    sm.throttle_session(session.session_id, result.granted_kw)
                mb.on_session_start(session)
                if result.redistributed and result.throttle_events:
                    mb.on_throttle(session, result)

                # Recua o relógio da sessão para simular tempo já decorrido,
                # depois acumula a energia correspondente a esse intervalo.
                inicio = agora - datetime.timedelta(minutes=minutos)
                session.start_time         = inicio
                session.last_energy_update = inicio
                sm.accrue_energy(session.session_id)
        except ValueError as exc:
            logger.warning("Seed de demonstração ignorou %s: %s", charger_id, exc)

    _atualizar_carregadores_livres()
    logger.info("Seed de demonstração aplicado: %d sessões ativas.",
                sm.active_count())


# Aplica o seed ao importar o módulo (vale tanto para `python app.py`
# quanto para servidores WSGI que importam `app`). Não roda sob pytest,
# para não poluir o estado esperado pelos testes.
import sys as _sys
if "pytest" not in _sys.modules:
    _seed_demo()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ip_local = _ip_local()
    porta = 5001

    # O banner mostra as contas de demonstração: numa banca, procurar a senha
    # no README custa tempo que ninguém tem.
    largura = 60

    def _linha(texto: str = "") -> str:
        """Uma linha do quadro, com a borda direita alinhada.

        Emojis ocupam duas colunas no terminal mas contam como um caractere
        em `len()`, então o padding é corrigido por quantos deles a linha tem.
        """
        largos = sum(1 for c in texto if ord(c) > 0x2500)
        return "║ " + texto.ljust(largura - 3 - largos) + "║"

    print()
    print("╔" + "═" * (largura - 1) + "╗")
    print(_linha("⚡ ChargeGrid Intelligence — NexusCharge"))
    print(_linha("Sprint 3 · FIAP + GoodWe EV Challenge 2026"))
    print("╠" + "═" * (largura - 1) + "╣")
    print(_linha(f"Local  http://localhost:{porta}"))
    print(_linha(f"Rede   http://{ip_local}:{porta}"))
    print(_linha())
    print(_linha("Contas de demonstração — senha 1234 para todas:"))
    for chave, perfil in auth.CONTAS.items():
        papel = ("operador" if perfil["staff"]
                 else _TIPO_USUARIO_PT[perfil["tipo"].name].lower())
        saldo = _brl(perfil["saldo_inicial"])
        print(_linha(f"  {chave:<7} {papel:<12} {saldo:>10} NC"))
    print(_linha())
    print(_linha("Parar  Ctrl+C"))
    print("╚" + "═" * (largura - 1) + "╝")
    print()

    # O modo debug do Flask publica o console interativo do Werkzeug, que
    # executa Python arbitrário — com host 0.0.0.0 isso fica aberto para a
    # rede inteira. Fica desligado por padrão; quem quer o reloader durante o
    # desenvolvimento liga com CHARGEGRID_DEBUG=1.
    app.run(debug=os.environ.get("CHARGEGRID_DEBUG") == "1",
            host="0.0.0.0", port=porta)
