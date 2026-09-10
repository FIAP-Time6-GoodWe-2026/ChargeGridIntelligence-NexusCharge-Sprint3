# =============================================================================
#  ChargeGrid Intelligence — Gestão de Sessões de Recarga (CLI)
#  Sprint 3 · Estruturas de Dados | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Sistema de gerenciamento de sessões de recarga em terminal.

Este módulo é a entrega da disciplina de Estruturas de Dados. Enquanto o
`app.py` opera as recargas ao vivo (potência, tarifa, pagamento), aqui o
recorte é outro: o histórico de sessões já encerradas como uma **coleção**
que precisa ser armazenada, percorrida, pesquisada, ordenada e resumida.

Algoritmos implementados manualmente
------------------------------------
Busca      : sequencial O(n) · binária O(log n)
Ordenação  : bubble sort O(n²) · insertion sort O(n²) — O(n) no melhor caso

Nenhum deles usa `sort()`, `sorted()`, `index()` ou `in` como substituto:
essas funções são o conteúdo avaliado da Sprint e estão escritas à mão. O
restante do programa usa a biblioteca padrão à vontade, como o enunciado
permite.

Origem dos dados
----------------
Na entrada, o programa tenta ler as sessões pagas de `chargegrid.db` — o
mesmo banco que o app web alimenta. Sem banco (ou sem sessões), começa
vazio e o cadastro manual pelo menu preenche a lista. Em nenhum dos dois
casos o CLI escreve no banco: ele é uma ferramenta de análise, e manter a
escrita fora daqui evita que um experimento de ordenação corrompa o
histórico de faturamento.

Uso
---
    python gestao_sessoes.py             # menu interativo
    python gestao_sessoes.py --autoteste # verificação dos algoritmos
"""

from __future__ import annotations

import datetime
import pathlib
import random
import sqlite3
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# Banco de histórico do aplicativo web. É a única ligação com o resto do
# projeto, e ela é opcional: sem o arquivo, o programa abre com a lista vazia.
#
# Dois lugares são procurados, nesta ordem: ao lado deste arquivo (é assim que
# o pacote de entrega vem montado) e na pasta do aplicativo web (é onde o
# banco vive no repositório). Quem procura só num lugar quebra no outro.
BANCO = "chargegrid.db"
LOCAIS_DO_BANCO = (".", "../aplicativo-web")

# ---------------------------------------------------------------------------
# 1. ESTRUTURA DE DADOS — a sessão de recarga
# ---------------------------------------------------------------------------


@dataclass
class Sessao:
    """
    Uma sessão de recarga já encerrada.

    Por que uma classe e não um dicionário
    --------------------------------------
    Um dicionário aceitaria `s["enrgia"]` sem reclamar e só quebraria na
    hora de somar. A classe fixa o contrato: os campos existem, têm tipo
    declarado e o erro de digitação aparece na hora. Como as comparações
    de ordenação e busca leem sempre os mesmos atributos, essa garantia
    vale mais aqui do que a flexibilidade do dicionário.

    Por que uma classe própria e não a `ChargingSession` do app
    -----------------------------------------------------------
    `ChargingSession` (models.py) modela uma recarga **em andamento**:
    potência alocada, estado de throttle, registradores Modbus, energia
    que ainda cresce a cada segundo. Aqui o objeto é um **registro
    histórico imutável** — a recarga acabou e foi paga. Carregar o
    maquinário de tempo real para ordenar uma lista seria acoplamento sem
    contrapartida.

    Atributos
    ---------
    id        : identificador inteiro sequencial, chave da busca
    codigo    : identificador do app web (ex.: "CGI-3F9A2B10"), quando veio de lá
    veiculo   : placa do veículo
    energia   : energia fornecida na sessão, em kWh
    tempo     : duração da recarga, em minutos
    custo     : valor cobrado, em reais
    tarifa    : tarifa aplicada, em R$/kWh
    conector  : carregador utilizado (ex.: "P1-C3")
    tipo      : categoria tarifária do usuário (P, A ou C)
    data      : data da recarga
    hora      : hora de início (0–23)
    status    : situação da sessão
    """

    id: int
    energia: float
    tempo: float
    custo: float
    veiculo: str = "—"
    codigo: str = ""
    tarifa: float = 0.0
    conector: str = "—"
    tipo: str = "P"
    data: str = ""
    hora: int = 0
    status: str = "ENCERRADA"

    def linha(self) -> str:
        """Formata a sessão como uma linha de tabela do menu."""
        return (
            f"{self.id:>4}  {self.veiculo:<9} {self.conector:<7} "
            f"{self.data:<10} {self.hora:>2}h  "
            f"{self.energia:>8.2f}  {self.tempo:>7.1f}  {self.custo:>9.2f}"
        )


CABECALHO = (
    f"{'ID':>4}  {'VEÍCULO':<9} {'CONECTOR':<7} {'DATA':<10} {'H':>3}  "
    f"{'kWh':>8}  {'MINUTOS':>7}  {'CUSTO R$':>9}"
)


# ---------------------------------------------------------------------------
# 2. ARMAZENAMENTO — lista de sessões
# ---------------------------------------------------------------------------

# A coleção é uma `list` e não um `dict` indexado por ID de propósito: busca
# binária e ordenação só fazem sentido sobre uma sequência com posições. Um
# dicionário resolveria a busca em O(1) e tornaria a Sprint inteira sem
# assunto — a escolha aqui é deliberada, e o custo dela é justamente o que a
# análise de complexidade mede.
sessoes: List[Sessao] = []


def proximo_id(colecao: List[Sessao]) -> int:
    """Menor inteiro livre para um novo cadastro (percorre a lista uma vez)."""
    maior = 0
    for s in colecao:
        if s.id > maior:
            maior = s.id
    return maior + 1


def id_existe(colecao: List[Sessao], id_procurado: int) -> bool:
    """True se já há sessão com este ID — usada para barrar duplicidade."""
    return busca_sequencial(colecao, id_procurado)[0] != -1


def carregar_do_banco() -> List[Sessao]:
    """
    Lê as sessões pagas de `chargegrid.db` e devolve a lista correspondente.

    Usa o `sqlite3` da biblioteca padrão em vez de importar o módulo `db.py`
    do aplicativo web: assim este arquivo é executável sozinho, sem precisar
    de nenhum outro arquivo do projeto ao lado dele.

    Falha silenciosa e proposital: sem banco, sem tabela ou sem sessões, o
    programa abre com a lista vazia em vez de recusar-se a iniciar. O CLI
    precisa rodar em qualquer máquina com Python, mesmo sem o app web ter
    sido executado antes.
    """
    aqui = pathlib.Path(__file__).resolve().parent
    caminho = next((c for c in (aqui / p / BANCO for p in LOCAIS_DO_BANCO)
                    if c.exists()), None)
    if caminho is None:
        return []

    try:
        conexao = sqlite3.connect(caminho)
        conexao.row_factory = sqlite3.Row
        linhas = conexao.execute(
            "SELECT * FROM sessoes ORDER BY inicio"
        ).fetchall()
        conexao.close()
    except sqlite3.Error:
        return []

    carregadas: List[Sessao] = []
    for i, linha in enumerate(linhas, start=1):
        # O banco grava "2026-08-09 13:04:22"; a tela usa dd/mm/aaaa, o mesmo
        # formato do cadastro manual — misturar os dois numa coluna só
        # atrapalha a leitura da listagem.
        iso = str(linha["inicio"])[:10]
        inicio = f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if len(iso) == 10 else iso
        carregadas.append(
            Sessao(
                id=i,
                codigo=linha["session_id"],
                veiculo=linha["vehicle_id"],
                energia=round(float(linha["energia_kwh"]), 2),
                tempo=round(float(linha["duracao_min"]), 1),
                custo=round(float(linha["custo_brl"]), 2),
                tarifa=round(float(linha["tarifa_kwh"]), 4),
                conector=linha["charger_id"],
                tipo=linha["user_type"],
                data=inicio,
                hora=int(linha["hora_inicio"]),
                status="PAGA",
            )
        )
    return carregadas


# ---------------------------------------------------------------------------
# 3. BUSCA — implementada manualmente
# ---------------------------------------------------------------------------


def busca_sequencial(colecao: List[Sessao], id_procurado: int) -> Tuple[int, int]:
    """
    Procura uma sessão pelo ID percorrendo a lista do começo ao fim.

    Complexidade: O(n)
    ------------------
    O laço abaixo visita uma posição por iteração. No melhor caso o elemento
    está na primeira (1 comparação); no pior, está na última ou não existe, e
    o laço roda `n` vezes. O crescimento acompanha o tamanho da entrada: com
    o dobro de sessões, o dobro de comparações no pior caso.

    Não exige lista ordenada — é a única busca aplicável logo após um
    cadastro, antes de qualquer ordenação.

    Returns:
        (índice do elemento ou -1, número de comparações realizadas)
    """
    comparacoes = 0
    for i in range(len(colecao)):
        comparacoes += 1
        if colecao[i].id == id_procurado:
            return i, comparacoes
    return -1, comparacoes


def busca_binaria(colecao: List[Sessao], id_procurado: int) -> Tuple[int, int]:
    """
    Procura uma sessão pelo ID dividindo o intervalo de busca ao meio.

    PRÉ-CONDIÇÃO: a lista precisa estar ordenada pelo mesmo atributo da
    busca (ID). Sobre uma lista desordenada o algoritmo descarta metade
    errada e devolve -1 para um elemento que existe — por isso o menu ordena
    antes de chamar esta função.

    Complexidade: O(log n)
    ----------------------
    Cada iteração do `while` descarta metade do intervalo restante. Partindo
    de `n` posições, a sequência n → n/2 → n/4 → ... chega a 1 depois de
    log₂(n) passos. Com 1.000 sessões são no máximo 10 comparações; com
    2.000, apenas 11. Dobrar a entrada acrescenta **uma** comparação, contra
    mil da busca sequencial.

    Returns:
        (índice do elemento ou -1, número de comparações realizadas)
    """
    inicio = 0
    fim = len(colecao) - 1
    comparacoes = 0

    while inicio <= fim:
        meio = (inicio + fim) // 2
        comparacoes += 1
        if colecao[meio].id == id_procurado:
            return meio, comparacoes
        if colecao[meio].id < id_procurado:
            inicio = meio + 1     # descarta a metade de baixo
        else:
            fim = meio - 1        # descarta a metade de cima

    return -1, comparacoes


# ---------------------------------------------------------------------------
# 4. ORDENAÇÃO — implementada manualmente
# ---------------------------------------------------------------------------

# Cada critério é uma função que extrai o valor comparável da sessão. Passar
# o critério como parâmetro evita quatro cópias de cada algoritmo, uma por
# atributo — a lógica de ordenação fica num lugar só.
CRITERIOS: dict = {
    "1": ("ID", lambda s: s.id),
    "2": ("Energia consumida", lambda s: s.energia),
    "3": ("Custo da sessão", lambda s: s.custo),
    "4": ("Tempo de recarga", lambda s: s.tempo),
}


def bubble_sort(colecao: List[Sessao],
                chave: Callable[[Sessao], float]) -> int:
    """
    Ordena a lista in-place comparando pares vizinhos e trocando-os.

    Complexidade: O(n²)
    -------------------
    São dois laços aninhados. O externo roda `n` vezes; o interno roda
    `n-1-i` vezes, encolhendo a cada passada porque o maior elemento já
    ficou no fim. O total é (n-1) + (n-2) + ... + 1 = n(n-1)/2 comparações,
    cujo termo dominante é n² — as constantes e o termo linear somem na
    notação assintótica.

    Na prática: 10 sessões → 45 comparações; 100 sessões → 4.950. Dez vezes
    mais dados, cem vezes mais trabalho.

    Este é o pior dos dois: como não tem parada antecipada, faz o mesmo
    número de comparações mesmo com a lista já ordenada.

    Returns:
        Número de comparações realizadas.
    """
    n = len(colecao)
    comparacoes = 0

    for i in range(n):
        for j in range(n - 1 - i):
            comparacoes += 1
            if chave(colecao[j]) > chave(colecao[j + 1]):
                colecao[j], colecao[j + 1] = colecao[j + 1], colecao[j]

    return comparacoes


def insertion_sort(colecao: List[Sessao],
                   chave: Callable[[Sessao], float]) -> int:
    """
    Ordena a lista in-place inserindo cada elemento na posição certa da
    porção já ordenada à sua esquerda.

    Complexidade: O(n²) no pior caso, O(n) no melhor
    ------------------------------------------------
    O laço externo percorre `n-1` elementos. O interno recua enquanto o
    vizinho da esquerda for maior — no pior caso (lista em ordem inversa)
    recua até o início, e o total volta a ser n(n-1)/2 comparações.

    A diferença para o bubble sort está no melhor caso: com a lista já
    ordenada, a condição do `while` falha na primeira comparação de cada
    elemento e o algoritmo faz apenas `n-1` comparações no total — cresce
    linearmente. É por isso que, ordenando duas vezes seguidas pelo mesmo
    critério, o segundo insertion sort é ordens de grandeza mais barato e o
    bubble sort custa exatamente o mesmo.

    Ambos são O(n²) na notação Big-O, que descreve o pior caso: a mesma
    classe assintótica esconde comportamentos bem diferentes no caso médio.

    Returns:
        Número de comparações realizadas.
    """
    comparacoes = 0

    for i in range(1, len(colecao)):
        atual = colecao[i]
        j = i - 1
        while j >= 0:
            comparacoes += 1
            if chave(colecao[j]) <= chave(atual):
                break
            colecao[j + 1] = colecao[j]
            j -= 1
        colecao[j + 1] = atual

    return comparacoes


ALGORITMOS_ORDENACAO: dict = {
    "1": ("Bubble Sort    (O(n²))", bubble_sort),
    "2": ("Insertion Sort (O(n²) pior · O(n) melhor)", insertion_sort),
}


# ---------------------------------------------------------------------------
# 5. ESTATÍSTICAS
# ---------------------------------------------------------------------------


def estatisticas(colecao: List[Sessao]) -> dict:
    """
    Resume a estação numa única passada pela lista — O(n).

    Quatro agregações independentes seriam quatro varreduras; como todas
    precisam do mesmo elemento ao mesmo tempo, uma passada só entrega tudo.

    Returns:
        Dicionário com totais, médias e extremos. Coleção vazia devolve
        zeros em vez de estourar — chamar `min()` numa lista vazia é
        ValueError, e o menu precisa continuar de pé.
    """
    if not colecao:
        return {"sessoes": 0, "energia": 0.0, "faturamento": 0.0,
                "ticket": 0.0, "maior": 0.0, "menor": 0.0,
                "tempo_total": 0.0}

    energia_total = 0.0
    faturamento = 0.0
    tempo_total = 0.0
    maior = colecao[0].energia
    menor = colecao[0].energia

    for s in colecao:
        energia_total += s.energia
        faturamento += s.custo
        tempo_total += s.tempo
        if s.energia > maior:
            maior = s.energia
        if s.energia < menor:
            menor = s.energia

    # O ticket médio deriva do faturamento JÁ arredondado, não da soma bruta:
    # assim a divisão que o usuário faz de cabeça a partir da tela bate com o
    # número impresso. Somar 36.00 + 15.30 + 10.00 + 54.24 em ponto flutuante
    # dá 115.53999…, e dividir isso por 4 imprimiria 28.88 embaixo de um
    # faturamento de 115.54.
    faturamento = round(faturamento, 2)

    return {
        "sessoes": len(colecao),
        "energia": round(energia_total, 2),
        "faturamento": faturamento,
        "ticket": round(faturamento / len(colecao), 2),
        "maior": round(maior, 2),
        "menor": round(menor, 2),
        "tempo_total": round(tempo_total, 1),
    }


# ---------------------------------------------------------------------------
# 6. ENTRADA VALIDADA
# ---------------------------------------------------------------------------


def ler_texto(rotulo: str, padrao: str = "") -> str:
    """Lê uma linha de texto; Enter vazio aceita o padrão."""
    valor = input(rotulo).strip()
    return valor or padrao


def ler_numero(rotulo: str, minimo: float = 0.0,
               maximo: Optional[float] = None,
               inteiro: bool = False) -> Optional[float]:
    """
    Lê um número validando tipo e faixa, com até 3 tentativas.

    Devolve None quando o usuário desiste (Enter vazio) ou erra três vezes,
    para que a operação em curso seja cancelada sem derrubar o menu. O
    `try/except ValueError` é o que impede que "onze" no lugar de 11 encerre
    o programa.
    """
    for tentativa in range(3):
        bruto = input(rotulo).strip().replace(",", ".")
        if not bruto:
            print("   Operação cancelada.")
            return None
        try:
            valor = int(bruto) if inteiro else float(bruto)
        except ValueError:
            print(f"   Valor inválido: '{bruto}' não é um número.")
            continue
        if valor < minimo:
            print(f"   Valor inválido: não pode ser menor que {minimo:g}.")
            continue
        if maximo is not None and valor > maximo:
            print(f"   Valor inválido: não pode ser maior que {maximo:g}.")
            continue
        return valor

    print("   Três tentativas inválidas — operação cancelada.")
    return None


# ---------------------------------------------------------------------------
# 7. OPERAÇÕES DO MENU
# ---------------------------------------------------------------------------


def cadastrar_sessao(colecao: List[Sessao]) -> None:
    """Coleta os dados de uma nova sessão e a acrescenta à lista."""
    print("\n── NOVA SESSÃO DE RECARGA ──────────────────────────────────")
    sugerido = proximo_id(colecao)

    id_novo = ler_numero(f"   ID [{sugerido}]: ", minimo=1, inteiro=True)
    if id_novo is None:
        id_novo = sugerido
    id_novo = int(id_novo)

    if id_existe(colecao, id_novo):
        print(f"   Já existe uma sessão com o ID {id_novo}. Cadastro cancelado.")
        return

    veiculo = ler_texto("   Placa do veículo [ABC1D23]: ", "ABC1D23")
    energia = ler_numero("   Energia consumida (kWh): ", minimo=0.0)
    if energia is None:
        return
    tempo = ler_numero("   Tempo de recarga (min): ", minimo=0.0)
    if tempo is None:
        return
    custo = ler_numero("   Custo da sessão (R$): ", minimo=0.0)
    if custo is None:
        return
    conector = ler_texto("   Conector [P1-C1]: ", "P1-C1")

    agora = datetime.datetime.now()
    colecao.append(Sessao(
        id=id_novo, energia=energia, tempo=tempo, custo=custo,
        veiculo=veiculo.upper(), conector=conector.upper(),
        tarifa=round(custo / energia, 4) if energia else 0.0,
        data=agora.strftime("%d/%m/%Y"), hora=agora.hour,
        status="MANUAL",
    ))
    print(f"\n   Sessão {id_novo} registrada. "
          f"A estação passa a ter {len(colecao)} sessão(ões).")


def listar_sessoes(colecao: List[Sessao]) -> None:
    """Exibe todas as sessões armazenadas, na ordem atual da lista."""
    print("\n── SESSÕES REGISTRADAS ─────────────────────────────────────")
    if not colecao:
        print("   Nenhuma sessão registrada ainda.")
        print("   Use a opção 1 para cadastrar a primeira.")
        return

    print(f"   {CABECALHO}")
    print("   " + "─" * len(CABECALHO))
    for s in colecao:
        print(f"   {s.linha()}")
    print(f"\n   {len(colecao)} sessão(ões) na lista.")


def buscar_sessao(colecao: List[Sessao]) -> None:
    """Pesquisa uma sessão pelo ID, com escolha do algoritmo de busca."""
    print("\n── BUSCAR SESSÃO ───────────────────────────────────────────")
    if not colecao:
        print("   Não há sessões para pesquisar.")
        return

    print("   1 - Busca sequencial   O(n)     · funciona em qualquer ordem")
    print("   2 - Busca binária      O(log n) · exige lista ordenada por ID")
    escolha = ler_texto("\n   Algoritmo [1]: ", "1")
    if escolha not in ("1", "2"):
        print("   Opção inválida.")
        return

    alvo = ler_numero("   Digite o ID da sessão: ", minimo=1, inteiro=True)
    if alvo is None:
        return
    alvo = int(alvo)

    if escolha == "1":
        indice, comparacoes = busca_sequencial(colecao, alvo)
        nome = "Busca sequencial"
    else:
        # A pré-condição da busca binária é responsabilidade de quem chama:
        # ordenamos por ID (com o nosso próprio algoritmo) antes de buscar.
        trocas = insertion_sort(colecao, CRITERIOS["1"][1])
        print(f"   Lista ordenada por ID primeiro "
              f"({trocas} comparações no insertion sort).")
        indice, comparacoes = busca_binaria(colecao, alvo)
        nome = "Busca binária"

    print()
    if indice == -1:
        print(f"   {nome}: sessão {alvo} não encontrada "
              f"({comparacoes} comparações).")
        return

    s = colecao[indice]
    print(f"   {nome}: encontrada na posição {indice} "
          f"({comparacoes} comparações).")
    print(f"   {'─' * 46}")
    print(f"   ID .............. {s.id}")
    if s.codigo:
        print(f"   Código .......... {s.codigo}")
    print(f"   Veículo ......... {s.veiculo}")
    print(f"   Conector ........ {s.conector}")
    print(f"   Data / hora ..... {s.data} · {s.hora}h")
    print(f"   Energia ......... {s.energia:.2f} kWh")
    print(f"   Tempo ........... {s.tempo:.1f} min")
    print(f"   Tarifa .......... R$ {s.tarifa:.4f}/kWh")
    print(f"   Custo ........... R$ {s.custo:.2f}")
    print(f"   Status .......... {s.status}")


def ordenar_sessoes(colecao: List[Sessao]) -> None:
    """Ordena a lista pelo critério e algoritmo escolhidos pelo usuário."""
    print("\n── ORDENAR SESSÕES ─────────────────────────────────────────")
    if len(colecao) < 2:
        print("   São necessárias ao menos duas sessões para ordenar.")
        return

    print("   Ordenar por:")
    for codigo, (rotulo, _) in CRITERIOS.items():
        print(f"     {codigo} - {rotulo}")
    criterio = ler_texto("\n   Critério [1]: ", "1")
    if criterio not in CRITERIOS:
        print("   Critério inválido.")
        return

    print("\n   Algoritmo:")
    for codigo, (rotulo, _) in ALGORITMOS_ORDENACAO.items():
        print(f"     {codigo} - {rotulo}")
    alg = ler_texto("\n   Algoritmo [1]: ", "1")
    if alg not in ALGORITMOS_ORDENACAO:
        print("   Algoritmo inválido.")
        return

    rotulo_criterio, chave = CRITERIOS[criterio]
    rotulo_alg, funcao = ALGORITMOS_ORDENACAO[alg]

    comparacoes = funcao(colecao, chave)

    print(f"\n   Ordenado por {rotulo_criterio.lower()} usando "
          f"{rotulo_alg.split('(')[0].strip()}.")
    print(f"   {comparacoes} comparações em {len(colecao)} elementos.")
    listar_sessoes(colecao)


def mostrar_estatisticas(colecao: List[Sessao]) -> None:
    """Exibe o resumo agregado da estação."""
    e = estatisticas(colecao)
    print("\n========== ESTATÍSTICAS DA ESTAÇÃO ==========")
    print()
    print(f"   Sessões realizadas .... {e['sessoes']}")
    print(f"   Energia fornecida ..... {e['energia']:.2f} kWh")
    print(f"   Faturamento ........... R$ {e['faturamento']:.2f}")
    print(f"   Ticket médio .......... R$ {e['ticket']:.2f}")
    print(f"   Maior consumo ......... {e['maior']:.2f} kWh")
    print(f"   Menor consumo ......... {e['menor']:.2f} kWh")
    print(f"   Tempo total ........... {e['tempo_total']:.1f} min")
    print()
    print("=" * 45)
    if not colecao:
        print("   (sem sessões — os valores são zero, não um erro)")


def _amostra(tamanho: int) -> List[Sessao]:
    """Lista de `tamanho` sessões em ordem aleatória, para o comparativo."""
    rng = random.Random(42)   # semente fixa: a medição é reprodutível
    ids = list(range(1, tamanho + 1))
    for i in range(len(ids) - 1, 0, -1):      # embaralhamento de Fisher-Yates
        j = rng.randint(0, i)
        ids[i], ids[j] = ids[j], ids[i]
    return [Sessao(id=i, energia=i * 1.5, tempo=i * 2.0, custo=i * 1.2)
            for i in ids]


def comparar_algoritmos(colecao: List[Sessao]) -> None:
    """
    Mede as comparações de cada algoritmo em entradas de tamanhos crescentes.

    A tabela é a ponte entre a notação e o desempenho: mostra o número de
    operações realmente executadas ao lado do que a fórmula previa.
    """
    print("\n── COMPLEXIDADE NA PRÁTICA ─────────────────────────────────")
    print("\n   ORDENAÇÃO — comparações por tamanho de entrada\n")
    print(f"   {'n':>5}  {'Bubble':>10}  {'Insertion':>10}  "
          f"{'n(n-1)/2':>10}")
    print("   " + "─" * 42)

    for n in (10, 25, 50, 100, 200):
        amostra_b = _amostra(n)
        amostra_i = _amostra(n)
        cb = bubble_sort(amostra_b, CRITERIOS["1"][1])
        ci = insertion_sort(amostra_i, CRITERIOS["1"][1])
        print(f"   {n:>5}  {cb:>10}  {ci:>10}  {n * (n - 1) // 2:>10}")

    print("\n   O bubble sort bate exatamente n(n-1)/2 porque não tem parada")
    print("   antecipada. Dobrar n multiplica as comparações por ~4: é o n².")

    print("\n   Melhor caso — a mesma lista, já ordenada:\n")
    for n in (50, 200):
        ja_ordenada_b = _amostra(n)
        bubble_sort(ja_ordenada_b, CRITERIOS["1"][1])
        cb = bubble_sort(ja_ordenada_b, CRITERIOS["1"][1])
        ja_ordenada_i = _amostra(n)
        insertion_sort(ja_ordenada_i, CRITERIOS["1"][1])
        ci = insertion_sort(ja_ordenada_i, CRITERIOS["1"][1])
        print(f"   n={n:>4}  Bubble {cb:>7}  ·  Insertion {ci:>7}")

    print("\n   O insertion cai para n-1 comparações; o bubble não muda nada.")
    print("   Mesma classe O(n²), comportamentos diferentes no caso médio.")

    print("\n   BUSCA — comparações no pior caso (elemento ausente)\n")
    print(f"   {'n':>5}  {'Sequencial':>11}  {'Binária':>9}")
    print("   " + "─" * 30)
    for n in (10, 100, 1000, 10000):
        lista = [Sessao(id=i, energia=1.0, tempo=1.0, custo=1.0)
                 for i in range(1, n + 1)]
        _, cs = busca_sequencial(lista, n + 1)
        _, cbin = busca_binaria(lista, n + 1)
        print(f"   {n:>5}  {cs:>11}  {cbin:>9}")

    print("\n   Sequencial acompanha n. Binária acompanha log₂(n): dez mil")
    print("   sessões custam 14 comparações, contra dez mil da sequencial.")

    if colecao:
        n = len(colecao)
        print(f"\n   Na sua lista atual, com {n} sessões: o bubble sort faria")
        print(f"   até {n * (n - 1) // 2} comparações e a busca binária, no máximo")
        print(f"   {max(1, n.bit_length())}.")


# ---------------------------------------------------------------------------
# 8. MENU PRINCIPAL
# ---------------------------------------------------------------------------

MENU = """
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
"""


def main() -> None:
    """Laço principal do menu: só termina quando o usuário escolhe encerrar."""
    global sessoes
    sessoes = carregar_do_banco()

    print("\n" + "=" * 45)
    print("  ChargeGrid Intelligence · Gestão de Sessões")
    print("  Sprint 3 — Estruturas de Dados")
    print("=" * 45)
    if sessoes:
        print(f"\n  {len(sessoes)} sessões carregadas de chargegrid.db.")
    else:
        print("\n  Nenhuma sessão no banco — começando com a lista vazia.")
        print("  Cadastre pela opção 1, ou rode o app web para gerar histórico.")

    acoes = {
        "1": cadastrar_sessao,
        "2": listar_sessoes,
        "3": buscar_sessao,
        "4": ordenar_sessoes,
        "5": mostrar_estatisticas,
        "6": comparar_algoritmos,
    }

    while True:
        print(MENU)
        try:
            opcao = input("Escolha: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nEncerrado.")
            return

        if opcao == "7":
            print(f"\nEncerrando. {len(sessoes)} sessão(ões) na lista.\n")
            return

        acao = acoes.get(opcao)
        if acao is None:
            print(f"\n   Opção inválida: '{opcao}'. Escolha de 1 a 7.")
            continue

        try:
            acao(sessoes)
        except (EOFError, KeyboardInterrupt):
            print("\n   Operação interrompida.")
        except Exception as erro:            # rede de segurança do menu
            # Nenhuma falha de uma operação pode derrubar o programa: o
            # enunciado exige que entrada incorreta não encerre o sistema.
            print(f"\n   Erro inesperado na operação: {erro}")


# ---------------------------------------------------------------------------
# Autoteste — prova executável dos algoritmos
# ---------------------------------------------------------------------------


def autoteste() -> None:
    """Verifica busca e ordenação contra resultados conhecidos."""
    amostra = [
        Sessao(id=5, energia=30.0, tempo=95.0, custo=36.00),
        Sessao(id=1, energia=12.5, tempo=40.0, custo=15.30),
        Sessao(id=9, energia=8.0,  tempo=25.0, custo=10.00),
        Sessao(id=3, energia=45.2, tempo=140.0, custo=54.24),
    ]

    # Busca sequencial encontra em qualquer ordem
    assert busca_sequencial(amostra, 9)[0] == 2
    assert busca_sequencial(amostra, 77)[0] == -1

    # Bubble sort por ID
    lista = list(amostra)
    bubble_sort(lista, CRITERIOS["1"][1])
    assert [s.id for s in lista] == [1, 3, 5, 9]

    # Insertion sort por energia
    lista = list(amostra)
    insertion_sort(lista, CRITERIOS["2"][1])
    assert [s.energia for s in lista] == [8.0, 12.5, 30.0, 45.2]

    # Busca binária sobre a lista ordenada por ID
    lista = list(amostra)
    insertion_sort(lista, CRITERIOS["1"][1])
    assert busca_binaria(lista, 5)[0] == 2
    assert busca_binaria(lista, 4)[0] == -1

    # Contagem de comparações do bubble bate a fórmula n(n-1)/2
    n = 12
    assert bubble_sort(_amostra(n), CRITERIOS["1"][1]) == n * (n - 1) // 2

    # Insertion no melhor caso (já ordenada) faz n-1 comparações
    ordenada = _amostra(n)
    insertion_sort(ordenada, CRITERIOS["1"][1])
    assert insertion_sort(ordenada, CRITERIOS["1"][1]) == n - 1

    # Estatísticas
    e = estatisticas(amostra)
    assert e["sessoes"] == 4
    assert e["energia"] == 95.7
    assert e["faturamento"] == 115.54
    assert e["ticket"] == 28.89
    assert e["maior"] == 45.2
    assert e["menor"] == 8.0

    # Coleção vazia não estoura
    assert estatisticas([])["sessoes"] == 0

    print("gestao_sessoes.py OK — busca, ordenação e estatísticas verificadas.")


if __name__ == "__main__":
    if "--autoteste" in sys.argv:
        autoteste()
    else:
        main()
