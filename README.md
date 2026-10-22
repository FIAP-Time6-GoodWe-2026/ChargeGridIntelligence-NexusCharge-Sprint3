# ⚡ ChargeGrid Intelligence — NexusCharge

> Sistema inteligente de gerenciamento de recarga para eletropostos comerciais
> **EV Challenge 2026 — FIAP + GoodWe · Sprint 3**

📦 **Repositório:** https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3

ChargeGrid Intelligence resolve um problema concreto do segmento comercial e de
varejo de eletropostos: a ausência de mecanismos integrados para **orquestrar
potência elétrica**, **registrar ciclos de recarga**, **faturar sessões** e
**comunicar informações** ao usuário e à plataforma de gestão.

O hardware de referência é o carregador AC **GoodWe GW11K-HCA-20** (11 kW, linha
HCA G2), e a integração é simulada via protocolo industrial **Modbus TCP**.

---

## 🆕 O que o Sprint 3 acrescenta

O Sprint 2 entregou a orquestração de potência e a tarifação dinâmica. O
Sprint 3 fecha o ciclo comercial: **quem é o usuário, como ele reserva, e como
ele paga**.

| Novidade | O que é |
|---|---|
| **Autenticação e Perfis** | Cinco contas pré-cadastradas (incluindo Luiz Otávio com cartão salvo); ninguém chega ao mapa sem entrar no Modo App. Rotas administrativas restritas ao operador. |
| **Modo App / Modo Totem** | Alternância com um clique entre experiência mobile para o motorista e interface vertical para totens físicos de autoatendimento touchscreen. |
| **Gestão de Veículos** | Suporte a múltiplos veículos por conta, cadastro de veículos avulsos e bloqueio estrito contra recargas simultâneas para a mesma placa. |
| **Totem com Pareamento** | Login no totem via QR Code dinâmico (ISO/IEC 18004 na stdlib) lido pelo smartphone, liberando o conector sem digitação de senha pública. |
| **Recarga sem cadastro (Totem)** | Visitante sem conta informa só a placa e paga um sinal de R$ 50,00 (cartão por aproximação ou Pix). A recarga é **pré-paga**: termina sozinha ao atingir o valor pago. Pode ser encerrada antes no totem ou no celular (QR de acompanhamento, sem app): o consumo sai do sinal e o restante é devolvido. |
| **Acompanhamento Móvel Omnichannel** | Monitoramento da recarga em tempo real pelo smartphone via QR Code do totem tanto para contas cadastradas (`/celular/parear/<token>`) quanto para visitantes avulsos (`/avulso/<token>`), com telemetria viva, encerramento remoto e quitação que libera o conector na hora. |
| **Sincronização Totem ⇄ Celular** | O totem monitora ativamente pagamentos realizados pelo smartphone, transitando automaticamente da tela de cobrança para o comprovante final sem exigir interação física no display público. |
| **NexusCoin** | Moeda interna com paridade 1 NC = R$ 1,00, **10% de cashback** ao pagar a recarga com ela, extrato auditável e recarga por Pix ou cartão. |
| **Reserva com sinal** | Bloqueia um conector por 15 minutos cobrando R$ 10,00. Compareceu, o sinal vira crédito; não compareceu, vira taxa por bloqueio; cancelou no prazo, estorno integral. |
| **Encerrar e pagar** | Botão na tela do posto encerra a própria recarga e leva à tela de pagamento, com NexusCoin, Pix (QR simulado) e cartão salvo. |
| **Menu de perfil** | Avatar no cabeçalho com nome, saldo, atalho de recarga e — para o operador — acesso ao painel. |
| **Painel do operador** | Hub em `/admin` reunindo dashboard, relatório, log Modbus e testes, com indicadores ao vivo e exportação em CSV. |
| **Persistência** | SQLite (`sqlite3` da biblioteca padrão) guarda carteiras, extrato, reservas e histórico de sessões. |
| **Estruturas de Dados** | Busca e ordenação implementadas à mão em `algoritmos.py`, **rodando em produção** (`get_session` e `rebalance`), com um segundo ponto de entrada em `menu.py` — menu de terminal sobre a mesma coleção de sessões. |
| **Fundação de design** | Escala tipográfica, espaçamento, raios e movimento em tokens; contrastes corrigidos para WCAG AA nos dois temas; foco de teclado visível; `prefers-reduced-motion`. |
| **Hardening & Resiliência** | Cabeçalhos defensivos OWASP (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `X-XSS-Protection`), proteção anti-open-redirect, clamp contra clock skew em `duration_seconds` e páginas de erro 404/500 customizadas. |

---

## 🚀 Como executar

**Pré-requisito:** Python 3.11+. As duas bibliotecas (`flask` e `pytest`) são
instaladas automaticamente na primeira execução. O banco de dados usa o módulo
`sqlite3`, que já vem com o Python — **não há nada a instalar por causa dele**.

### Windows

Dois cliques em **`iniciar.bat`**. Ele confere o Python, instala o que faltar
e abre um menu:

```
 [1]  Aplicativo web        mapa, recarga, carteira e pagamento
 [2]  Gestao de sessoes     menu de terminal (Estruturas de Dados)
 [3]  Rodar os testes       suite completa no terminal
 [4]  Sair
```

A opção 1 sobe o servidor e abre o navegador sozinho.

### Qualquer sistema

```bash
pip install flask pytest

python app.py      # http://localhost:5001
python menu.py     # menu de terminal (Estruturas de Dados)
pytest -q          # 414 testes
```

Ao iniciar, o terminal imprime o endereço e as contas de demonstração com os
saldos, para não ser preciso procurar a senha no meio de uma apresentação:

```
╔═══════════════════════════════════════════════════════════╗
║ ⚡ ChargeGrid Intelligence — NexusCharge                 ║
║ Sprint 3 · FIAP + GoodWe EV Challenge 2026               ║
╠═══════════════════════════════════════════════════════════╣
║ Local  http://localhost:5001                             ║
║                                                          ║
║ Contas de demonstração — senha 1234 para todas:          ║
║   amanda  assinante        100,00 NC                     ║
║   allan   corporativo        5,00 NC                     ║
║   jose    padrão             0,00 NC                     ║
║   luiz    assinante        150,00 NC                     ║
║   mylon   operador      10.000,00 NC                     ║
╚═══════════════════════════════════════════════════════════╝
```

O arquivo `chargegrid.db` é criado sozinho na primeira execução. Para zerar
tudo, basta apagá-lo — ou usar **Restaurar estado de demonstração** no painel
do operador.

> **Nota:** o mapa interativo usa tiles do OpenStreetMap e precisa de conexão
> com a internet. Sem conexão, um aviso é exibido e a navegação pela lista de
> postos continua funcionando.

---

## 👤 Contas de demonstração

Senha de todas: **`1234`**. Cada conta demonstra um caminho diferente do produto.

| Usuário | Nome | Categoria | Saldo inicial | Veículos | Para que serve na demonstração |
|---|---|---|---:|---|---|
| `amanda` | Amanda Ribeiro | Assinante (−15%) | 100,00 NC | `BRA2E19`, `RIO4F22` | Caminho feliz no Modo App: inicia com recarga em andamento no conector C4 da Faria Lima (`BRA2E19`), encerra, paga com NexusCoin, recebe 10% de cashback e inicia nova recarga com seu segundo carro (`RIO4F22`) |
| `allan` | Allan Souza | Corporativo (−10%) | 5,00 NC | `SPA7C31` | Saldo insuficiente: bloqueio da reserva, recarga da carteira e retomada do pagamento |
| `jose` | José Fino | Padrão | 0,00 NC | `JSF1A23` | Carteira zerada: estado vazio do extrato, tarifa cheia e pagamento por Pix ou cartão |
| `luiz` | Luiz Otávio | Assinante (−15%) | 150,00 NC | `LUZ9B87` | Cartão salvo (Visa final 4821); demonstração do pareamento celular-totem via QR Code e recarga no totem físico |
| `mylon` | Mylon Freixo | Operador | 10.000,00 NC | `MYL0N26` | Painel administrativo (`/admin`), controle de demanda/throttle ao vivo, log Modbus, suíte de testes e exportação CSV |

Na tela de login, clicar em uma conta preenche e envia o formulário.

> **Regra de integridade veicular:** cada conta pode possuir múltiplos carros cadastrados e adicionar novos veículos avulsos no formulário de recarga (com opção de salvar para futuras recargas ou carregar o carro de um terceiro). Por integridade física e operacional do sistema, **um mesmo veículo não pode ter duas recargas ativas simultaneamente**, sendo bloqueado com mensagem amigável caso tente nova sessão enquanto a anterior não for paga e liberada.

---

## 🧭 Roteiro de demonstração (≈ 5 min, ao vivo)

O roteiro completo da apresentação (falas, passo a passo dos aparelhos e plano B)
fica fora do repositório, na pasta `Pitch GoodWe\Apresentacao ao vivo`. Resumo:

### Parte 1 — App do motorista (`amanda`, só software)
1. **Mapa de postos** → cada posto tem uma cor: Paulista verde (livre), Faria Lima amarelo (potência dividida), Berrini vermelho (lotado).
2. **Faria Lima → C5 (VIP) → Iniciar Recarga VIP** → o BYD (`BRA2E19`) aparece bloqueado como "Carregando em P2-C4"; o Kwid (`RIO4F22`) é aprovado.
3. **Voltar ao posto** → a potência foi redividida por prioridade: 6,0 · 6,0 · 6,6 · 7,2 · 7,2 kW (33 kW no total).
4. **Encerrar o C5 → pagar com NexusCoin** → 10% de cashback. Com conta, o conector só é liberado depois do pagamento.
5. **Painel do operador** (`mylon`, `/dashboard`) → "Decisões de potência" registra a redistribuição e o rebalanceamento. A lista de sessões se atualiza sozinha.

### Parte 2 — Totem do posto (`/modo/totem`, abre no Paulista C4, só software)
6. **Com conta:** "Entrar com conta existente" → QR → o celular confirma sem senha → "Olá, Luiz" → iniciar → encerrar e pagar no totem (cartão por aproximação) ou no celular.
7. **Sem conta:** placa → sinal de R$ 50,00 → QR "Acompanhe no Celular" → encerrar pelo celular: o restante do sinal é devolvido.

### Parte 3 — Totem físico (ESP32, portas 1–3 da Paulista)
8. Rodapé do totem → **Totem físico (ESP32)** → plugar o celular-carro na porta 1 → login pelo QR → recarga a 11 kW simulados (a medição do sensor fica em `/esp32`) → tirar o cabo → o totem pede o pagamento.

---

## 🏗️ Arquitetura

Arquitetura modular em camadas, sem dependências circulares. Nenhuma regra de
negócio vive na camada web.

```
iniciar.bat             Menu de inicialização para Windows (web · gestão · testes)

models.py               Entidades e enums (ChargingSession, SessionStatus, UserType)
   ↑
algoritmos.py           Busca e ordenação manuais + estatísticas (só stdlib)
   ↑
session_manager.py      Ciclo de vida das sessões e acúmulo de energia
   ↑
power_manager.py        Controle de demanda: limite, throttle, rebalanceamento
   ↑
modbus_simulator.py     Simulação do protocolo Modbus TCP (registradores HCA G2)

pricing_engine.py       Tarifação dinâmica em 3 eixos
logica_recarga.py       Lógica de simulação do Sprint 1

db.py                   Persistência SQLite (stdlib) — carteira, reservas, histórico
auth.py                 Contas e autenticação (mockup acadêmico)
wallet.py               Carteira NexusCoin: saldo, débito, crédito, cashback
reservations.py         Reserva de conector com sinal e expiração preguiçosa
billing.py              Composição da cobrança de uma sessão encerrada
qr.py                   QR Code simulado em SVG (Pix)
   ↑
app.py                  Camada web Flask — rotas, validação e orquestração
menu.py                 Camada de terminal — mesmo sistema, sem Flask
templates/              29 telas e 3 parciais (Modo App e Modo Totem)
static/                 favicon
test_chargegrid.py      414 testes automatizados
seed_historico.py       Gerador de histórico sintético para as análises
```

`app.py` e `menu.py` são dois pontos de entrada para o **mesmo** sistema: a
mesma classe de sessão, a mesma lista dentro do `SessionManager`, os mesmos
algoritmos. `menu.py` não importa Flask e roda sem nenhuma dependência
instalada.

Os módulos ficam lado a lado de propósito. O grafo de dependência é uma
estrela em volta do `app.py` — ele importa **12 dos 15** outros módulos de
produção; `models.py` é importado por 11, `db.py` por 5, `algoritmos.py` e
`pricing_engine.py` por 3 cada, e todo o resto por 0, 1 ou 2. Os 16 módulos
somam **35 arestas de import** entre si, e não existe subgrupo que converse
mais consigo mesmo do que com o resto: dividir por tema deixaria a maioria dos
imports atravessando a fronteira. Pasta que não esconde nada é gaveta, não
camada.

Virar um pacote `chargegrid/` esconderia todas elas — essa seria estrutura de
verdade — ao custo de reescrever **233 linhas de import**, 197 delas na suíte
de testes. Decidimos que não se paga nesta escala.

---

## 💰 Regras de negócio

### Controle de potência
- Limite por posto: **33 kW** (3 conectores a 11 kW cabem; o 4º dispara throttle)
- Piso por conector: **4,2 kW** (mínima trifásica do HCA G2)
- Pesos de prioridade na redistribuição: Padrão 1,00 · Corporativo 1,10 · Assinante 1,20

### Tarifação (R$/kWh)
| Componente | Fator | Condição |
|---|:-:|---|
| Tarifa base | R$ 1,20 | sempre |
| Horário de pico | × 1,50 | 18h–22h59 |
| Alta demanda | × 1,30 | ocupação do posto ≥ 70% |
| Desconto assinante | − 15% | categoria Assinante |
| Desconto corporativo | − 10% | categoria Corporativo |
| Taxa mínima | R$ 2,00 | piso por sessão |

A tarifa é **fixada no momento da conexão** e não sofre reajuste retroativo.

### NexusCoin
| Regra | Valor |
|---|---|
| Paridade | 1 NexusCoin = R$ 1,00 |
| Cashback ao pagar com NexusCoin | 10% do valor pago |
| Cashback com Pix ou cartão | nenhum |
| Sinal de reserva | R$ 10,00, debitados no ato |
| Saldo negativo | proibido |

### Reserva
| Desfecho | Destino do sinal |
|---|---|
| Compareceu e iniciou a recarga | vira crédito e abate o pagamento |
| Prazo de 15 min expirou | retido como taxa por bloqueio de conector |
| Cancelou dentro do prazo | estorno integral |

O abatimento nunca excede o subtotal: um sinal maior que o consumo zera a conta
e o excedente **não** vira crédito na carteira — do contrário, reservar e
carregar por um minuto seria uma forma de mover dinheiro de graça.

---

## 🔌 Integração Modbus (registradores HCA G2)

| Registrador | Função | Acesso |
|:-:|---|:-:|
| 10017 | Status da estação | Leitura |
| 10015 | Potência de recarga (÷10 = kW) | Leitura |
| 10016 | Energia da sessão (÷10 = kWh) | Leitura |
| 10029 | Potência máxima de recarga | Leitura/Escrita |
| 10025 | Gestão dinâmica de carga | Leitura/Escrita |
| 10060 | Liga/desliga recarga | Leitura/Escrita |
| 10026 | Corrente do disjuntor (A) | Leitura/Escrita |

---

## 🗺️ Rotas

### Modo App / Usuário (Mobile)
| Método | Rota | Função |
|---|---|---|
| GET/POST | `/login` | Autenticação e seleção de conta de demonstração |
| GET | `/logout` | Encerra a sessão de login |
| GET | `/modo/<modo>` | Alterna entre Modo App e Modo Totem |
| GET | `/` | Mapa de postos interativo |
| GET | `/posto/<id>` | Conectores do posto, com reserva e encerramento |
| GET | `/posto/<id>/carregador/<id>` | Formulário de recarga com seleção/cadastro de veículos |
| POST | `/sessao` | Cria a sessão de recarga |
| POST | `/api/reservar` | Reserva conector com débito de sinal (R$ 10,00) |
| POST | `/api/reserva/cancelar` | Cancela reserva e estorna sinal integralmente |
| POST | `/sessao/<id>/encerrar` | Encerra recarga (conector retido até confirmação de pagamento) |
| GET | `/pagamento/<id>` | Tela de pagamento (NexusCoin, Pix, Cartão salvo) |
| POST | `/pagamento/<id>/confirmar` | Efetiva pagamento, libera o conector e credita cashback |
| GET | `/recibo/<id>` | Comprovante com contagem dinâmica de cashback e exportação |
| GET | `/carteira` | Saldo, extrato auditável e recarga NexusCoin |
| POST | `/carteira/recarregar` | Compra de créditos NexusCoin via Pix ou cartão |

### Modo Totem / Autoatendimento (Tela touch vertical do totem físico)
| Método | Rota | Função |
|---|---|---|
| GET | `/totem` | Tela inicial do totem físico com status dos conectores locais |
| GET/POST | `/totem/configurar` | Configuração inicial do posto associado ao hardware do totem |
| GET | `/totem/entrar` | Exibe QR Code dinâmico para pareamento com smartphone |
| GET | `/totem/entrar/<token>/estado` | Polling de verificação de pareamento consumido pelo totem |
| GET/POST | `/celular/parear/<token>` | Rota mobile de confirmação de pareamento do usuário com o totem |
| GET | `/celular/parear/<token>/status` | Polling dinâmico de telemetria da recarga no smartphone pareado |
| POST | `/celular/parear/<token>/encerrar` | Encerra a recarga pelo smartphone e direciona para quitação no app |
| GET/POST | `/totem/veiculo` | Seleção de conector e veículo cadastrado na tela do totem |
| GET/POST | `/totem/sem-conta` | Identificação por placa e conector para visitante sem cadastro |
| GET/POST | `/totem/sem-conta/pagar` | Pagamento do sinal de R$ 50,00 (cartão por aproximação ou Pix) que libera a recarga pré-paga |
| GET | `/totem/carregando` | Monitoramento vertical da recarga em andamento no conector do totem |
| GET | `/totem/carregando/status` | Polling dinâmico de telemetria exibido no display do totem |
| POST | `/totem/encerrar` | Encerra recarga diretamente na tela do totem |
| GET | `/totem/pagamento/<id>/status` | Sincronização omnichannel: detecta pagamento móvel e avança tela do totem |
| GET | `/totem/recibo/<id>` | Recibo do totem com acerto de consumo e estorno do saldo de sinal |
| POST | `/totem/sair` | Desconecta a conta pareada do totem e retorna ao estado inicial |
| GET | `/avulso/<token>` | Acompanhamento mobile da recarga avulsa de visitante |
| GET | `/avulso/<token>/status` | Polling dinâmico de telemetria da recarga avulsa no smartphone |
| POST | `/avulso/<token>/encerrar` | Encerra a recarga avulsa pelo smartphone do visitante |
| POST | `/avulso/<token>/pagar-excedente` | Pagamento móvel do excedente (> R$ 50) liberando conector na hora |

### Operador (Staff) e Integração IoT
| Método | Rota | Função |
|---|---|---|
| GET | `/admin` | Hub central do operador |
| GET | `/dashboard` | Painel de potência, ocupação e sessões ativas ao vivo |
| POST | `/dashboard/nova-sessao` | Criação de sessão manual pelo operador |
| POST | `/dashboard/encerrar` | Encerramento de sessão pelo painel |
| GET | `/relatorio` | Relatório gerencial e financeiro consolidado. Busca e ordenação em Python: `?busca=&ordenar=&dir=&fonte=` |
| GET | `/modbus-log` | Log de tráfego de frames industriais Modbus TCP |
| GET | `/testes` · POST `/api/testes/run` | Suíte completa de testes executável no navegador |
| GET | `/admin/export.csv` | Histórico de sessões em CSV |
| POST | `/sessao/<id>/liberar` | Desbloqueio forçado de conector retido |
| POST | `/admin/demo-reset` | Restauração completa do estado de demonstração |
| GET | `/api/status` | Polling JSON (5 s) de telemetria e potência dos postos |
| POST | `/api/energia` | Integração IoT solar (Raspberry Pi Pico W): aplica orçamento dinâmico bidirecional |

---

## 🔌 Totem físico (ESP32) — protótipo de bancada

Um ESP32 com 3 sensores de corrente (INA219) e 3 LEDs de semáforo simula o
posto Paulista (P1): as portas físicas 1–3 são os conectores `P1-C1..C3`.
Plugar um aparelho abre a recarga; desplugar encerra. Tudo roda sem alterar o
fluxo do app — o ESP32 só envia leituras para `POST /api/esp32/portas`.

**Como ligar**
1. Copie `firmware/totem_esp32/config.example.h` para `config.h` (fica fora do
   Git) e preencha `WIFI_SSID`, `WIFI_SENHA`, `SERVIDOR_IP` (o IP da linha
   "Rede" que o servidor mostra ao iniciar) e `TOKEN_ESP32`.
2. Envie `totem_esp32.ino` ao ESP32 pela Arduino IDE (placa e Wi-Fi **2,4 GHz**).
3. Suba o servidor (`python3 app.py`). Se o IP do banner sair errado, force com
   `CHARGEGRID_HOST_IP=<ip>`. Para trocar o token de desenvolvimento, defina
   `CHARGEGRID_ESP32_TOKEN` (o mesmo valor do `config.h`).
4. Abra `/modo/totem` em **um navegador** e o app/operador em **outro**: o modo
   é guardado em cookie, então um navegador não faz os dois ao mesmo tempo.
5. Em `/totem/fisico` (atalho "Totem físico (ESP32)" no rodapé do totem) a tela
   acompanha as portas. Ao plugar, o motorista entra pelo QR (o celular confirma
   com a própria conta, sem senha); quem não tem conta paga antes (pré-pago).
   "Voltar ao totem" retorna ao totem comum, que por padrão controla o
   **Paulista C4** — um conector só de software, fora das portas físicas.

**Regras do protótipo**
- Presença: corrente ≥ 20 mA, decidida no servidor (`esp32.LIMIAR_PRESENCA_MA`);
  desplugue confirmado após 3 leituras seguidas.
- Potência medida: o ESP32 envia tensão e corrente e o servidor grava a
  medição (visível em `/esp32`). **Por padrão a cobrança usa a potência simulada
  do conector (até 11 kW)**, para a demonstração ser previsível. Para cobrar pela
  medida, inicie com `CHARGEGRID_COBRANCA_MEDIDA=1`: então **1 W medido vale 1 kW**
  (celulares no lugar dos carros), limitado a 11 kW e à alocada, e sem medição por
  mais de 10 s a recarga acumula 0 kW.
- Semáforo do posto: verde (< 50 % da potência), amarelo (≥ 50 %), vermelho (cheio).
- Com conta: desplugar encerra a recarga e o totem vai para o pagamento. O
  conector **só é liberado depois de pago**; até lá o valor aparece como
  pendente na Carteira (acima de R$ 100 ou 7 dias, novas recargas ficam bloqueadas).
- Página de diagnóstico do ESP32: `/esp32`.

Alterações feitas para isso e pontos em aberto: `docs/PONTOS_PARA_O_GRUPO.md`.

---

## 🧪 Testes

```bash
pytest -v   # ou pela interface, em /testes
```

**414 testes** em 47 classes. A suíte roda contra um banco temporário por teste,
então executá-la **não altera o `chargegrid.db` da demonstração**.

| Suíte | Cobertura |
|---|---|
| PricingEngine | Os três eixos de tarifa e as fronteiras de horário |
| PowerManager · Alocação / Rebalance | Limites, throttle, recusa física e prioridade |
| SessionManager | Energia em tempo real, idempotência, taxa mínima |
| Flask Routes | Todas as rotas, incluindo posto lotado e fluxos de erro |
| Regressão e Auditoria | Não-reincidência dos bugs corrigidos |
| Conector VIP | Exclusividade do conector C5 |
| **Autenticação** | Guarda de acesso, staff × usuário, open redirect |
| **Modo App e Modo Totem** | Alternância de modos, isolamento de modos e consistência de sessão |
| **Veículos e Integridade** | Múltiplos carros por conta, placa única ativa e cadastro avulso |
| **Totem com Conta** | Pareamento via QR Code, ciclo de vida do token e sessão remota |
| **Totem sem Conta** | Sinal de R$ 50,00 pré-pago, encerrar no totem ou no celular devolve o restante |
| **Carteira** | Saldos iniciais, débito/crédito, saldo insuficiente, extrato |
| **Reserva** | Débito do sinal, unicidade, cancelamento, expiração |
| **Billing** | Abatimento do sinal, teto do abatimento, cashback |
| **Pagamento** | Três métodos, propriedade da sessão, duplo clique, CSV |
| **QR simulado** | Determinismo e rótulo acessível |
| **Estruturas de Dados** | Busca e ordenação manuais, contagens contra as fórmulas fechadas, estabilidade, coleção vazia, guarda anti-`sorted` |
| **Integração dos algoritmos** | Testes-espião: falham se `get_session` deixar de usar a busca sequencial ou o `rebalance` deixar de usar o insertion sort |
| **Carregamento do histórico** | Reconstrução das sessões do SQLite, banco ausente e arquivo corrompido |
| **Menu de terminal** | As 7 opções, validações de entrada, `EOFError` e falha dentro de uma opção |
| **Memória × histórico** | Os rótulos que separam sessões desta execução do histórico arquivado, e a consulta única que substituiu uma por sessão |
| **Tarifa com fonte única** | `pricing_engine` reexporta as constantes de `logica_recarga` em vez de redeclará-las |
| **Robustez e Concorrência** | Isolamento de sinal de reserva concluída, exigência de quitação de excedente avulso > R$ 50, estorno automático ≤ R$ 50, proteção contra clock skew em `duration_seconds`, injeção de cabeçalhos OWASP, bloqueio de backslash open-redirect, páginas de erro 404/500 customizadas e sincronização omnichannel totem-celular |
| **Melhorias Comerciais e IoT** | Orçamento bidirecional (`aplicar_orcamento`), endpoint `POST /api/energia` (Pico W em watts e kW), rebalanceamento automático no encerramento pelo totem, restauração completa em memória e banco no `demo-reset` |

---

## 🧮 Estruturas de Dados e Algoritmos

Os algoritmos de busca e ordenação foram implementados diretamente no núcleo
do sistema e operam em produção tanto nas rotas web quanto no terminal.

| Algoritmo | Big-O | Onde o sistema usa |
|---|:-:|---|
| `busca_sequencial` | O(n) | `SessionManager.get_session` e o campo de busca do `/relatorio` (`buscar`) |
| `merge_sort` | O(n log n) | `ordenar_por` — cabeçalhos da tabela do `/relatorio`; opções 4 e 6 do menu |
| `insertion_sort` | O(n²) / O(n) | `PowerManager.rebalance` — toda vez que um conector é liberado |
| `busca_binaria` | O(log n) | opção 3 do menu, como contraste medido |
| `bubble_sort` | O(n²) | opção 4 do menu |

`algoritmos.py` importa **apenas** `models` e a biblioteca padrão — nada de
Flask, nada de SQLite. Dentro dele não há `.sort(`, `sorted(`, `.index(` nem
`bisect`, e um teste automatizado varre o arquivo para garantir que continue
assim.

O menu de terminal abre sobre o histórico real do banco:

```bash
python menu.py   # menu interativo, 7 opções
```

```
=====================================
        ESTAÇÃO DE RECARGA
      ChargeGrid Intelligence
=====================================

1 - Nova sessão de recarga
2 - Listar sessões
3 - Buscar sessão
4 - Ordenar sessões
5 - Estatísticas
6 - Comparar algoritmos (Big-O na prática)
7 - Encerrar
```

A opção 6 mede busca e ordenação sobre a coleção real, em vários tamanhos de
entrada. Com 180 sessões no banco:

| n | busca sequencial | busca binária | bubble | n(n−1)/2 | insertion | insertion já ordenada | merge O(n log n) |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 10 | 10 | 4 | 45 | 45 | 32 | 9 | 23 |
| 50 | 50 | 6 | 1.225 | 1.225 | 678 | 49 | 222 |
| 180 | 180 | 8 | 16.110 | 16.110 | 7.933 | 179 | 1.116 |

A coluna do bubble é idêntica à fórmula fechada em todas as linhas, a do
insertion em lista já ordenada é exatamente n−1 — o melhor caso linear que
justifica o insertion no `rebalance` — e o `merge_sort` mantém crescimento
garantido O(n log n) na ordenação de tabelas completas no `/relatorio`.

A análise completa, com o trecho de código que provoca o crescimento de cada
algoritmo, está no **`RELATORIO_SPRINT3_DSA.pdf`**, que acompanha o pacote
de entrega — fora deste repositório, porque é documento de disciplina e não
parte do aplicativo.

---

## 📊 Dados para as análises estatísticas

As disciplinas de Modelagem Linear e de Estruturas de Dados precisam de algumas
centenas de sessões. O gerador produz um histórico plausível **pelas mesmas
regras do produto** (tarifa da PricingEngine, potências entre 4,2 e 11 kW,
horários com pico às 19h):

```bash
python seed_historico.py 300 --limpar --semente 42
```

Depois, entre como `mylon` e baixe em **`/admin/export.csv`**.

Com a base gerada acima, a regressão `duração → energia` devolve coeficiente
angular **0,1603 kWh/min** (R² = 0,865) — que **multiplicado por 60 dá 9,62 kW**,
próximo da potência média realmente entregue nas sessões, 9,32 kW, e dentro da
faixa do GW11K-HCA-20. A diferença entre os dois vem do intercepto negativo
(−0,47 kWh): a reta cobra um custo fixo de partida que não existe, e compensa
com uma inclinação um pouco maior. A dispersão em torno dela é o throttling.

---

## 🎨 Design

Modo **Operate**: o usuário está executando uma tarefa, então escaneabilidade e
consistência valem mais que expressão. A marca vive nos detalhes.

- **Tokens** para tipografia (escala fixa, razão 1,125), espaçamento (base 4px),
  raios e movimento — substituindo os ~25 tamanhos de fonte e 18 espaçamentos
  soltos do Sprint 2
- **Contraste WCAG AA** nos dois temas: a paleta separa cor de *superfície* de
  cor de *texto*, porque `#C00000` é ótimo como fundo de botão (6,48:1) e
  reprovado como cor de link sobre o card escuro (2,26:1)
- **Números tabulares** em todo valor que muda ou aparece em coluna — sem isso o
  dashboard "dança" a cada atualização de 5 segundos
- **Foco de teclado visível** em todo controle e respeito a `prefers-reduced-motion`
- **Três momentos de deleite**, e só três: countdown da reserva, contagem do
  cashback no recibo e realce de valores no dashboard

A marca **NexusCharge** é um `<symbol>` SVG inline definido uma vez em
`base.html`: acompanha o tema, funciona a 20px no menu de perfil e serve
também de símbolo da moeda NexusCoin.

---

## 🛠️ Stack

- **Backend:** Python 3 · Flask
- **Persistência:** SQLite (`sqlite3` da stdlib — sem ORM, sem instalação)
- **Frontend:** HTML5 · CSS3 · JavaScript (vanilla, sem framework)
- **Mapa:** Leaflet + OpenStreetMap
- **Testes:** pytest
- **Protocolo:** Modbus TCP (simulado)

---

## 👥 Equipe

Projeto desenvolvido para o **EV Challenge 2026** (FIAP + GoodWe).

| Nome | RM |
|---|---|
| Giovanne Gomes Petenuci | 574091 |
| Arthur Vettorazzo de Souza | 569445 |
| Gustavo Zibini Belizario | 561376 |
| Alan Junio Araujo de Souza | 574112 |
| Brayan Barbosa Dos Santos | 573682 |
| Luiz Otávio Brito Freixo | 569977 |

---

## 📄 Licença

Projeto acadêmico desenvolvido no contexto do EV Challenge 2026 (FIAP + GoodWe).
