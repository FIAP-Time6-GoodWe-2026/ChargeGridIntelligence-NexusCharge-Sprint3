"""
Simulador do ESP32 para testar o servidor sem o hardware.

Envia ao Flask o mesmo JSON que o firmware envia, a cada ciclo, com as portas
que você escolher marcadas como plugadas. Só usa a biblioteca padrão.

Exemplos:
    python tools/simular_esp32.py                      # tudo livre, 1 envio
    python tools/simular_esp32.py --plugadas 1 3       # portas 1 e 3 plugadas
    python tools/simular_esp32.py --plugadas 2 --ciclos 20 --intervalo 1.5
    python tools/simular_esp32.py --plugadas 1 --corrente 2000  # 10 W = 10 kW
    python tools/simular_esp32.py --sem-sensor 3       # INA219 da porta 3 mudo
    python tools/simular_esp32.py --token errado       # deve receber 401
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def montar_mensagem(plugadas: set, sem_sensor: set,
                    corrente_ma: float = 1000.0) -> dict:
    portas = []
    for n in (1, 2, 3):
        ok = n not in sem_sensor
        presente = ok and n in plugadas
        portas.append({
            "porta": n,
            "corrente_ma": corrente_ma if presente else 0.0,
            "tensao_v": 5.0 if ok else 0.0,
            "presente": presente,
            "leitura_ok": ok,
        })
    return {"fw": "simulador", "portas": portas}


def enviar(url: str, token: str, mensagem: dict) -> tuple:
    req = urllib.request.Request(
        url, data=json.dumps(mensagem).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-ESP32-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read().decode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:5001/api/esp32/portas")
    ap.add_argument("--token",
                    default=os.environ.get("CHARGEGRID_ESP32_TOKEN",
                                           "chargegrid-esp32-dev"))
    ap.add_argument("--plugadas", type=int, nargs="*", default=[],
                    help="números das portas plugadas (1 a 3)")
    ap.add_argument("--sem-sensor", type=int, nargs="*", default=[],
                    help="portas cujo INA219 não responde")
    ap.add_argument("--corrente", type=float, default=1000.0,
                    help="mA nas portas plugadas, a 5 V (1000 mA = 5 W = 5 kW)")
    ap.add_argument("--ciclos", type=int, default=1)
    ap.add_argument("--intervalo", type=float, default=1.5)
    args = ap.parse_args()

    msg = montar_mensagem(set(args.plugadas), set(args.sem_sensor), args.corrente)
    for i in range(args.ciclos):
        try:
            codigo, corpo = enviar(args.url, args.token, msg)
        except (urllib.error.URLError, OSError) as erro:
            print(f"[{i + 1}] servidor inacessível: {erro}")
            return 1
        print(f"[{i + 1}] HTTP {codigo}  {corpo.strip()}")
        if i < args.ciclos - 1:
            time.sleep(args.intervalo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
