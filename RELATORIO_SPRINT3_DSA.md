# Relatório — Sprint 3 · Estruturas de Dados

**ChargeGrid Intelligence · NexusCharge** — EV Challenge 2026 · FIAP + GoodWe

Programa analisado: **`gestao_sessoes.py`**

Execução:

```
python gestao_sessoes.py              # menu interativo
python gestao_sessoes.py --autoteste  # verificação dos algoritmos
```

Todas as medições deste relatório foram produzidas pela opção **6 — Comparar
algoritmos** do próprio programa, e podem ser reproduzidas.

**Repositório:** https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3

---

## Onde encontrar cada item do enunciado

Cada linha aponta o arquivo, a função e a linha. Os títulos são links diretos
para o código no repositório.

| Item do enunciado | Onde está |
|---|---|
| 1. Estrutura da sessão (classe) | [`gestao_sessoes.py`, `class Sessao`, linha 53](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L53-L109) |
| 2. Registro de múltiplas sessões (lista) | [`sessoes: List[Sessao]`, linha 127](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L118-L141) · `append` em `cadastrar_sessao()`, `len()` em `listar_sessoes()` |
| 3. Menu principal com laço | [`MENU` linha 682 e `main()` linha 698](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L682-L751) — o `while True` está na linha 722 |
| 4. Busca — sequencial | [`busca_sequencial()`, linha 190](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L190-L212) |
| 4. Busca — binária | [`busca_binaria()`, linha 215](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L215-L252) |
| 5. Ordenação — Bubble Sort | [`bubble_sort()`, linha 267](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L267-L298) |
| 5. Ordenação — Insertion Sort | [`insertion_sort()`, linha 301](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L301-L344) |
| 5. Critério escolhido pelo usuário | [`CRITERIOS`, linha 259](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L255-L265) — ID, energia, custo e tempo |
| 6. Estatísticas da estação | [`estatisticas()`, linha 353](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L353-L400) e `mostrar_estatisticas()`, linha 593 |
| 7. Funções organizando as operações | tabela completa na seção 2 deste relatório |
| 8. Tratamento de dados e validações | [`ler_numero()`, linha 414](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L414-L446) · `id_existe()` linha 139 · captura de exceção em `main()`, linha 743 |
| 9. Análise de algoritmos (Big-O) | seção 5 deste relatório, e as docstrings dos quatro algoritmos no código |
| 10. Comparação entre algoritmos | seção 6 deste relatório · medição executável em [`comparar_algoritmos()`, linha 622](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py#L622-L679) |

### Arquivos da entrega

| Arquivo | O que é |
|---|---|
| [`gestao_sessoes.py`](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/gestao_sessoes.py) | **o programa desta Sprint** — 811 linhas, só biblioteca padrão |
| [`RELATORIO_SPRINT3_DSA.md`](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/RELATORIO_SPRINT3_DSA.md) | este documento |
| [`RELATORIO_SPRINT3_DSA.pdf`](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/RELATORIO_SPRINT3_DSA.pdf) | este documento em PDF |
| [`test_chargegrid.py`](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/test_chargegrid.py) | suíte do projeto; a classe `TestGestaoSessoes` cobre os algoritmos |
| [`iniciar.bat`](https://github.com/FIAP-Time6-GoodWe-2026/ChargeGridIntelligence-NexusCharge-Sprint3/blob/main/iniciar.bat) | dois cliques no Windows: instala o que falta e abre um menu |

O restante do repositório é o aplicativo web das outras disciplinas da Sprint
(Flask + SQLite). Ele **não** implementa os algoritmos avaliados aqui — usa
`sorted()` livremente, o que o enunciado permite "nas demais partes do
sistema". Os algoritmos escritos à mão estão todos em `gestao_sessoes.py`.

### Como executar

```
python gestao_sessoes.py
```

Ou, no Windows, dois cliques em `iniciar.bat` e a opção **2** do menu.

---

## 1. Estrutura utilizada para representar uma sessão

A sessão é uma **classe** (`Sessao`, declarada como `dataclass`):

```python
@dataclass
class Sessao:
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
```

### Por que classe e não dicionário

Um dicionário aceitaria `s["enrgia"]` — repare no erro de digitação — sem
reclamar, e só quebraria na hora de somar, com um `KeyError` longe da origem
do problema. A classe fixa o contrato:
os campos existem, têm tipo declarado, e o erro de digitação aparece na
escrita. Como as funções de busca e ordenação leem sempre os mesmos
atributos, essa garantia vale mais aqui do que a flexibilidade do dicionário.

O `@dataclass` gera `__init__` e `__repr__` a partir da declaração dos
campos — é a mesma classe do exemplo do enunciado, sem o construtor
repetitivo.

### Atributos além dos quatro obrigatórios

Os quatro exigidos são `id`, `energia`, `tempo` e `custo`. Os demais existem
porque o programa consome o histórico real do sistema:

| Atributo | Papel |
|---|---|
| `codigo` | identificador da sessão no app web (ex.: `CGI-1480B94E`) |
| `veiculo` | placa, exibida na listagem e na consulta |
| `tarifa` | R$/kWh aplicada, permite conferir `custo ÷ energia` |
| `conector` | carregador usado (`P1-C3`), liga a sessão ao posto |
| `tipo` | categoria tarifária (P/A/C) |
| `data`, `hora` | quando a recarga começou |
| `status` | `PAGA` (veio do banco) ou `MANUAL` (cadastrada no menu) |

### Armazenamento: uma lista

```python
sessoes: List[Sessao] = []
sessoes.append(nova_sessao)
len(sessoes)
```

A escolha da `list` é deliberada e vale registrar: um `dict` indexado por ID
resolveria a busca em O(1) e tornaria a Sprint inteira sem assunto. A lista
tem posições, e é a existência de posições que dá sentido a ordenar e a
buscar por divisão do intervalo. O custo dessa escolha é exatamente o que a
seção 5 mede.

---

## 2. Funcionamento geral do programa

### Origem dos dados

Ao iniciar, o programa tenta ler as sessões pagas de `chargegrid.db` — o
mesmo banco que o app web (`app.py`) alimenta quando uma recarga é
encerrada e paga. Cada linha vira um objeto `Sessao` e recebe um `id`
inteiro sequencial.

Sem banco, sem tabela ou sem sessões, o programa abre com a lista vazia em
vez de recusar-se a iniciar; o cadastro pelo menu preenche a lista. O CLI
**nunca escreve** no banco: é ferramenta de análise, e manter a escrita fora
daqui impede que um experimento de ordenação altere o histórico de
faturamento.

### Menu

```
=====================================
        ESTAÇÃO DE RECARGA
=====================================

1 - Nova sessão de recarga
2 - Listar sessões
3 - Buscar sessão
4 - Ordenar sessões
5 - Estatísticas
6 - Comparar algoritmos (Big-O na prática)
7 - Encerrar
```

O laço é `while True` e só termina na opção 7. Opção inexistente é avisada e
o menu volta a ser exibido.

### Divisão em funções

| Função | Responsabilidade |
|---|---|
| `carregar_do_banco()` | lê o histórico e monta a lista inicial |
| `cadastrar_sessao()` | coleta e valida os dados de uma nova sessão |
| `listar_sessoes()` | imprime a tabela na ordem atual da lista |
| `buscar_sessao()` | pergunta o algoritmo, executa e mostra o resultado |
| `ordenar_sessoes()` | pergunta critério e algoritmo, ordena, relista |
| `mostrar_estatisticas()` | imprime o resumo agregado |
| `comparar_algoritmos()` | mede comparações em entradas crescentes |
| `busca_sequencial()` `busca_binaria()` | algoritmos de busca |
| `bubble_sort()` `insertion_sort()` | algoritmos de ordenação |
| `estatisticas()` | agrega em uma passada e devolve os valores |
| `ler_numero()` `ler_texto()` | entrada validada |
| `main()` | laço do menu e despacho das operações |

As funções de algoritmo são puras em relação ao menu: recebem a lista e
devolvem resultado, sem imprimir nada. Isso é o que permite chamá-las
dentro do comparativo da opção 6 e do autoteste sem duplicar código.

### Critérios de ordenação

O critério é passado como parâmetro — uma função que extrai o valor
comparável:

```python
CRITERIOS = {
    "1": ("ID",                lambda s: s.id),
    "2": ("Energia consumida", lambda s: s.energia),
    "3": ("Custo da sessão",   lambda s: s.custo),
    "4": ("Tempo de recarga",  lambda s: s.tempo),
}
```

Sem isso seriam quatro cópias de cada algoritmo, uma por atributo. A lógica
de ordenação fica num lugar só e os quatro critérios são configuração.

### Estatísticas

Calculadas sobre as sessões realmente armazenadas, em **uma única passada**
pela lista — quatro agregações independentes seriam quatro varreduras, e
todas precisam do mesmo elemento ao mesmo tempo:

```
========== ESTATÍSTICAS DA ESTAÇÃO ==========

   Sessões realizadas .... 180
   Energia fornecida ..... 2878.19 kWh
   Faturamento ........... R$ 4205.76
   Ticket médio .......... R$ 23.37
   Maior consumo ......... 38.41 kWh
   Menor consumo ......... 2.07 kWh
   Tempo total ........... 18445.0 min
```

Lista vazia devolve zeros em vez de estourar: `min()` sobre lista vazia é
`ValueError`, e o menu precisa continuar de pé.

### Validações

| Situação | Tratamento |
|---|---|
| Texto onde se espera número | `try/except ValueError`, nova tentativa (até 3) |
| Energia, tempo ou custo negativo | recusado com a faixa aceita na mensagem |
| ID duplicado | verificado com `busca_sequencial` antes de inserir |
| Opção de menu inválida | avisada; o laço continua |
| Enter vazio | cancela a operação e volta ao menu |
| `Ctrl+C` / fim de entrada | encerra a operação sem *traceback* |
| Exceção inesperada numa operação | capturada em `main()`; o menu sobrevive |

Nenhuma entrada do usuário encerra o programa inesperadamente.

---

## 3. Algoritmo de busca utilizado

Dois algoritmos, escolhidos pelo usuário na opção 3.

### 3.1 Busca sequencial

```python
def busca_sequencial(colecao, id_procurado):
    comparacoes = 0
    for i in range(len(colecao)):
        comparacoes += 1
        if colecao[i].id == id_procurado:
            return i, comparacoes
    return -1, comparacoes
```

Percorre a lista da primeira posição à última e devolve o índice do
elemento, ou `-1` se não existir. **Não exige lista ordenada** — é a única
busca aplicável logo depois de um cadastro, antes de qualquer ordenação. É
também a que `id_existe()` usa para barrar ID duplicado.

### 3.2 Busca binária

```python
def busca_binaria(colecao, id_procurado):
    inicio, fim, comparacoes = 0, len(colecao) - 1, 0
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
```

Compara com o elemento central e descarta metade do intervalo a cada passo.

**Pré-condição:** a lista precisa estar ordenada pelo mesmo atributo da
busca. Sobre uma lista desordenada o algoritmo descarta a metade errada e
devolve `-1` para um elemento que existe. Quem chama é responsável por
garantir isso — por esse motivo `buscar_sessao()` ordena por ID com o
`insertion_sort` antes de chamar, e informa na tela:

```
Lista ordenada por ID primeiro (179 comparações no insertion sort).
Busca binária: encontrada na posição 41 (6 comparações).
```

Nenhuma função pronta (`index`, `in`, `bisect`) substitui os dois
algoritmos.

---

## 4. Algoritmo de ordenação utilizado

Dois algoritmos, escolhidos pelo usuário na opção 4. Ambos ordenam a lista
*in-place* e devolvem o número de comparações realizadas.

### 4.1 Bubble Sort

```python
def bubble_sort(colecao, chave):
    n = len(colecao)
    comparacoes = 0
    for i in range(n):
        for j in range(n - 1 - i):
            comparacoes += 1
            if chave(colecao[j]) > chave(colecao[j + 1]):
                colecao[j], colecao[j + 1] = colecao[j + 1], colecao[j]
    return comparacoes
```

Compara pares vizinhos e troca os que estão fora de ordem. A cada passada
do laço externo o maior elemento restante "flutua" até o fim, e por isso o
laço interno encolhe (`n - 1 - i`).

Não tem parada antecipada: mesmo com a lista já ordenada, faz o mesmo
número de comparações.

### 4.2 Insertion Sort

```python
def insertion_sort(colecao, chave):
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
```

Trata a porção à esquerda como já ordenada e insere cada novo elemento na
posição certa dela, deslocando os maiores para a direita. O `break` é o que
dá a ele o melhor caso linear: encontrando um vizinho menor ou igual, para
de recuar.

Nem `sort()` nem `sorted()` são usados em nenhum ponto do arquivo.

---

## 5. Análise de complexidade (Big-O)

### 5.1 Busca sequencial — O(n)

O trecho que provoca o crescimento:

```python
for i in range(len(colecao)):
```

O laço visita uma posição por iteração.

- **melhor caso:** elemento na primeira posição → 1 comparação
- **pior caso:** elemento na última, ou ausente → `n` comparações
- **caso médio:** ~n/2 comparações

A notação descreve o pior caso e descarta a constante: n/2 e n crescem na
mesma proporção, então ambos são **O(n)**. Dobrar o número de sessões dobra
o número máximo de verificações.

### 5.2 Busca binária — O(log n)

```python
while inicio <= fim:
    meio = (inicio + fim) // 2
```

Cada iteração descarta metade do intervalo restante. Partindo de `n`
posições, a sequência n → n/2 → n/4 → … chega a 1 depois de **log₂(n)**
passos. Medido pelo programa (elemento ausente, pior caso):

| n | Sequencial | Binária | log₂(n) |
|---:|---:|---:|---:|
| 10 | 10 | 4 | 3,3 |
| 100 | 100 | 7 | 6,6 |
| 1.000 | 1.000 | 10 | 10,0 |
| 10.000 | 10.000 | 14 | 13,3 |

Dobrar a entrada acrescenta **uma** comparação à busca binária, contra o
dobro na sequencial.

### 5.3 Bubble Sort — O(n²)

Os dois laços aninhados:

```python
for i in range(n):
    for j in range(n - 1 - i):
```

O externo roda `n` vezes; o interno roda `n-1-i` vezes, encolhendo a cada
passada. O total é a soma

```
(n-1) + (n-2) + ... + 2 + 1  =  n(n-1)/2  =  (n² - n)/2
```

Na notação assintótica a constante ½ e o termo linear `-n` são descartados:
sobra **n²**. A medição do programa bate com a fórmula exatamente, porque
não há parada antecipada:

| n | Bubble (medido) | n(n-1)/2 |
|---:|---:|---:|
| 10 | 45 | 45 |
| 25 | 300 | 300 |
| 50 | 1.225 | 1.225 |
| 100 | 4.950 | 4.950 |
| 200 | 19.900 | 19.900 |

De n=100 para n=200 as comparações vão de 4.950 para 19.900: o dobro de
dados, **quatro vezes** o trabalho. É a assinatura do crescimento
quadrático.

Sobre o histórico real do projeto, com 180 sessões, ordenar por energia
custou **16.110 comparações** — exatamente 180 × 179 / 2.

### 5.4 Insertion Sort — O(n²) no pior caso, O(n) no melhor

```python
for i in range(1, len(colecao)):
    while j >= 0:
```

No pior caso (lista em ordem inversa) o `while` recua até o início a cada
elemento, e o total volta a ser n(n-1)/2 — **mesma classe do bubble**.

No melhor caso (lista já ordenada) a condição falha na primeira comparação
de cada elemento: **n-1** comparações no total, crescimento **linear**.

Medido pelo programa, sobre a mesma lista ordenada duas vezes seguidas:

| n | Bubble (2ª vez) | Insertion (2ª vez) |
|---:|---:|---:|
| 50 | 1.225 | 49 |
| 200 | 19.900 | 199 |

O bubble não muda nada; o insertion cai para `n-1`.

---

## 6. Comparação e significado prático

### Busca: O(n) contra O(log n)

Com 10.000 sessões, a busca sequencial faz até 10.000 comparações e a
binária, 14. A diferença não é "um pouco mais rápido": é a diferença entre
um custo que acompanha o tamanho do arquivo e um custo que praticamente não
muda.

Mas a binária tem um preço escondido: ela **exige a lista ordenada**. Se for
preciso ordenar antes de cada busca, o custo real é o da ordenação — O(n²)
com os algoritmos desta Sprint — e a busca sequencial sai na frente. A
binária compensa quando a lista já está ordenada, ou quando muitas buscas
são feitas entre duas alterações. Foi por isso que o programa deixa a
escolha na mão do usuário em vez de eleger uma delas.

### Ordenação: dois O(n²) que se comportam diferente

Bubble e insertion pertencem à mesma classe assintótica, e ainda assim o
insertion fez, na medição acima, cerca de **metade** das comparações do
bubble com entrada aleatória, e **cem vezes menos** com entrada já
ordenada.

A lição é sobre o que a notação Big-O diz e o que ela não diz: ela classifica
o crescimento no pior caso e ignora constantes. Dois algoritmos O(n²) podem
ter desempenhos muito diferentes no caso médio — e é por isso que a análise
assintótica orienta a escolha, mas não substitui a medição.

### Tamanho da entrada → operações → desempenho

```
        n  →  operações  →  complexidade  →  desempenho
       180        16.110         O(n²)         instantâneo
    10.000    ~50 milhões        O(n²)         segundos
   100.000     ~5 bilhões        O(n²)         inviável
```

Para as 180 sessões do histórico atual, qualquer um dos algoritmos resolve
sem que o usuário perceba. Se a rede de eletropostos crescer para dezenas
de milhares de sessões, o bubble sort deixa de ser aceitável — e o caminho
não é otimizar o laço, é trocar por um algoritmo O(n log n) como merge sort
ou quicksort. **A escolha do algoritmo, e não a velocidade do computador, é
o que decide se o sistema escala.**

---

## 7. Verificação

O arquivo traz uma bateria de asserções executável:

```
$ python gestao_sessoes.py --autoteste
gestao_sessoes.py OK — busca, ordenação e estatísticas verificadas.
```

Ela confere: busca sequencial encontrando e não encontrando; bubble sort
por ID; insertion sort por energia; busca binária sobre lista ordenada,
com acerto e com ausência; a contagem de comparações do bubble batendo
n(n-1)/2; o melhor caso do insertion em n-1; os seis valores estatísticos;
e a coleção vazia devolvendo zeros sem estourar.

Os mesmos algoritmos também são cobertos pela suíte do projeto
(`test_chargegrid.py`, classe `TestGestaoSessoes`).
