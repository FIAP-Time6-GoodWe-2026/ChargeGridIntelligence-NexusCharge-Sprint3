# =============================================================================
#  ChargeGrid Intelligence — Testes Automatizados
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Testes automatizados para os módulos de negócio do ChargeGrid.

Execução:
    pip install pytest
    pytest test_chargegrid.py -v

Cobertura:
    - PricingEngine : todos os eixos e combinações de tarifa
    - PowerManager  : alocação (4 casos), rebalanceamento, recusa física
    - SessionManager: criação, acúmulo de energia, idempotência do finish
    - Integração    : ciclo completo de sessão via app Flask
"""

import sys
import time
import types

import pytest

# ---------------------------------------------------------------------------
# Isolamento do banco (Sprint 3)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _db_temporario(tmp_path, monkeypatch):
    """
    Redireciona o SQLite para um arquivo temporário em cada teste.

    Sem isso, rodar a suíte mexeria no `chargegrid.db` usado na demonstração:
    saldos alterados, reservas criadas e sessões arquivadas no meio de uma
    apresentação. O `autouse` garante que nenhum teste escape por esquecimento.
    """
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "teste.db")
    db.init()
    yield


# ---------------------------------------------------------------------------
# Fixtures compartilhadas
# ---------------------------------------------------------------------------

@pytest.fixture
def sm():
    """SessionManager limpo para cada teste."""
    from session_manager import SessionManager
    return SessionManager()


@pytest.fixture
def pm(sm):
    """PowerManager com limite de 33 kW."""
    from power_manager import PowerManager
    return PowerManager(sm, limit_kw=33.0)


@pytest.fixture
def pe(sm):
    """PricingEngine ligado ao SessionManager."""
    from pricing_engine import PricingEngine
    return PricingEngine(sm)


@pytest.fixture
def full(sm, pm, pe):
    """Retorna a trinca (sm, pm, pe) para testes de integração leve."""
    return sm, pm, pe


@pytest.fixture
def chargers(sm):
    """Lista de IDs de carregadores disponíveis."""
    return list(sm.list_chargers().keys())


def _start(sm, pm, pe, charger_id, user_type, pot=11.0, hora=10):
    """Helper: cria + aloca + inicia sessão. Espelha o comportamento do app.py.

    Após start_charging, aplica throttle_session na nova sessão quando a
    potência concedida é menor que a solicitada (redistribuição Caso 3).
    Isso replica o passo que vive em app.py::dashboard_nova_sessao e é
    necessário para que os testes de regressão de status THROTTLED sejam válidos.
    """
    from models import SessionStatus
    s = sm.create_session(charger_id, "TST-0001", "Test User", user_type, pot)
    r = pm.allocate(s)
    if not r.rejected:
        t = pe.calculate(user_type, hora=hora)
        sm.start_charging(s.session_id, r.granted_kw, t.tariff_kwh)
        # Replica o passo de throttle da nova sessão (app.py linha ~544)
        if r.redistributed and r.granted_kw < pot:
            sm.throttle_session(s.session_id, r.granted_kw)
    return s, r


# ===========================================================================
# PricingEngine
# ===========================================================================

class TestPricingEngine:

    def test_tarifa_base_fora_pico(self, pe):
        from models import UserType
        from pricing_engine import TARIFA_BASE_KWH
        r = pe.calculate(UserType.STANDARD, hora=10)
        assert r.tariff_kwh == TARIFA_BASE_KWH
        assert not r.peak_applied
        assert not r.demand_applied

    def test_multiplicador_pico(self, pe):
        from models import UserType
        from pricing_engine import TARIFA_BASE_KWH, MULTIPLICADOR_PICO
        r = pe.calculate(UserType.STANDARD, hora=20)
        assert r.peak_applied
        assert abs(r.tariff_kwh - round(TARIFA_BASE_KWH * MULTIPLICADOR_PICO, 4)) < 0.0001

    def test_desconto_assinante(self, pe):
        from models import UserType
        from pricing_engine import TARIFA_BASE_KWH, DESCONTO_ASSINANTE
        r = pe.calculate(UserType.SUBSCRIBER, hora=10)
        esperado = round(TARIFA_BASE_KWH * (1 - DESCONTO_ASSINANTE), 4)
        assert abs(r.tariff_kwh - esperado) < 0.0001
        assert r.user_discount_pct == pytest.approx(DESCONTO_ASSINANTE * 100)

    def test_desconto_corporativo(self, pe):
        from models import UserType
        from pricing_engine import TARIFA_BASE_KWH, DESCONTO_CORPORATE
        r = pe.calculate(UserType.CORPORATE, hora=10)
        esperado = round(TARIFA_BASE_KWH * (1 - DESCONTO_CORPORATE), 4)
        assert abs(r.tariff_kwh - esperado) < 0.0001

    def test_eixo_demanda_ativado(self, sm, pm, pe, chargers):
        """Demanda ativa quando ocupação >= 70% (11/15 = 73.3%)."""
        from models import UserType
        from pricing_engine import LIMIAR_DEMANDA
        for i in range(11):   # 11/15 = 73.3% >= 70%
            s, r = _start(sm, pm, pe, chargers[i], UserType.STANDARD, hora=10)
        ocupacao = sm.occupancy_ratio()
        assert ocupacao >= LIMIAR_DEMANDA, f"ocupação {ocupacao:.1%} < {LIMIAR_DEMANDA:.0%}"
        r = pe.calculate(UserType.STANDARD, hora=10)
        assert r.demand_applied

    def test_eixo_demanda_inativo_baixa_ocupacao(self, pe):
        """Sem sessões: demanda não deve ser aplicada."""
        from models import UserType
        r = pe.calculate(UserType.STANDARD, hora=10)
        assert not r.demand_applied

    def test_tres_eixos_combinados(self, sm, pm, pe, chargers):
        """Pico + Alta demanda + Assinante devem combinar multiplicadores."""
        from models import UserType
        from pricing_engine import (TARIFA_BASE_KWH, MULTIPLICADOR_PICO,
                                     MULTIPLICADOR_DEMANDA, DESCONTO_ASSINANTE)
        for i in range(11):   # 11/15 = 73.3% >= 70%
            _start(sm, pm, pe, chargers[i], UserType.STANDARD, hora=10)
        r = pe.calculate(UserType.SUBSCRIBER, hora=20)
        esperado = round(
            TARIFA_BASE_KWH
            * MULTIPLICADOR_PICO
            * MULTIPLICADOR_DEMANDA
            * (1 - DESCONTO_ASSINANTE),
            4,
        )
        assert abs(r.tariff_kwh - esperado) < 0.001
        assert r.peak_applied and r.demand_applied

    def test_taxa_minima_estimativa(self, pe):
        from models import UserType
        from pricing_engine import TAXA_MINIMA_SESSAO
        custo = pe.estimate_cost(UserType.STANDARD, energy_kwh=0.01, hora=10)
        assert custo == TAXA_MINIMA_SESSAO

    @pytest.mark.parametrize("hora,esperado_pico", [
        (17, False), (18, True), (22, True), (23, False), (0, False),
    ])
    def test_fronteiras_horario_pico(self, pe, hora, esperado_pico):
        from models import UserType
        r = pe.calculate(UserType.STANDARD, hora=hora, minuto=0)
        assert r.peak_applied == esperado_pico


# ===========================================================================
# PowerManager — Alocação
# ===========================================================================

class TestPowerManagerAlocacao:

    def test_caso_1_potencia_integral(self, sm, pm, pe, chargers):
        """Carga ≤ 90% do limite → potência integral, severity=ok."""
        from models import UserType
        s, r = _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        assert r.granted_kw == 11.0
        assert not r.redistributed
        assert r.severity == "ok"
        assert not r.rejected

    def test_caso_2_redistribuicao_parcial(self, sm, pm, pe, chargers):
        """3×11=33kW cabe no limite; 4ª sessão (44kW projetado > 33kW) aciona redistribuição."""
        from models import UserType
        # 3 sessões a 11kW = 33kW (exatamente no limite)
        _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        _start(sm, pm, pe, chargers[1], UserType.STANDARD)
        _start(sm, pm, pe, chargers[2], UserType.STANDARD)
        # 4ª sessão: 33+11=44kW > 33kW → Caso 3 (redistribuição total)
        s4, r4 = _start(sm, pm, pe, chargers[3], UserType.STANDARD)
        assert r4.redistributed
        assert r4.severity in ("warning", "danger")
        assert sm.total_allocated_power_kw() <= pm.limit_kw

    def test_caso_3_estouro_redistribuicao_total(self, sm, pe, chargers):
        """Limite 22kW + 3 sessões → Caso 3, severity=danger."""
        from models import UserType
        from power_manager import PowerManager
        pm2 = PowerManager(sm, limit_kw=22.0)
        _start(sm, pm2, pe, chargers[0], UserType.STANDARD)
        _start(sm, pm2, pe, chargers[1], UserType.STANDARD)
        s3, r3 = _start(sm, pm2, pe, chargers[2], UserType.STANDARD)
        assert r3.redistributed
        assert r3.severity == "danger"
        assert sm.total_allocated_power_kw() <= 22.0

    def test_caso_0_recusa_fisica(self, sm, pe, chargers):
        """(n+1) × 4.2 > limite → sessão recusada, severity=danger."""
        from models import UserType, SessionStatus
        from power_manager import PowerManager
        pm_apertado = PowerManager(sm, limit_kw=22.0)
        recusadas = 0
        for i in range(8):
            s = sm.create_session(chargers[i], f"V{i}", f"U{i}", UserType.STANDARD, 11.0)
            r = pm_apertado.allocate(s)
            if r.rejected:
                sm.finish_session(s.session_id, SessionStatus.FAULTED)
                recusadas += 1
            else:
                t = pe.calculate(UserType.STANDARD, hora=10)
                sm.start_charging(s.session_id, r.granted_kw, t.tariff_kwh)
        assert recusadas > 0
        assert sm.total_allocated_power_kw() <= 22.0

    def test_load_after_consistente(self, sm, pm, pe, chargers):
        """load_after_kw deve bater com o estado real pós-throttle."""
        from models import UserType
        _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        _start(sm, pm, pe, chargers[1], UserType.STANDARD)
        s3, r3 = _start(sm, pm, pe, chargers[2], UserType.STANDARD, pot=8.0)
        divergencia = abs(r3.load_after_kw - sm.total_allocated_power_kw())
        assert divergencia < 0.5, f"Divergência de {divergencia:.2f} kW"

    def test_limite_nunca_ultrapassado_12_sessoes(self, sm, pm, pe, chargers):
        """12 tentativas simultâneas nunca devem estourar o limite."""
        from models import UserType, SessionStatus
        for i in range(12):
            s = sm.create_session(chargers[i], f"V{i}", f"U{i}", UserType.STANDARD, 11.0)
            r = pm.allocate(s)
            if r.rejected:
                sm.finish_session(s.session_id, SessionStatus.FAULTED)
            else:
                t = pe.calculate(UserType.STANDARD, hora=10)
                sm.start_charging(s.session_id, r.granted_kw, t.tariff_kwh)
        assert sm.total_allocated_power_kw() <= pm.limit_kw


# ===========================================================================
# PowerManager — Rebalanceamento
# ===========================================================================

class TestPowerManagerRebalance:

    def test_rebalance_restaura_throttled(self, sm, pe, chargers):
        """Após encerrar sessão, throttled devem recuperar potência."""
        from models import UserType, SessionStatus
        from power_manager import PowerManager
        pm2 = PowerManager(sm, limit_kw=22.0)
        sess = []
        for i in range(3):
            s, r = _start(sm, pm2, pe, chargers[i], UserType.STANDARD)
            if not r.rejected:
                sess.append(s)
        throttled_antes = [s for s in sm.list_active()
                           if s.status == SessionStatus.THROTTLED]
        assert len(throttled_antes) > 0

        sm.finish_session(sess[0].session_id)
        rb = pm2.rebalance()
        assert rb is not None
        assert sm.total_allocated_power_kw() <= 22.0

    def test_rebalance_nao_ultrapassa_limite(self, sm, pe, chargers):
        """Rebalanceamento nunca deve fazer a carga exceder o limite."""
        from models import UserType
        from power_manager import PowerManager
        pm2 = PowerManager(sm, limit_kw=22.0)
        sess = []
        for i in range(3):
            s, r = _start(sm, pm2, pe, chargers[i], UserType.STANDARD)
            if not r.rejected:
                sess.append(s)
        sm.finish_session(sess[0].session_id)
        pm2.rebalance()
        assert sm.total_allocated_power_kw() <= 22.0

    def test_rebalance_sem_sessoes_retorna_none(self, sm, pm):
        rb = pm.rebalance()
        assert rb is None

    def test_rebalance_severity_ok(self, sm, pe, chargers):
        """Severity do rebalanceamento deve ser 'ok'."""
        from models import UserType
        from power_manager import PowerManager
        pm2 = PowerManager(sm, limit_kw=22.0)
        sess = []
        for i in range(3):
            s, r = _start(sm, pm2, pe, chargers[i], UserType.STANDARD)
            if not r.rejected:
                sess.append(s)
        sm.finish_session(sess[0].session_id)
        rb = pm2.rebalance()
        if rb:
            assert rb.severity == "ok"


# ===========================================================================
# SessionManager
# ===========================================================================

class TestSessionManager:

    def test_create_session_valida(self, sm, chargers):
        from models import UserType, SessionStatus
        s = sm.create_session(chargers[0], "ABC-1234", "Ana", UserType.STANDARD, 11.0)
        assert s.session_id.startswith("CGI-")
        assert s.status == SessionStatus.PREPARING
        assert sm.get_session(s.session_id) is s

    def test_carregador_ocupado_raise(self, sm, pm, pe, chargers):
        from models import UserType
        _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        with pytest.raises(ValueError, match="ocupado"):
            sm.create_session(chargers[0], "DEF-5678", "B", UserType.STANDARD, 11.0)

    def test_potencia_invalida_raise(self, sm, chargers):
        from models import UserType
        with pytest.raises(ValueError):
            sm.create_session(chargers[0], "V1", "U", UserType.STANDARD, 0.5)

    def test_finish_idempotente(self, sm, pm, pe, chargers):
        """Chamar finish_session duas vezes não deve alterar o custo."""
        from models import UserType
        s, _ = _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        sm.update_energy(s.session_id, 2.0)
        sm.finish_session(s.session_id)
        custo1 = s.total_cost_brl
        sm.finish_session(s.session_id)
        assert s.total_cost_brl == custo1

    def test_taxa_minima_aplicada(self, sm, pm, pe, chargers):
        from models import UserType
        from pricing_engine import TAXA_MINIMA_SESSAO
        s, _ = _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        sm.update_energy(s.session_id, 0.01)   # custo irrisório
        sm.finish_session(s.session_id)
        assert s.total_cost_brl == TAXA_MINIMA_SESSAO

    def test_occupancy_ratio_deriva_de_chargers(self, sm):
        """occupancy_ratio deve usar len(_chargers) real, não valor hardcoded."""
        assert sm.occupancy_ratio() == 0.0
        total_real = len(sm._chargers)
        assert total_real == 15    # 3 postos × 5 carregadores

    def test_accrue_energy_idempotente(self, sm, pm, pe, chargers):
        """Várias chamadas rápidas a accrue_energy não devem inflar energia."""
        from models import UserType
        s, _ = _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        e0 = s.energy_kwh
        for _ in range(10):
            sm.accrue_energy(s.session_id)
        assert abs(s.energy_kwh - e0) < 0.005  # < 5Wh em chamadas instantâneas

    def test_accrue_energy_cresce_com_tempo(self, sm, pm, pe, chargers):
        """Energia deve crescer proporcionalmente ao tempo real."""
        from models import UserType
        s, _ = _start(sm, pm, pe, chargers[0], UserType.STANDARD)
        time.sleep(1.0)
        sm.accrue_energy(s.session_id)
        esperado = 11.0 * (1.0 / 3600.0)
        assert abs(s.energy_kwh - esperado) < 0.002


# ===========================================================================
# Integração Flask
# ===========================================================================

def _app_limpo(monkeypatch_db_path):
    """Recarrega o módulo `app` apontando o banco para o arquivo do teste."""
    import importlib

    import db
    import app as app_module

    importlib.reload(app_module)
    # O reload de app.py chama db.init(); reafirma o caminho temporário porque
    # o módulo db não é recarregado junto.
    app_module.db.DB_PATH = db.DB_PATH
    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture
def client(tmp_path):
    """
    Cliente de teste Flask autenticado como operador (staff).

    Sprint 3: todas as rotas passaram a exigir login, e as administrativas
    exigem perfil staff. A fixture entra como `mylon` para que os testes de
    rota herdados do Sprint 2 continuem exercitando o que exercitavam.
    """
    app_module = _app_limpo(tmp_path)
    with app_module.app.test_client() as c:
        c.post("/login", data={"usuario": "mylon", "senha": "1234"})
        yield c


@pytest.fixture
def client_usuario(tmp_path):
    """Cliente autenticado como usuária comum (Amanda, assinante, 100 NC)."""
    app_module = _app_limpo(tmp_path)
    with app_module.app.test_client() as c:
        c.post("/login", data={"usuario": "amanda", "senha": "1234"})
        yield c


@pytest.fixture
def client_anonimo(tmp_path):
    """Cliente sem autenticação, para verificar a guarda de acesso."""
    app_module = _app_limpo(tmp_path)
    with app_module.app.test_client() as c:
        yield c


class TestFlaskRoutes:

    def test_mapa_retorna_200(self, client):
        assert client.get("/").status_code == 200

    def test_posto_retorna_200(self, client):
        assert client.get("/posto/P1").status_code == 200

    def test_dashboard_retorna_200(self, client):
        assert client.get("/dashboard").status_code == 200

    def test_api_status_retorna_json(self, client):
        import json
        r = client.get("/api/status")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "sessoes_ativas" in data
        assert "potencia_em_uso" in data
        assert "ocupacao_pct" in data

    def test_nova_sessao_via_dashboard(self, client):
        r = client.post("/dashboard/nova-sessao", data={
            "charger_id": "P1-C1", "vehicle_id": "TST-001",
            "user_type": "A", "hora": "10", "potencia": "11.0",
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_posto_lotado_indisponivel(self, client):
        """Quando todos os 4 carregadores do posto P1 estão ocupados,
        o mapa deve exibir o posto como indisponível."""
        import json
        for n in range(1, 5):
            client.post("/dashboard/nova-sessao", data={
                "charger_id": f"P1-C{n}", "vehicle_id": f"TST-00{n}",
                "user_type": "P", "hora": "10", "potencia": "4.2",
            })
        r = client.get("/")
        html = r.data.decode()
        # P1 deve aparecer como indisponível
        assert "Lotado" in html or 'data-disponivel="false"' in html

    def test_modbus_log_retorna_200(self, client):
        assert client.get("/modbus-log").status_code == 200

    def test_relatorio_retorna_200(self, client):
        assert client.get("/relatorio").status_code == 200


# ===========================================================================
# Testes de Regressão — Bugs #B1, #B2, #B3
# ===========================================================================

class TestRegressaoBugs:
    """
    Testes de regressão para os três bugs corrigidos na sessão 2026-06-02:

        B1 — Carga máxima 31.7 kW em vez de 33.0 kW com 5 sessões
             Causa: MARGEM_REDISTRIBUICAO aplicada no Caso 3 (_redistribute_to),
             consumindo 5% da capacidade instalada de forma sistemática.

        B2 — Última sessão STANDARD recebe mais kW que as anteriores
             Causa: mesmo que B1 — existentes recebiam limit/n × 0.95 enquanto
             a nova recebia limit/n sem desconto.

        B3 — Sessões saem de THROTTLED após remoção mesmo ainda abaixo do solicitado
             Causa: restore_session() transitava para CHARGING incondicionalmente,
             sem verificar se a potência restaurada atingia a solicitada.
    """

    def _setup_posto_cheio(self, sm, pe, chargers):
        """Cria 5 sessões STANDARD num posto com limite 33 kW (retorna lista)."""
        from models import UserType
        from power_manager import PowerManager
        pm5 = PowerManager(sm, limit_kw=33.0)
        sessoes = []
        for i in range(5):
            s, r = _start(sm, pm5, pe, chargers[i], UserType.STANDARD)
            if not r.rejected:
                sessoes.append(s)
        return pm5, sessoes

    def test_b1_carga_total_atinge_limite_com_5_sessoes(self, sm, pe, chargers):
        """B1: com 5 sessões STANDARD e limite 33 kW, carga total deve ser 33 kW."""
        pm5, sessoes = self._setup_posto_cheio(sm, pe, chargers)
        assert len(sessoes) == 5, "Esperado 5 sessões aceitas (mínimo 4.2×5=21 ≤ 33)"
        carga = sm.total_allocated_power_kw()
        assert abs(carga - 33.0) < 0.5, (
            f"Carga esperada ≈ 33.0 kW, obtida {carga:.2f} kW "
            f"(regressão B1: MARGEM_REDISTRIBUICAO no Caso 3)"
        )

    def test_b2_nova_sessao_nao_recebe_mais_que_existentes_mesmo_tipo(
        self, sm, pe, chargers
    ):
        """B2: com 5 sessões STANDARD, todas devem ter potência ≈ igual (33/5 = 6.6 kW)."""
        from models import SessionStatus
        pm5, sessoes = self._setup_posto_cheio(sm, pe, chargers)

        ativas = sm.list_active()
        potencias = [s.allocated_power_kw for s in ativas]
        assert len(potencias) == 5

        # Todas devem ser iguais (mesma prioridade, mesma solicitação)
        max_kw = max(potencias)
        min_kw = min(potencias)
        assert max_kw - min_kw < 0.5, (
            f"Desbalanceamento: máx={max_kw:.2f} kW, mín={min_kw:.2f} kW "
            f"(regressão B2: nova sessão recebia mais que existentes)"
        )

    def test_b3_sessoes_permanecem_throttled_apos_remocao_parcial(
        self, sm, pe, chargers
    ):
        """B3: remover 1 sessão de 5 deve manter as 4 restantes em THROTTLED,
        pois 33/4 = 8.25 kW < 11 kW solicitado — ainda não é a potência cheia."""
        from models import UserType, SessionStatus
        from power_manager import PowerManager

        pm5, sessoes = self._setup_posto_cheio(sm, pe, chargers)
        assert len(sessoes) == 5

        # Encerra uma sessão e rebalanceia
        sm.finish_session(sessoes[0].session_id)
        pm5.rebalance()

        restantes = sm.list_active()
        assert len(restantes) == 4

        # Com 4 sessões e limite 33 kW → ideal = 8.25 kW < 11 kW → THROTTLED
        for s in restantes:
            assert s.status == SessionStatus.THROTTLED, (
                f"Sessão {s.session_id} deveria ser THROTTLED mas está {s.status.value} "
                f"({s.allocated_power_kw:.2f} kW alocado, {s.requested_power_kw:.1f} kW solicitado) "
                f"(regressão B3: restore_session transitava para CHARGING prematuramente)"
            )

    def test_b3_sessao_vai_para_charging_quando_restaurada_integralmente(
        self, sm, pe, chargers
    ):
        """B3 complementar: com 2 sessões e limite 33 kW, ao remover 1 a outra
        pode ir para 11 kW (potência cheia) → status deve ser CHARGING."""
        from models import UserType, SessionStatus
        from power_manager import PowerManager

        pm2 = PowerManager(sm, limit_kw=22.0)  # 22 kW → 2×11 kW exato
        s1, r1 = _start(sm, pm2, pe, chargers[0], UserType.STANDARD)
        s2, r2 = _start(sm, pm2, pe, chargers[1], UserType.STANDARD)

        # Com 22 kW e 2 sessões de 11 kW → sem throttle
        # Adiciona 3a sessão para forçar throttle: 3×11=33 > 22
        s3, r3 = _start(sm, pm2, pe, chargers[2], UserType.STANDARD)
        assert r3.redistributed, "3a sessão deveria causar redistribuição"

        # Encerra s3 — s1 e s2 devem voltar para 11 kW → CHARGING
        sm.finish_session(s3.session_id)
        pm2.rebalance()

        for s in [s1, s2]:
            sess = sm.get_session(s.session_id)
            assert sess.status == SessionStatus.CHARGING, (
                f"Sessão {sess.session_id} deveria estar CHARGING após restauração integral "
                f"(alocado={sess.allocated_power_kw:.1f}, solicitado={sess.requested_power_kw:.1f})"
            )


# ===========================================================================
# Testes de Regressão — Auditoria B24–B35 (sessão 2026-06-04)
# ===========================================================================

class TestAuditoriaB24aB35:
    """
    Regressão dos 12 bugs encontrados na auditoria completa do v3.
    Cada teste falha se o respectivo bug reaparecer.
    """

    # ---- B26: rebalance respeita prioridade por tipo de usuário ----------
    def test_b26_rebalance_respeita_prioridade(self, sm, pe, chargers):
        from models import UserType, SessionStatus
        from power_manager import PowerManager
        pm5 = PowerManager(sm, limit_kw=33.0)

        def start(cid, ut):
            s = sm.create_session(cid, "ABC1D23", "U", ut, 11.0)
            r = pm5.allocate(s)
            t = pe.calculate(ut, hora=10)
            sm.start_charging(s.session_id, r.granted_kw, t.tariff_kwh)
            if r.redistributed and r.granted_kw < 11.0:
                sm.throttle_session(s.session_id, r.granted_kw)
            return s

        start("P1-C1", UserType.SUBSCRIBER)
        start("P1-C2", UserType.STANDARD)
        start("P1-C3", UserType.STANDARD)
        start("P1-C4", UserType.CORPORATE)
        s5 = start("P1-C5", UserType.STANDARD)

        sm.finish_session(s5.session_id)
        pm5.rebalance()

        por_tipo = {s.charger_id: (s.user_type.name, s.allocated_power_kw)
                    for s in sm.list_active()}
        sub  = por_tipo["P1-C1"][1]
        corp = por_tipo["P1-C4"][1]
        std  = por_tipo["P1-C2"][1]
        # Assinante > Corporativo > Padrão após o rebalance
        assert sub > corp > std, (
            f"Prioridade não respeitada no rebalance: "
            f"SUB={sub} CORP={corp} STD={std} (regressão B26)"
        )
        assert sm.total_allocated_power_kw() <= 33.0 + 0.05

    # ---- B28: tarifa de demanda usa ocupação fornecida (do posto) --------
    def test_b28_demanda_usa_occupancy_override(self, sm, pe):
        from models import UserType
        # Rede global vazia → sem demanda
        t_global = pe.calculate(UserType.STANDARD, hora=10)
        assert not t_global.demand_applied
        # Override de 100% (posto cheio) → demanda ativa
        t_posto = pe.calculate(UserType.STANDARD, hora=10, occupancy_override=1.0)
        assert t_posto.demand_applied
        assert t_posto.tariff_kwh > t_global.tariff_kwh, (
            "occupancy_override não ativou a tarifa de demanda (regressão B28)"
        )

    # ---- B29: Caso 2 morto removido; _redistribute não existe mais -------
    def test_b29_redistribute_orfao_removido(self):
        from power_manager import PowerManager
        assert not hasattr(PowerManager, "_redistribute"), (
            "_redistribute deveria ter sido removido (regressão B29)"
        )
        assert hasattr(PowerManager, "_target_por_peso"), (
            "_target_por_peso deveria existir como helper unificado"
        )

    # ---- B30: validação de hora ------------------------------------------
    def test_b30_validar_hora(self):
        import app
        assert app._validar_hora("10") == 10
        assert app._validar_hora("23") == 23
        for invalida in ("24", "-1", "abc", "99"):
            with pytest.raises(ValueError):
                app._validar_hora(invalida)

    # ---- B31: validação de placa -----------------------------------------
    def test_b31_validar_placa(self):
        import app
        assert app._validar_placa("abc1d23") == "ABC1D23"   # Mercosul, normaliza
        assert app._validar_placa("ABC-1234") == "ABC1234"  # antigo com hífen
        for invalida in ("", "123", "ABCDEFG", "AB1234"):
            with pytest.raises(ValueError):
                app._validar_placa(invalida)

    # ---- B32: imports não usados removidos do modbus_simulator -----------
    def test_b32_imports_limpos(self):
        import modbus_simulator as mbsim
        src = open(mbsim.__file__).read()
        # 'time' não deve mais ser importado
        assert "import time" not in src, "import time deveria ter sido removido (B32)"


class TestAuditoriaModbusFlask:
    """B24/B25 via Flask test client — frames Modbus de throttle e meter read."""

    @pytest.fixture
    def client(self):
        import importlib
        import app as app_module
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            # Sprint 3 — as rotas do painel exigem sessão de operador.
            c.post("/login", data={"usuario": "mylon", "senha": "1234"})
            yield c, app_module

    # ---- B24: redistribuição gera frames Modbus --------------------------
    def test_b24_on_throttle_emite_frames(self, client):
        c, A = client
        for n in range(1, 5):  # 4ª sessão estoura o limite de P1
            c.post("/dashboard/nova-sessao", data={
                "charger_id": f"P1-C{n}", "vehicle_id": f"ABC{n}D34",
                "user_type": "P", "hora": "10", "potencia": "11.0",
            })
        throttle = [f for f in A.mb.get_log() if "Throttle" in f.description]
        assert len(throttle) > 0, "on_throttle não gerou frames Modbus (regressão B24)"

    # ---- B25: polling gera MeterRead -------------------------------------
    def test_b25_on_meter_read_no_polling(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P1-C1", "vehicle_id": "ABC1D34",
            "user_type": "P", "hora": "10", "potencia": "11.0",
        })
        c.get("/api/status")
        meter = [f for f in A.mb.get_log() if "MeterRead" in f.description]
        assert len(meter) > 0, "on_meter_read não foi chamado no polling (regressão B25)"

    # ---- B31 (rota): placa inválida não cria sessão ----------------------
    def test_b31_rota_rejeita_placa_invalida(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P3-C1", "vehicle_id": "XX",
            "user_type": "P", "hora": "10", "potencia": "11.0",
        }, follow_redirects=True)
        assert A.sm.list_chargers().get("P3-C1") is None, (
            "Placa inválida criou sessão (regressão B31)"
        )

    # ---- B35: relatório expõe receita realizada e projetada --------------
    def test_b35_receita_separada(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P2-C1", "vehicle_id": "AAA1B11",
            "user_type": "P", "hora": "10", "potencia": "11.0",
        })
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P2-C2", "vehicle_id": "BBB2C22",
            "user_type": "P", "hora": "10", "potencia": "11.0",
        })
        sid = [s.session_id for s in A.sm.list_active()
               if s.charger_id == "P2-C1"][0]
        c.post("/dashboard/encerrar", data={"session_id": sid})
        r = c.get("/relatorio")
        assert r.status_code == 200
        html = r.data.decode()
        assert "Realizada" in html and "Projetada" in html, (
            "Relatório não distingue receita realizada de projetada (regressão B35)"
        )


# ===========================================================================
# Testes de Regressão — Revisão R1–R5 (revisão completa do v4)
# ===========================================================================

class TestRevisaoR1aR5:
    """
    Regressão dos achados da revisão completa do v4:
        R1 — guard de 80% bloqueava restaurações legítimas (removido)
        R2 — log Modbus crescia ilimitado com on_meter_read (buffer circular)
        R5 — _simular_tick fora do lock na rota /posto (movido para sob lock)
    """

    # ---- R1: rebalance restaura com carga entre 80% e 100% ---------------
    def test_r1_rebalance_restaura_acima_de_80pct(self, sm):
        from power_manager import PowerManager
        from models import UserType, SessionStatus
        pm = PowerManager(sm, limit_kw=33.0)

        # 4 sessões throttled a 6.7 kW = 26.8 kW = 81% do limite
        for i in range(4):
            s = sm.create_session(f"P1-C{i+1}", "ABC1D23", "U",
                                  UserType.STANDARD, 11.0)
            sm.start_charging(s.session_id, 6.7, 1.20)
            s.status = SessionStatus.THROTTLED
            s.allocated_power_kw = 6.7

        carga_antes = sm.total_allocated_power_kw()
        assert carga_antes > 33.0 * 0.80, "pré-condição: carga deve estar > 80%"

        rb = pm.rebalance()
        carga_depois = sm.total_allocated_power_kw()

        assert rb is not None, (
            "rebalance deveria restaurar mesmo com carga > 80% (regressão R1)"
        )
        assert carga_depois > carga_antes, "carga deveria aumentar"
        assert carga_depois <= 33.05, "não pode estourar o limite"

    # ---- R2: log Modbus tem buffer circular ------------------------------
    def test_r2_log_modbus_tem_cap(self, sm):
        from modbus_simulator import ModbusSimulator, MAX_LOG_FRAMES
        from models import UserType

        mb = ModbusSimulator(verbose=False)
        sess = sm.create_session("P1-C1", "ABC1D23", "U",
                                 UserType.STANDARD, 11.0)
        sm.start_charging(sess.session_id, 11.0, 1.20)

        # Emite muito mais frames que o cap via meter reads repetidos
        for _ in range(MAX_LOG_FRAMES * 2):
            mb.on_meter_read(sess)

        assert len(mb.get_log()) <= MAX_LOG_FRAMES, (
            f"log em memória deveria ser capado em {MAX_LOG_FRAMES} (regressão R2)"
        )
        # O contador acumulado preserva o histórico total
        assert mb.frame_count() > MAX_LOG_FRAMES, (
            "frame_count deveria contar todos os frames já emitidos, não só o buffer"
        )

    # ---- R5: rota /posto não vaza _simular_tick --------------------------
    def test_r5_simular_tick_removido(self):
        import app
        assert not hasattr(app, "_simular_tick"), (
            "_simular_tick deveria ter sido removido (regressão R5)"
        )

    def test_r5_rota_posto_responde(self):
        import importlib
        import app as app_module
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            c.post("/login", data={"usuario": "mylon", "senha": "1234"})
            c.post("/dashboard/nova-sessao", data={
                "charger_id": "P1-C1", "vehicle_id": "ABC1D23",
                "user_type": "P", "hora": "10", "potencia": "11.0",
            })
            r = c.get("/posto/P1")
            assert r.status_code == 200, "rota /posto deveria responder 200 (R5)"


class TestConectorVIP:
    """Regra de negócio: o conector C5 é exclusivo para assinantes."""

    @pytest.fixture
    def client(self):
        import importlib
        import app as app_module
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            # Sprint 3 — as rotas do painel exigem sessão de operador.
            c.post("/login", data={"usuario": "mylon", "senha": "1234"})
            yield c, app_module

    def test_padrao_bloqueado_no_c5(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P1-C5", "vehicle_id": "ABC1D23",
            "user_type": "P", "hora": "10", "potencia": "11.0",
        })
        assert not [s for s in A.sm.list_active() if s.charger_id == "P1-C5"], \
            "Usuário Padrão não deveria poder usar o conector VIP C5"

    def test_corporativo_bloqueado_no_c5(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P1-C5", "vehicle_id": "DEF2G34",
            "user_type": "C", "hora": "10", "potencia": "11.0",
        })
        assert not [s for s in A.sm.list_active() if s.charger_id == "P1-C5"], \
            "Usuário Corporativo não deveria poder usar o conector VIP C5"

    def test_assinante_permitido_no_c5(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P1-C5", "vehicle_id": "GHI3J56",
            "user_type": "A", "hora": "10", "potencia": "11.0",
        })
        assert [s for s in A.sm.list_active() if s.charger_id == "P1-C5"], \
            "Assinante deveria poder usar o conector VIP C5"

    def test_padrao_permitido_em_conector_publico(self, client):
        c, A = client
        c.post("/dashboard/nova-sessao", data={
            "charger_id": "P1-C1", "vehicle_id": "JKL4M78",
            "user_type": "P", "hora": "10", "potencia": "11.0",
        })
        assert [s for s in A.sm.list_active() if s.charger_id == "P1-C1"], \
            "Usuário Padrão deveria poder usar conectores públicos (C1–C4)"


# ===========================================================================
# SPRINT 3 — Autenticação e autorização
# ===========================================================================

class TestAutenticacao:
    """Guarda global de acesso, login, logout e separação usuário/operador."""

    def test_rota_protegida_redireciona_sem_login(self, client_anonimo):
        r = client_anonimo.get("/")
        assert r.status_code == 302, "mapa deveria exigir autenticação"
        assert "/login" in r.headers["Location"]

    def test_login_publico_responde_200(self, client_anonimo):
        assert client_anonimo.get("/login").status_code == 200

    def test_login_valido_libera_o_mapa(self, client_anonimo):
        client_anonimo.post("/login", data={"usuario": "amanda", "senha": "1234"})
        assert client_anonimo.get("/").status_code == 200

    def test_login_ignora_caixa_do_usuario(self, client_anonimo):
        client_anonimo.post("/login", data={"usuario": "AMANDA", "senha": "1234"})
        assert client_anonimo.get("/").status_code == 200

    def test_senha_incorreta_nao_autentica(self, client_anonimo):
        client_anonimo.post("/login", data={"usuario": "amanda", "senha": "9999"})
        assert client_anonimo.get("/").status_code == 302

    def test_conta_inexistente_nao_autentica(self, client_anonimo):
        client_anonimo.post("/login", data={"usuario": "fulano", "senha": "1234"})
        assert client_anonimo.get("/").status_code == 302

    def test_usuario_comum_barrado_no_dashboard(self, client_usuario):
        r = client_usuario.get("/dashboard")
        assert r.status_code == 302, "usuário comum não pode ver o painel"

    def test_usuario_comum_barrado_no_relatorio(self, client_usuario):
        assert client_usuario.get("/relatorio").status_code == 302

    def test_staff_acessa_o_painel(self, client):
        assert client.get("/admin").status_code == 200
        assert client.get("/dashboard").status_code == 200

    def test_logout_encerra_a_sessao(self, client_usuario):
        client_usuario.get("/logout")
        assert client_usuario.get("/").status_code == 302

    def test_next_externo_e_recusado(self, client_anonimo):
        """O parâmetro `next` não pode virar um open redirect."""
        r = client_anonimo.post("/login", data={
            "usuario": "amanda", "senha": "1234", "next": "//exemplo-malicioso.com",
        })
        assert "exemplo-malicioso" not in r.headers.get("Location", "")

    def test_next_interno_e_respeitado(self, client_anonimo):
        r = client_anonimo.post("/login", data={
            "usuario": "amanda", "senha": "1234", "next": "/carteira",
        })
        assert r.headers["Location"].endswith("/carteira")


# ===========================================================================
# SPRINT 3 — Carteira NexusCoin
# ===========================================================================

class TestCarteira:
    """Saldo, crédito, débito, extrato e a fronteira do saldo insuficiente."""

    def test_saldos_iniciais_por_conta(self, client_anonimo):
        import auth
        import wallet
        for chave, perfil in auth.CONTAS.items():
            wallet.garantir_conta(chave, perfil["saldo_inicial"])
            assert wallet.saldo(chave) == perfil["saldo_inicial"]

    def test_garantir_conta_nao_recarrega(self):
        import wallet
        wallet.garantir_conta("t", 10.0)
        wallet.garantir_conta("t", 500.0)
        assert wallet.saldo("t") == 10.0

    def test_credito_e_debito(self):
        import wallet
        wallet.garantir_conta("t", 10.0)
        assert wallet.creditar("t", 5.0, "RECARGA") == 15.0
        assert wallet.debitar("t", 4.0, "PAGAMENTO") == 11.0

    def test_saldo_insuficiente_nao_altera_saldo(self):
        import wallet
        wallet.garantir_conta("t", 5.0)
        with pytest.raises(wallet.SaldoInsuficiente) as exc:
            wallet.debitar("t", 12.0, "PAGAMENTO")
        assert exc.value.falta == 7.0
        assert wallet.saldo("t") == 5.0, "débito recusado não pode mover o saldo"

    def test_extrato_registra_as_duas_pontas(self):
        import wallet
        wallet.garantir_conta("t", 10.0)
        wallet.creditar("t", 5.0, "RECARGA", "entrada")
        wallet.debitar("t", 2.0, "PAGAMENTO", "saída")
        ext = wallet.extrato("t")
        assert len(ext) == 2
        assert ext[0]["valor"] < 0 and ext[1]["valor"] > 0

    def test_valores_nao_positivos_sao_recusados(self):
        import wallet
        wallet.garantir_conta("t", 10.0)
        with pytest.raises(ValueError):
            wallet.creditar("t", 0, "RECARGA")
        with pytest.raises(ValueError):
            wallet.debitar("t", -3, "PAGAMENTO")

    def test_recarga_pela_rota_credita(self, client_usuario):
        import wallet
        antes = wallet.saldo("amanda")
        client_usuario.post("/carteira/recarregar",
                            data={"valor": "50,00", "metodo": "PIX"})
        assert wallet.saldo("amanda") == antes + 50.0

    def test_recarga_fora_da_faixa_e_recusada(self, client_usuario):
        import wallet
        antes = wallet.saldo("amanda")
        client_usuario.post("/carteira/recarregar",
                            data={"valor": "99999", "metodo": "PIX"})
        assert wallet.saldo("amanda") == antes

    def test_total_cashback(self):
        import wallet
        wallet.garantir_conta("t", 0.0)
        wallet.creditar("t", 1.5, "CASHBACK")
        wallet.creditar("t", 2.0, "CASHBACK")
        wallet.creditar("t", 10.0, "RECARGA")
        assert wallet.total_cashback("t") == 3.5


# ===========================================================================
# SPRINT 3 — Reserva de conector com sinal
# ===========================================================================

class TestReserva:
    """Ciclo de vida da reserva e o destino do sinal em cada desfecho."""

    def _conta(self, saldo=100.0, usuario="amanda"):
        import wallet
        wallet.garantir_conta(usuario, saldo)
        return usuario

    def test_criar_debita_o_sinal(self):
        import reservations
        import wallet
        u = self._conta()
        r = reservations.criar(u, "P2-C1")
        assert wallet.saldo(u) == 90.0
        assert r.segundos_restantes > 60 * 14

    def test_conector_reservado_nao_aceita_segunda_reserva(self):
        import reservations
        self._conta()
        self._conta(100.0, "outro")
        reservations.criar("amanda", "P2-C1")
        with pytest.raises(ValueError):
            reservations.criar("outro", "P2-C1")

    def test_usuario_so_tem_uma_reserva_ativa(self):
        import reservations
        self._conta()
        reservations.criar("amanda", "P2-C1")
        with pytest.raises(ValueError):
            reservations.criar("amanda", "P2-C2")

    def test_saldo_insuficiente_impede_a_reserva(self):
        import reservations
        import wallet
        u = self._conta(5.0, "allan")
        with pytest.raises(wallet.SaldoInsuficiente):
            reservations.criar(u, "P2-C3")
        assert reservations.ativa_do_conector("P2-C3") is None
        assert wallet.saldo(u) == 5.0

    def test_cancelar_estorna_integralmente(self):
        import reservations
        import wallet
        u = self._conta()
        reservations.criar(u, "P2-C1")
        assert reservations.cancelar(u, "P2-C1") == 10.0
        assert wallet.saldo(u) == 100.0
        assert reservations.ativa_do_conector("P2-C1") is None

    def test_cancelar_reserva_de_outro_e_recusado(self):
        import reservations
        self._conta()
        self._conta(100.0, "outro")
        reservations.criar("amanda", "P2-C1")
        with pytest.raises(ValueError):
            reservations.cancelar("outro", "P2-C1")

    def test_consumir_marca_usada_e_devolve_o_sinal(self):
        import reservations
        import wallet
        u = self._conta()
        reservations.criar(u, "P2-C1")
        assert reservations.consumir(u, "P2-C1") == 10.0
        assert reservations.consumir(u, "P2-C1") == 0.0, "não pode contar duas vezes"
        assert reservations.sinal_creditado(u, "P2-C1") == 10.0
        assert wallet.saldo(u) == 90.0, "reserva honrada não estorna"

    def test_expiracao_retem_o_sinal(self):
        import db
        import reservations
        import wallet
        u = self._conta()
        reservations.criar(u, "P2-C1")
        db.execute("UPDATE reservas SET expira_em = ? WHERE charger_id = ?",
                   ("2020-01-01 00:00:00", "P2-C1"))
        assert reservations.expirar_vencidas() == 1
        assert reservations.ativa_do_conector("P2-C1") is None
        assert wallet.saldo(u) == 90.0, "expiração não devolve o sinal"
        assert reservations.receita_retida() == 10.0

    def test_conector_reservado_sai_da_contagem_de_livres(self, client_usuario):
        import app as A
        import reservations
        livres_antes = A.POSTOS["P2"]["carregadores_livres"]
        reservations.criar("amanda", "P2-C1")
        A._atualizar_carregadores_livres()
        assert A.POSTOS["P2"]["carregadores_livres"] == livres_antes - 1

    def test_api_reservar_responde_402_sem_saldo(self, client_anonimo):
        client_anonimo.post("/login", data={"usuario": "allan", "senha": "1234"})
        r = client_anonimo.post("/api/reservar",
                                json={"posto_id": "P2", "carregador_id": "C1"})
        assert r.status_code == 402
        assert r.get_json()["acao"] == "recarregar"

    def test_api_reservar_cria_e_debita(self, client_usuario):
        import wallet
        r = client_usuario.post("/api/reservar",
                                json={"posto_id": "P2", "carregador_id": "C1"})
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert wallet.saldo("amanda") == 90.0

    def test_api_reservar_recusa_conector_ocupado(self, client_usuario):
        """Conector com sessão em andamento não pode ser reservado."""
        import app as A
        from models import UserType
        A.sm.create_session("P1-C1", "ABC1D23", "Outro", UserType.STANDARD, 11.0)
        r = client_usuario.post("/api/reservar",
                                json={"posto_id": "P1", "carregador_id": "C1"})
        assert r.status_code == 400


# ===========================================================================
# SPRINT 3 — Cobrança
# ===========================================================================

class TestBilling:
    """Composição do valor devido antes de escolher o meio de pagamento."""

    def _sessao(self, custo, energia=5.0, tarifa=1.2):
        import datetime
        from models import ChargingSession, SessionStatus, UserType
        s = ChargingSession(
            charger_id="P1-C1", station_id="P1", vehicle_id="ABC1D23",
            user_name="Teste", user_type=UserType.STANDARD, requested_power_kw=11.0,
        )
        s.total_cost_brl = custo
        s.energy_kwh = energia
        s.tariff_kwh = tarifa
        s.end_time = s.start_time + datetime.timedelta(minutes=30)
        s.status = SessionStatus.FINISHED
        return s

    def test_sinal_abate_o_subtotal(self):
        import billing
        c = billing.calcular(self._sessao(25.00), sinal_brl=10.00)
        assert c.total_brl == 15.00 and c.sinal_brl == 10.00

    def test_sinal_maior_que_o_consumo_zera_sem_credito(self):
        """Excedente do sinal fica com o posto: senão vira vetor de saque."""
        import billing
        c = billing.calcular(self._sessao(4.00), sinal_brl=10.00)
        assert c.total_brl == 0.0
        assert c.sinal_brl == 4.00, "abate no máximo o subtotal"
        assert c.gratuito and c.cashback_nc == 0.0

    def test_cashback_e_dez_por_cento_do_total(self):
        import billing
        import wallet
        c = billing.calcular(self._sessao(30.00))
        assert c.cashback_nc == round(30.00 * wallet.CASHBACK_NEXUSCOIN, 2)

    def test_sem_reserva_o_total_e_o_subtotal(self):
        import billing
        c = billing.calcular(self._sessao(7.30))
        assert (c.total_brl, c.sinal_brl) == (7.30, 0.0)

    def test_metodo_invalido_e_recusado(self):
        import billing
        assert billing.normalizar_metodo(" pix ") == "PIX"
        with pytest.raises(ValueError):
            billing.normalizar_metodo("boleto")


# ===========================================================================
# SPRINT 3 — Encerramento e pagamento pela interface
# ===========================================================================

class TestPagamento:
    """Fluxo completo: encerrar a própria recarga, pagar e emitir recibo."""

    def _sessao_de(self, app_module, owner="amanda", charger="P2-C1"):
        """Cria uma sessão pertencente ao usuário informado."""
        from models import UserType
        s = app_module.sm.create_session(
            charger, "ABC1D23", "Amanda Ribeiro", UserType.SUBSCRIBER,
            11.0, owner=owner,
        )
        r = app_module._get_pm(charger.split("-")[0]).allocate(s)
        app_module.sm.start_charging(s.session_id, r.granted_kw, 1.02)
        app_module.sm.update_energy(s.session_id, 10.0)   # 10 kWh → R$ 10,20
        return s

    def test_encerrar_leva_ao_pagamento(self, client_usuario):
        import app as A
        s = self._sessao_de(A)
        r = client_usuario.post(f"/sessao/{s.session_id}/encerrar")
        assert r.status_code == 302
        assert f"/pagamento/{s.session_id}" in r.headers["Location"]

    def test_sessao_de_outro_usuario_e_recusada(self, client_usuario):
        import app as A
        s = self._sessao_de(A, owner="allan")
        r = client_usuario.post(f"/sessao/{s.session_id}/encerrar",
                                follow_redirects=False)
        assert "/pagamento/" not in r.headers.get("Location", "")

    def test_pagamento_com_nexuscoin_debita_e_credita_cashback(self, client_usuario):
        import app as A
        import wallet
        s = self._sessao_de(A)
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")
        saldo_antes = wallet.saldo("amanda")

        client_usuario.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "NEXUSCOIN"})

        linha = A._sessao_arquivada(s.session_id)
        assert linha is not None, "sessão paga deve ser arquivada"
        total = round(linha["custo_brl"] - linha["sinal_abatido"], 2)
        esperado = round(saldo_antes - total + linha["cashback_nc"], 2)
        assert wallet.saldo("amanda") == esperado
        assert linha["cashback_nc"] == round(total * wallet.CASHBACK_NEXUSCOIN, 2)

    def test_pagamento_por_pix_nao_toca_a_carteira(self, client_usuario):
        import app as A
        import wallet
        s = self._sessao_de(A)
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")
        antes = wallet.saldo("amanda")

        client_usuario.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "PIX"})

        assert wallet.saldo("amanda") == antes
        assert A._sessao_arquivada(s.session_id)["cashback_nc"] == 0.0

    def test_confirmar_duas_vezes_cobra_uma(self, client_usuario):
        import app as A
        import wallet
        s = self._sessao_de(A)
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")

        client_usuario.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "NEXUSCOIN"})
        saldo_depois_do_primeiro = wallet.saldo("amanda")

        client_usuario.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "NEXUSCOIN"})
        assert wallet.saldo("amanda") == saldo_depois_do_primeiro, \
            "duplo clique não pode cobrar duas vezes"

    def test_saldo_insuficiente_nao_arquiva_a_sessao(self, client_anonimo):
        import app as A
        client_anonimo.post("/login", data={"usuario": "jose", "senha": "1234"})
        s = self._sessao_de(A, owner="jose")
        client_anonimo.post(f"/sessao/{s.session_id}/encerrar")

        client_anonimo.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "NEXUSCOIN"})
        assert A._sessao_arquivada(s.session_id) is None, \
            "sem saldo, a sessão não pode constar como paga"

    def test_recibo_indisponivel_antes_do_pagamento(self, client_usuario):
        import app as A
        s = self._sessao_de(A)
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")
        r = client_usuario.get(f"/recibo/{s.session_id}")
        assert r.status_code == 302

    def test_sinal_da_reserva_abate_no_pagamento(self, client_usuario):
        import app as A
        import reservations
        reservations.criar("amanda", "P2-C1")
        s = self._sessao_de(A, charger="P2-C1")
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")
        client_usuario.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "NEXUSCOIN"})
        linha = A._sessao_arquivada(s.session_id)
        assert linha["sinal_abatido"] == 10.0

    # ---- B41: encerrar sem pagar não devolve a vaga ----------------------
    def test_encerrar_sem_pagar_mantem_o_conector_ocupado(self, client_usuario):
        import app as A
        s = self._sessao_de(A, charger="P2-C1")
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")

        assert A.sm.list_chargers()["P2-C1"] == s.session_id, \
            "conector liberado sem pagamento (regressão B41)"
        assert not A.sm.is_charger_available("P2-C1")

    def test_pagamento_libera_o_conector(self, client_usuario):
        import app as A
        s = self._sessao_de(A, charger="P2-C1")
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")
        client_usuario.post(f"/pagamento/{s.session_id}/confirmar",
                            data={"metodo": "NEXUSCOIN"})

        assert A.sm.is_charger_available("P2-C1"), \
            "conector deveria voltar à fila depois do pagamento"

    def test_pendencia_aparece_para_o_dono_da_sessao(self, client_usuario):
        import app as A
        s = self._sessao_de(A, charger="P2-C1")
        client_usuario.post(f"/sessao/{s.session_id}/encerrar")

        r = client_usuario.get("/")
        assert b"Pagar agora" in r.data, \
            "sem faixa de pendência o débito fica sem caminho de volta"
        assert A._pendencia_do_usuario("amanda").session_id == s.session_id

    # ---- B42: operador libera pelo posto, sem passar pelo caixa ----------
    def test_staff_encerrando_sessao_alheia_libera_sem_pagamento(self, client):
        import app as A
        s = self._sessao_de(A, owner="amanda", charger="P2-C1")
        r = client.post(f"/sessao/{s.session_id}/encerrar")

        assert "/pagamento/" not in r.headers["Location"], \
            "dono do posto não pode ser mandado para o caixa (regressão B42)"
        assert f"/posto/{s.station_id}" in r.headers["Location"]
        assert A.sm.is_charger_available("P2-C1")

    def test_staff_libera_conector_retido(self, client):
        import app as A
        s = self._sessao_de(A, owner="amanda", charger="P2-C1")
        A.sm.finish_session(s.session_id, liberar=False)

        client.post(f"/sessao/{s.session_id}/liberar")
        assert A.sm.is_charger_available("P2-C1")

    def test_usuario_comum_nao_libera_conector(self, client_usuario):
        import app as A
        s = self._sessao_de(A, owner="allan", charger="P2-C1")
        A.sm.finish_session(s.session_id, liberar=False)

        client_usuario.post(f"/sessao/{s.session_id}/liberar")
        assert not A.sm.is_charger_available("P2-C1"), \
            "liberar conector é rota de operação, restrita ao staff"

    def test_export_csv_traz_a_sessao_paga(self, client):
        """O CSV é a base das análises estatísticas da Sprint 3."""
        import app as A
        s = self._sessao_de(A, owner="mylon")
        client.post(f"/sessao/{s.session_id}/encerrar")
        client.post(f"/pagamento/{s.session_id}/confirmar", data={"metodo": "PIX"})
        r = client.get("/admin/export.csv")
        assert r.status_code == 200
        assert s.session_id in r.data.decode("utf-8-sig")


# ===========================================================================
# SPRINT 3 — QR simulado
# ===========================================================================

class TestQRSimulado:

    def test_determinismo(self):
        from qr import qr_simulado
        assert qr_simulado("A|1|2") == qr_simulado("A|1|2")
        assert qr_simulado("A|1|2") != qr_simulado("B|1|2")

    def test_tem_rotulo_acessivel_e_densidade(self):
        from qr import qr_simulado
        svg = qr_simulado("CGI|TESTE|10.00")
        assert "aria-label" in svg
        assert svg.count("<rect") > 200
