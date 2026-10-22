# Totem físico (ESP32) — pontos para discutir com o grupo

Documento vivo da homologação (branch `feat/esp32-fase1`, repositório
`gustavozibini/ChargeGridIntelligence-NexusCharge`). Nada disto foi enviado ao
repositório principal: depende de aprovação do grupo.

## A. O que foi alterado em relação ao repositório principal

| Área | Mudança | Por quê |
|---|---|---|
| `esp32.py` / resposta do `/api/esp32/portas` | Campo `semaforo` (verde <50%, amarelo ≥50%, vermelho ≥99,9% de ocupação do posto) | LEDs do totem seguem a ocupação real do posto |
| `esp32.py` (novo) | Validação da mensagem, token, estado das portas, detector de desplugue | Camada de negócio isolada, sem Flask |
| `app.py` | Rotas `/api/esp32/portas`, `/api/esp32/estado`, `/esp32` | Recebe o ESP32 e mostra o painel do operador |
| `app.py` | Rotas `/totem/fisico`, `/totem/fisico/estado`, `/totem/fisico/porta/<n>` | A tela do totem segue a porta plugada (P1-C<n>) |
| `app.py` | Retirar o cabo encerra a recarga ativa (`_encerrar_por_desplugue`) | Fecha o ciclo físico |
| `app.py` | `_seed_demo`: os 4 carros de demonstração saíram da Paulista (P1) para a Faria Lima (P2) | Paulista começa livre para o totem físico |
| `templates/esp32.html`, `totem_fisico.html` (novos) | Painel do operador e tela de espera | |
| `firmware/`, `tools/simular_esp32.py` (novos) | Firmware do ESP32 e simulador | |
| `test_chargegrid.py` | Testes novos + fixture `fora_do_pico` | 2 testes antigos dependiam do horário (falhavam entre 18h e 22h59) |
| `.gitignore`, `README.md`, `veiculos.py` | `config.h` e `.idea/` ignorados; referências de P1→P2 | Consistência com o seed |

## A2. Pagar depois — REVERTIDO (21/10)

Decisão do grupo: **com conta, o conector só é liberado após o pagamento**
(volta a regra original B41/B42).

- Encerrar (app, totem, celular ou cabo retirado) para a energia e redivide a
  potência na hora, mas o conector fica **retido** ("A pagar · Pagar e
  liberar") até o pagamento ser confirmado. A equipe do posto, encerrando a
  recarga de outra pessoa, continua liberando na hora (#B42).
- Cabo retirado no totem físico: o totem vai sozinho para "Recarga encerrada ·
  escolha como pagar".
- Os botões "Pagar depois" saíram das telas de pagamento (app e totem).
- Continua: a lista "Pagamentos pendentes" na Carteira e o limite de R$ 100 /
  7 dias para iniciar outra recarga (`LIMITE_PENDENTE_BRL`, `PRAZO_PENDENTE_DIAS`).
- Limitação que segue: as pendências vivem na memória do servidor.

## A3. ALTERAÇÃO MAIOR (precisa de aval): recarga sem conta pré-paga

Muda a regra original da recarga avulsa (caução de R$ 50 + acerto no fim).

- A recarga sem conta **para sozinha ao consumir o valor pago** (R$ 50);
  nunca há cobrança acima dele (sem "pagar a diferença").
- **Cabo retirado** encerra a recarga, libera o conector e **devolve** a
  sobra (revisão de 19/10: antes não devolvia).
- **Botão "Encerrar" de volta** (revisão de 21/10) nas telas da recarga sem
  conta, no totem e no celular: encerrar antes acerta o consumo e devolve o
  restante do sinal (ex.: consumo R$ 2,00 → volta R$ 48,00).
- O corte é aplicado a cada mensagem do ESP32 (a cada ~1,5 s) e a cada
  consulta de telemetria, sem depender de alguém olhando a tela. Fora do
  totem físico, só ocorre quando alguém consulta a telemetria.
- Textos do totem atualizados ("pré-paga", "o restante é devolvido").
- Efeito: o cadastro de contas novas deixa de ser necessário para a
  demonstração (proposta futura: cadastro simples + "pagar depois").

## B. Decisões de projeto que precisam de aval

1. Posto Paulista (P1): portas 1–3 do totem físico = P1-C1..C3. O totem
   comum (`/modo/totem`) abre por padrão no **P1-C4**, conector só de software
   (revisão de 21/10), para a demonstração do app não depender do hardware.
2. Token do ESP32 em `CHARGEGRID_ESP32_TOKEN`; sem a variável vale o token de
   desenvolvimento (o servidor avisa no banner). Definir antes da apresentação.
3. Desplugar só encerra sessões em que o cabo já foi visto, após 3 leituras
   livres seguidas (~4,5 s). Parâmetros ajustáveis.
4. Recarga avulsa encerrada por desplugue é acertada como Pix (o método
   escolhido fica no cookie do totem e não chega à rota do ESP32).

## C. Melhorias de tela/fluxo observadas (já do projeto original)

1. ~~**Tela do celular após o pagamento** fica em "aguardando"~~ — **feito
   (21/10)**: mostra "Recarga concluída" depois de paga.
2. **Trocar de modo (app/totem) encerra o login** — é intencional (trocam de
   aparelho), mas num único navegador confunde; avaliar aviso na tela ou
   explicar no README que o totem e o app usam navegadores diferentes.
3. **Telemetria do totem deixa de atualizar sem aviso** se o modo muda ou a
   sessão cai (o `fetch` recebe HTML e falha em silêncio). Mostrar "conexão
   perdida" e voltar ao início.
4. **Recibo do totem some sozinho**; o motorista que não salvou o recibo fica
   sem tela de "obrigado" nem caminho claro de volta. Incluir tela final com
   contagem para o início.
5. ~~**Fluxo pós-encerramento no totem**~~ — **feito (21/10)**: o aviso diz
   "Recarga finalizada! Escolha a forma de pagamento para liberar o conector."
6. **Link "Abrir a confirmação em outra aba"** abre `target=_blank`; em
   navegadores embutidos pode não abrir. Oferecer também copiar o link.
7. **Banner "Rede" do servidor** podia mostrar o IP errado — **feito**:
   `_ip_local()` agora usa a interface da rota padrão, aceita só IP privado de
   LAN (192.168 / 10 / 172.16–31) e descarta 192.0.0.x (hotspot iPhone),
   169.254 e loopback. Dá para forçar com `CHARGEGRID_HOST_IP=<ip>`.
8. **README/banner**: saldo do `luiz` (50 NC no README, 150 NC no banner).

9. **Celular sempre logado como `luiz`**: na demonstração não dá para mostrar
   dois motoristas diferentes. Alteração feita (homologação, revisão de
   21/10): a confirmação do QR **não pede senha**. Vale a conta já logada no
   app do celular; sem login, a conta padrão (`luiz`). A conta do operador
   não entra no totem.
10. **Totem de 1 conector × 3 portas físicas**: a tela segue um conector por
    vez; o acompanhamento e o pagamento de uma recarga em outra porta só
    aparecem pelo celular/app.

11. **Celular após o cabo retirado**: a tela de confirmação do QR avisa
    "pagamento pendente na sua conta" e manda pagar pela Carteira (com login).
    Não há mais pagamento pelo link do QR: o link não autentica ninguém.
13. **Segurança (já existia)**: `/celular/parear/<token>/encerrar` faz login
    como o dono do pareamento só com o token do QR. Avaliar exigir senha ou
    invalidar o token ao fim da recarga.
12. ~~Depois de paga, a tela do celular volta a "aguardando"~~ — **feito
    (21/10)**, mesmo item do C1.
14. **Feito em 21/10 (homologação)**: atalho "Totem físico (ESP32)" no rodapé
    do totem (e "Voltar ao totem" na tela física); a lista de sessões do
    painel do operador se atualiza sozinha quando o número de recargas ativas
    muda.

## D. Pendências técnicas do totem físico

- ~~Semáforo reflete a ocupação do posto~~ (feito, firmware 0.2.0).
- Conferir cobrança mínima (0,037 kWh cobrou R$ 2,00): regra do projeto original?
- Medição de potência (firmware 0.3.0): o ESP32 envia `tensao_v` e o servidor
  grava `measured_power_kw` (o mesmo campo que o MeterValues do OCPP vai
  alimentar). **Decisão de 21/10: a cobrança continua na potência simulada de
  11 kW** (demonstração previsível, telas coerentes com painel/semáforo/Modbus).
  Cobrar pela medida (1 W = 1 kW, teto 11 kW e a alocada, medição com mais de
  10 s vale 0) é opcional: `CHARGEGRID_COBRANCA_MEDIDA=1`.
- ~~Presença decidida no firmware~~ (feito): o servidor decide pela corrente.
- Queda de Wi-Fi do ESP32: aceita como limitação conhecida (as recargas seguem até alguém encerrar ou o cabo ser retirado e o ESP32 voltar).
- Detecção por corrente: o ruído é ±0,4 mA e um celular com bateria cheia puxa ~0,7 mA, indistinguível de "desplugado" (limiar 20 mA mantido). Para a demonstração, usar celular com bateria baixa ou carga fixa (resistor ~100 Ω).
- Rede da demonstração (hotspot): iPhone IPv6-only não deu IPv4 ao Mac; testar
  Android ou roteador.
- ~~Seção do README sobre o totem físico~~ (feito).
