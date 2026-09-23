# =============================================================================
#  ChargeGrid Intelligence — QR Code (ISO/IEC 18004) em SVG
#  Sprint 3 | FIAP + GoodWe EV Challenge 2026
# =============================================================================

"""
Codificador de QR Code escrito só com a biblioteca padrão.

Existe porque o QR do totem precisa ser lido por um celular de verdade: é ele
que leva o motorista da tela do totem para a confirmação no celular. A versão
anterior deste módulo desenhava um padrão parecido com um QR a partir de um
hash — bonito, mas nenhum leitor o decodificava.

Escopo, escolhido para o que o sistema precisa e nada além:
    - modo byte (UTF-8), que cobre URLs e qualquer texto
    - nível de correção M (recupera ~15% de módulos danificados)
    - versões 1 a 10, até 213 bytes de conteúdo

O QR sai sempre escuro sobre fundo branco, com a zona de silêncio de 4
módulos que o padrão exige. Isso não é estética: leitores não reconhecem QR
invertido, e herdar a cor do texto fazia o código ficar claro sobre escuro no
tema noturno.

Referência de algoritmo: a mesma sequência de etapas das implementações de
referência — dados → blocos → Reed-Solomon → intercalação → posicionamento →
máscara de menor penalidade → informação de formato e de versão.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# Por versão, nível M: (blocos curtos, dados por bloco curto, blocos longos,
# codewords de correção por bloco). Blocos longos têm um byte de dado a mais.
_BLOCOS_M: dict[int, Tuple[int, int, int, int]] = {
    1: (1, 16, 0, 10),  2: (1, 28, 0, 16),  3: (1, 44, 0, 26),
    4: (2, 32, 0, 18),  5: (2, 43, 0, 24),  6: (4, 27, 0, 16),
    7: (4, 31, 0, 18),  8: (2, 38, 2, 22),  9: (3, 36, 2, 22),
    10: (4, 43, 1, 26),
}
_ALINHAMENTO: dict[int, List[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_FORMATO_M: int = 0b00          # bits do nível M na informação de formato
ZONA_SILENCIO: int = 4


# ---------------------------------------------------------------------------
# Aritmética em GF(256) e Reed-Solomon
# ---------------------------------------------------------------------------

def _gf_mul(x: int, y: int) -> int:
    """Produto em GF(2^8) com o polinômio 0x11D do padrão QR."""
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(grau: int) -> List[int]:
    resultado = [0] * (grau - 1) + [1]
    raiz = 1
    for _ in range(grau):
        for j in range(grau):
            resultado[j] = _gf_mul(resultado[j], raiz)
            if j + 1 < grau:
                resultado[j] ^= resultado[j + 1]
        raiz = _gf_mul(raiz, 0x02)
    return resultado


def _rs_resto(dados: List[int], divisor: List[int]) -> List[int]:
    resultado = [0] * len(divisor)
    for byte in dados:
        fator = byte ^ resultado.pop(0)
        resultado.append(0)
        for i, coef in enumerate(divisor):
            resultado[i] ^= _gf_mul(coef, fator)
    return resultado


# ---------------------------------------------------------------------------
# Montagem dos codewords
# ---------------------------------------------------------------------------

def _capacidade(versao: int) -> int:
    curtos, k, longos, _ = _BLOCOS_M[versao]
    return curtos * k + longos * (k + 1)


def _codewords(conteudo: bytes, versao: int) -> List[int]:
    """Dados + terminador + preenchimento, divididos em blocos com RS e intercalados."""
    bits: List[int] = []

    def poe(valor: int, tamanho: int) -> None:
        bits.extend((valor >> i) & 1 for i in reversed(range(tamanho)))

    poe(0b0100, 4)                                    # modo byte
    poe(len(conteudo), 8 if versao < 10 else 16)      # contagem de caracteres
    for b in conteudo:
        poe(b, 8)

    capacidade = _capacidade(versao) * 8
    poe(0, min(4, capacidade - len(bits)))            # terminador
    poe(0, (8 - len(bits) % 8) % 8)                   # completa o byte
    preenchimento = (0xEC, 0x11)
    i = 0
    while len(bits) < capacidade:
        poe(preenchimento[i % 2], 8)
        i += 1

    dados = [int("".join(map(str, bits[j:j + 8])), 2) for j in range(0, len(bits), 8)]

    curtos, k, longos, grau_ec = _BLOCOS_M[versao]
    divisor = _rs_divisor(grau_ec)
    blocos, ecs, pos = [], [], 0
    for n in range(curtos + longos):
        tamanho = k + (1 if n >= curtos else 0)
        bloco = dados[pos:pos + tamanho]
        pos += tamanho
        blocos.append(bloco)
        ecs.append(_rs_resto(bloco, divisor))

    saida: List[int] = []
    for i in range(k + 1):
        for bloco in blocos:
            if i < len(bloco):
                saida.append(bloco[i])
    for i in range(grau_ec):
        for ec in ecs:
            saida.append(ec[i])
    return saida


# ---------------------------------------------------------------------------
# Matriz: padrões fixos, dados e máscara
# ---------------------------------------------------------------------------

class _Matriz:
    def __init__(self, versao: int) -> None:
        self.versao = versao
        self.lado = versao * 4 + 17
        self.mod = [[False] * self.lado for _ in range(self.lado)]
        self.fixo = [[False] * self.lado for _ in range(self.lado)]
        self._padroes_fixos()

    def _poe(self, x: int, y: int, escuro: bool) -> None:
        self.mod[y][x] = escuro
        self.fixo[y][x] = True

    def _localizador(self, cx: int, cy: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.lado and 0 <= y < self.lado:
                    d = max(abs(dx), abs(dy))
                    self._poe(x, y, d not in (2, 4))

    def _padroes_fixos(self) -> None:
        n = self.lado
        for i in range(n):                                # temporização
            self._poe(6, i, i % 2 == 0)
            self._poe(i, 6, i % 2 == 0)
        self._localizador(3, 3)
        self._localizador(n - 4, 3)
        self._localizador(3, n - 4)
        pos = _ALINHAMENTO[self.versao]
        for i, a in enumerate(pos):                       # alinhamento
            for j, b in enumerate(pos):
                canto = (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) \
                    or (i == len(pos) - 1 and j == 0)
                if not canto:
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            self._poe(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self._formato(0)                                  # reserva a área
        self._versao()

    def _formato(self, mascara: int) -> None:
        dados = _FORMATO_M << 3 | mascara
        resto = dados
        for _ in range(10):
            resto = (resto << 1) ^ ((resto >> 9) * 0x537)
        bits = (dados << 10 | resto) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1              # noqa: E731
        n = self.lado
        for i in range(6):
            self._poe(8, i, bit(i))
        self._poe(8, 7, bit(6))
        self._poe(8, 8, bit(7))
        self._poe(7, 8, bit(8))
        for i in range(9, 15):
            self._poe(14 - i, 8, bit(i))
        for i in range(8):
            self._poe(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._poe(8, n - 15 + i, bit(i))
        self._poe(8, n - 8, True)                         # módulo escuro fixo

    def _versao(self) -> None:
        if self.versao < 7:
            return
        resto = self.versao
        for _ in range(12):
            resto = (resto << 1) ^ ((resto >> 11) * 0x1F25)
        bits = self.versao << 12 | resto
        for i in range(18):
            escuro = (bits >> i) & 1 == 1
            a, b = self.lado - 11 + i % 3, i // 3
            self._poe(a, b, escuro)
            self._poe(b, a, escuro)

    def dados(self, codewords: List[int]) -> None:
        total = len(codewords) * 8
        i = 0
        direita = self.lado - 1
        while direita >= 1:
            if direita == 6:
                direita = 5
            for vert in range(self.lado):
                for j in range(2):
                    x = direita - j
                    subindo = ((direita + 1) & 2) == 0
                    y = self.lado - 1 - vert if subindo else vert
                    if not self.fixo[y][x] and i < total:
                        self.mod[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            direita -= 2

    def mascarar(self, mascara: int) -> None:
        condicoes = (
            lambda x, y: (x + y) % 2 == 0,
            lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        )
        cond = condicoes[mascara]
        for y in range(self.lado):
            for x in range(self.lado):
                if not self.fixo[y][x] and cond(x, y):
                    self.mod[y][x] = not self.mod[y][x]

    def penalidade(self) -> int:
        """Regras N1 a N4 do padrão, para escolher a máscara mais legível."""
        n, m, total = self.lado, self.mod, 0
        for linhas in (m, [list(c) for c in zip(*m)]):
            for linha in linhas:                          # N1: corridas de 5+
                corrida = 1
                for a, b in zip(linha, linha[1:]):
                    if a == b:
                        corrida += 1
                    else:
                        total += corrida - 2 if corrida >= 5 else 0
                        corrida = 1
                total += corrida - 2 if corrida >= 5 else 0
                texto = "".join("1" if v else "0" for v in linha)
                total += 40 * (texto.count("10111010000")   # N3
                               + texto.count("00001011101"))
        for y in range(n - 1):                            # N2: blocos 2x2
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    total += 3
        escuros = sum(map(sum, m))                        # N4: equilíbrio
        total += 10 * (abs(escuros * 20 - n * n * 10) // (n * n))
        return total


def _matriz(texto: str) -> _Matriz:
    conteudo = texto.encode("utf-8")
    versao = next((v for v in _BLOCOS_M
                   if _capacidade(v) * 8 >= 4 + (8 if v < 10 else 16) + 8 * len(conteudo)),
                  None)
    if versao is None:
        raise ValueError(f"Conteúdo grande demais para um QR até a versão 10 "
                         f"({len(conteudo)} bytes).")
    codewords = _codewords(conteudo, versao)

    melhor: Optional[Tuple[int, _Matriz]] = None
    for mascara in range(8):
        m = _Matriz(versao)
        m.dados(codewords)
        m.mascarar(mascara)
        m._formato(mascara)
        pontos = m.penalidade()
        if melhor is None or pontos < melhor[0]:
            melhor = (pontos, m)
    return melhor[1]


def qr_svg(texto: str, rotulo: str = "QR Code") -> str:
    """
    Devolve o `<svg>` de um QR Code legível por qualquer leitor.

    Escuro sobre branco, com zona de silêncio, e escalável: o SVG ocupa 100%
    do container, e quem define o tamanho na tela é o CSS de quem o usa.

    Args:
        texto  : conteúdo (URL ou texto), até 213 bytes em UTF-8
        rotulo : descrição para leitores de tela
    """
    m = _matriz(texto)
    lado = m.lado + 2 * ZONA_SILENCIO
    caminho = "".join(
        f"M{x + ZONA_SILENCIO} {y + ZONA_SILENCIO}h1v1h-1z"
        for y in range(m.lado) for x in range(m.lado) if m.mod[y][x]
    )
    return (
        f'<svg viewBox="0 0 {lado} {lado}" role="img" aria-label="{rotulo}" '
        f'shape-rendering="crispEdges" width="100%" height="100%">'
        f'<rect width="{lado}" height="{lado}" fill="#FFFFFF"/>'
        f'<path d="{caminho}" fill="#0B0B0B"/>'
        f'</svg>'
    )


if __name__ == "__main__":
    a = qr_svg("https://exemplo.com.br/totem/parear/abc123")
    assert a == qr_svg("https://exemplo.com.br/totem/parear/abc123"), "deve ser determinístico"
    assert 'fill="#FFFFFF"' in a, "o fundo precisa ser branco"
    print("qr.py OK")
