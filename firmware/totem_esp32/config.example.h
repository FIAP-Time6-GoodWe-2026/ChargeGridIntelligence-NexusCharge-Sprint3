// =============================================================================
//  Configuração local do totem ESP32.
//
//  1. Copie este arquivo para `config.h` (na mesma pasta do .ino).
//  2. Preencha os valores. O `config.h` NÃO vai para o Git (está no .gitignore),
//     porque guarda a senha do Wi-Fi e o token.
// =============================================================================
#pragma once

// Wi-Fi: o ESP32 só conecta em redes de 2,4 GHz.
// No iPhone: Ajustes > Ponto de Acesso Pessoal > "Maximizar compatibilidade".
#define WIFI_SSID  "NOME_DA_REDE"
#define WIFI_SENHA "SENHA_DA_REDE"

// Servidor Flask (o Mac). Use o IP que o `python app.py` mostra na linha "Rede".
// O IP pode mudar quando o hotspot reconecta: confira antes de cada teste.
#define SERVIDOR_IP    "172.20.10.2"
#define SERVIDOR_PORTA 5001

// Opcional: nome mDNS do Mac (sem ".local"), para o ESP32 descobrir o IP sozinho.
// Deixe "" para usar só o SERVIDOR_IP acima.
#define SERVIDOR_NOME_MDNS ""

// Deve ser igual à variável CHARGEGRID_ESP32_TOKEN do servidor.
// Sem a variável definida, o servidor aceita o token de desenvolvimento abaixo.
#define TOKEN_ESP32 "chargegrid-esp32-dev"
