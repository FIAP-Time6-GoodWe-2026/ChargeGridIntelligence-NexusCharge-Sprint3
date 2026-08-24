# ⚡ ChargeGrid Intelligence — NexusCharge

> Sistema inteligente de gerenciamento de recarga para eletropostos comerciais
> **EV Challenge 2026 — FIAP + GoodWe · Sprint 3**

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
| **Autenticação** | Quatro contas pré-cadastradas; ninguém chega ao mapa sem entrar. Rotas administrativas restritas ao operador. |
| **NexusCoin** | Moeda interna com paridade 1 NC = R$ 1,00, **10% de cashback** ao pagar a recarga com ela, extrato auditável e recarga por Pix ou cartão. |
| **Reserva com sinal** | Bloqueia um conector por 15 minutos cobrando R$ 10,00. Compareceu, o sinal vira crédito; não compareceu, vira taxa por bloqueio; cancelou no prazo, estorno integral. |
| **Encerrar e pagar** | Botão na tela do posto encerra a própria recarga e leva à tela de pagamento, com NexusCoin, Pix (QR simulado) e cartão salvo. |
| **Menu de perfil** | Avatar no cabeçalho com nome, saldo, atalho de recarga e — para o operador — acesso ao painel. |
| **Painel do operador** | Hub em `/admin` reunindo dashboard, relatório, log Modbus e testes, com indicadores ao vivo e exportação em CSV. |
| **Persistência** | SQLite (`sqlite3` da biblioteca padrão) guarda carteiras, extrato, reservas e histórico de sessões. |
| **Fundação de design** | Escala tipográfica, espaçamento, raios e movimento em tokens; contrastes corrigidos para WCAG AA nos dois temas; foco de teclado visível; `prefers-reduced-motion`. |

---

## 🚀 Como executar

**Pré-requisito:** Python 3.10+. As duas bibliotecas (`flask` e `pytest`) são
instaladas automaticamente na primeira execução. O banco de dados usa o módulo
`sqlite3`, que já vem com o Python — **não há nada a instalar por causa dele**.

### Windows

Dois cliques em **`iniciar.bat`**. Ele confere o Python, instala o que faltar,
sobe o servidor e abre o navegador.

### Qualquer sistema

```bash
pip install flask pytest
python app.py
# http://localhost:5001
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

| Usuário | Nome | Categoria | Saldo inicial | Para que serve na demonstração |
|---|---|---|---:|---|
| `amanda` | Amanda Ribeiro | Assinante (−15%) | 100,00 NC | Caminho feliz: já chega com uma recarga em andamento, encerra, paga com NexusCoin e recebe cashback |
| `allan` | Allan Souza | Corporativo (−10%) | 5,00 NC | Saldo insuficiente: bloqueio da reserva, recarga da carteira e retomada do pagamento |
| `jose` | José Fino | Padrão | 0,00 NC | Carteira zerada: estado vazio do extrato, tarifa cheia e pagamento por Pix ou cartão |
| `mylon` | Mylon Freixo | Operador | 10.000,00 NC | Painel, throttle ao vivo, log Modbus, testes e exportação |

Na tela de login, clicar em uma conta preenche e envia o formulário.

---

## 🧭 Roteiro de demonstração (≈ 4 min)

1. **Entrar como `amanda`** → o mapa mostra os três postos, com Berrini lotado
   e Paulista em throttle.
2. **Abrir o posto Paulista (P1)** → Amanda encontra a **própria recarga em
   andamento** no conector C4.
3. **Reservar o conector C5** → modal com os termos, R$ 10,00 debitados,
   countdown de 15 minutos. Dar F5: o countdown **retoma de onde estava**.
4. **Encerrar a recarga do C4** → tela de pagamento com energia medida, tarifa
   fixada na conexão e total.
5. **Pagar com NexusCoin** → saldo cai, cashback de 10% entra, recibo com o
   valor contando de zero até o crédito.
6. **Entrar como `allan`** (5 NC) → tentar reservar: bloqueio com aviso de
   quanto falta e atalho para a carteira. Recarregar e concluir.
7. **Entrar como `mylon`** → painel do operador: potência por posto, throttle
   ao vivo, frames Modbus, reservas ativas e sinais retidos.

---

## 🏗️ Arquitetura

Arquitetura modular em camadas, sem dependências circulares. Nenhuma regra de
negócio vive na camada web.

```
models.py            Entidades e enums (ChargingSession, SessionStatus, UserType)
   ↑
session_manager.py   Ciclo de vida das sessões e acúmulo de energia
   ↑
power_manager.py     Controle de demanda: limite, throttle, rebalanceamento
   ↑
modbus_simulator.py  Simulação do protocolo Modbus TCP (registradores HCA G2)

pricing_engine.py    Tarifação dinâmica em 3 eixos
logica_recarga.py    Lógica de simulação do Sprint 1

iniciar.bat          Atalho de inicialização para Windows
db.py                Persistência SQLite (stdlib) — carteira, reservas, histórico
auth.py              Contas e autenticação (mockup acadêmico)
wallet.py            Carteira NexusCoin: saldo, débito, crédito, cashback
reservations.py      Reserva de conector com sinal e expiração preguiçosa
billing.py           Composição da cobrança de uma sessão encerrada
qr.py                QR Code simulado em SVG (Pix)
   ↑
app.py               Camada web Flask — rotas, validação e orquestração
templates/           14 telas + partial de cabeçalho
test_chargegrid.py   126 testes automatizados
seed_historico.py    Gerador de histórico sintético para as análises
```

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

### Usuário
| Método | Rota | Função |
|---|---|---|
| GET/POST | `/login` | Autenticação (única rota pública) |
| GET | `/logout` | Encerra a sessão |
| GET | `/` | Mapa de postos |
| GET | `/posto/<id>` | Conectores do posto, com reserva e encerramento |
| GET | `/posto/<id>/carregador/<id>` | Formulário de nova sessão |
| POST | `/sessao` | Cria a sessão de recarga |
| POST | `/api/reservar` | Reserva um conector (débito do sinal) |
| POST | `/api/reserva/cancelar` | Cancela e estorna |
| POST | `/sessao/<id>/encerrar` | Encerra a própria recarga (o conector fica retido até o pagamento) |
| GET | `/pagamento/<id>` | Tela de pagamento |
| POST | `/pagamento/<id>/confirmar` | Efetiva o pagamento |
| GET | `/recibo/<id>` | Comprovante |
| GET | `/carteira` | Saldo e extrato NexusCoin |
| POST | `/carteira/recarregar` | Compra de NexusCoin |

### Operador (staff)
| Método | Rota | Função |
|---|---|---|
| GET | `/admin` | Hub do painel |
| GET | `/dashboard` | Potência, sessões e tarifas em tempo real |
| POST | `/dashboard/nova-sessao` | Cria sessão pelo painel |
| POST | `/dashboard/encerrar` | Encerra sessão pelo painel |
| GET | `/relatorio` | Relatório consolidado |
| GET | `/modbus-log` | Frames Modbus TCP |
| GET | `/testes` · POST `/api/testes/run` | Suíte de testes no navegador |
| GET | `/admin/export.csv` | Histórico de sessões em CSV |
| POST | `/sessao/<id>/liberar` | Libera conector de recarga encerrada e não paga |
| POST | `/admin/demo-reset` | Restaura o estado de demonstração |
| GET | `/api/status` | JSON de polling (5 s) |

---

## 🧪 Testes

```bash
pytest test_chargegrid.py -v      # ou pela interface, em /testes
```

**126 testes** em 17 classes. A suíte roda contra um banco temporário por teste,
então executá-la **não altera o `chargegrid.db` da demonstração**.

| Suíte | Cobertura |
|---|---|
| PricingEngine | Os três eixos de tarifa e as fronteiras de horário |
| PowerManager · Alocação / Rebalance | Limites, throttle, recusa física e prioridade |
| SessionManager | Energia em tempo real, idempotência, taxa mínima |
| Flask Routes | Todas as rotas, incluindo posto lotado |
| Regressão e Auditoria | Não-reincidência dos bugs corrigidos |
| Conector VIP | Exclusividade do conector C5 |
| **Autenticação** | Guarda de acesso, staff × usuário, open redirect |
| **Carteira** | Saldos iniciais, débito/crédito, saldo insuficiente, extrato |
| **Reserva** | Débito do sinal, unicidade, cancelamento, expiração |
| **Billing** | Abatimento do sinal, teto do abatimento, cashback |
| **Pagamento** | Três métodos, propriedade da sessão, duplo clique, CSV |
| **QR simulado** | Determinismo e rótulo acessível |

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
angular ≈ 0,160 kWh/min — que **multiplicado por 60 dá ≈ 9,6 kW**, a potência
média real da instalação, dentro da faixa do GW11K-HCA-20. A dispersão em torno
da reta é o efeito do throttling.

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
