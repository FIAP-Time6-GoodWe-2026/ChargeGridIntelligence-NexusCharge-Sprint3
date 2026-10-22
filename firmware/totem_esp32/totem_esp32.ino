// =============================================================================
//  TOTEM EV — ESP32 + ChargeGrid Intelligence (homologação, Fase 1)
//
//  Lê corrente e tensão das 3 portas (INA219, I2C chaveado por software) e
//  envia o estado ao servidor Flask por HTTP/JSON a cada ciclo. O servidor
//  calcula a potência (W medido = kW na aplicação) e decide a presença. O semáforo (LEDs)
//  segue a cor que o servidor devolve para o posto da Paulista (ocupação real
//  do posto na aplicação). Sem resposta do servidor, usa a regra local pelos
//  carros detectados nas 3 portas.
//
//  Mapeamento: porta 1 -> P1-C1, porta 2 -> P1-C2, porta 3 -> P1-C3
//  (o totem simula fisicamente o posto da Paulista).
//
//  Bibliotecas: Adafruit INA219 (+ Adafruit BusIO). WiFi, HTTPClient, ESPmDNS
//  e Wire já vêm com o pacote da placa ESP32.
// =============================================================================

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ESPmDNS.h>
#include <Adafruit_INA219.h>

#include "config.h"   // copie de config.example.h

#define FIRMWARE_VERSAO "0.3.0"

// --- Pinagem (a mesma do protótipo de bancada) --------------------------------
#define PIN_LED_RED    25
#define PIN_LED_YELLOW 26
#define PIN_LED_GREEN  27

const int TOTAL_PORTAS = 3;
const int PINOS_SDA[TOTAL_PORTAS] = {21, 18, 32};
const int PINOS_SCL[TOTAL_PORTAS] = {22, 19, 33};

// Corrente mínima para considerar um dispositivo plugado. Só vale para o
// semáforo offline: o servidor decide a presença pelo próprio limiar.
const float LIMIAR_PRESENCA_MA = 20.0;

// Intervalos
const unsigned long INTERVALO_CICLO_MS     = 1500;
const unsigned long TIMEOUT_HTTP_MS        = 2000;
const unsigned long TENTATIVA_WIFI_MS      = 10000;

Adafruit_INA219 ina[TOTAL_PORTAS];
bool inaOk[TOTAL_PORTAS] = {false, false, false};

IPAddress servidorMdns;           // preenchido se SERVIDOR_NOME_MDNS estiver em uso
bool servidorMdnsResolvido = false;

// --- Semáforo -------------------------------------------------------------------
// Cor decidida pelo servidor (ocupação do posto). Fallback local, na escala da
// aplicação (11 kW por carro, posto de 33 kW): 0-1 carro verde, 2 amarelo, 3 vermelho.
String corServidor = "";   // "verde" | "amarelo" | "vermelho" | "" (sem resposta)

void acenderSemaforo(const String &cor) {
  digitalWrite(PIN_LED_GREEN,  cor == "verde"    ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, cor == "amarelo"  ? HIGH : LOW);
  digitalWrite(PIN_LED_RED,    cor == "vermelho" ? HIGH : LOW);
}

String corLocal(int veiculos) {
  if (veiculos >= 3) return "vermelho";
  if (veiculos == 2) return "amarelo";
  return "verde";
}

// Extrai o valor de "semaforo":"..." da resposta JSON do servidor.
String extrairSemaforo(const String &corpo) {
  int i = corpo.indexOf("\"semaforo\"");
  if (i < 0) return "";
  int a = corpo.indexOf('"', corpo.indexOf(':', i) + 1);
  int b = (a < 0) ? -1 : corpo.indexOf('"', a + 1);
  if (a < 0 || b < 0) return "";
  String cor = corpo.substring(a + 1, b);
  return (cor == "verde" || cor == "amarelo" || cor == "vermelho") ? cor : "";
}

// --- I2C chaveado: cada porta tem o seu par de pinos ------------------------------
bool iniciarSensor(int i) {
  Wire.begin(PINOS_SDA[i], PINOS_SCL[i]);
  bool ok = ina[i].begin(&Wire);
  Wire.end();
  return ok;
}

// Lê corrente e tensão da porta `i`. Devolve false se o sensor não está disponível.
bool lerPorta(int i, float &corrente_ma, float &tensao_v) {
  if (!inaOk[i]) {
    // Sensor ausente na partida (fio solto, módulo desligado): tenta de novo.
    inaOk[i] = iniciarSensor(i);
    if (!inaOk[i]) return false;
  }
  Wire.begin(PINOS_SDA[i], PINOS_SCL[i]);
  corrente_ma = ina[i].getCurrent_mA();
  tensao_v = ina[i].getBusVoltage_V();
  Wire.end();
  return true;
}

// --- Wi-Fi ------------------------------------------------------------------------
void conectarWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Conectando ao Wi-Fi \"%s\"...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < TENTATIVA_WIFI_MS) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("Wi-Fi OK. IP do ESP32: %s\n", WiFi.localIP().toString().c_str());
    servidorMdnsResolvido = false;  // refaz a descoberta numa rede nova
  } else {
    Serial.println("Wi-Fi indisponível; nova tentativa no próximo ciclo.");
  }
}

// Endereço do servidor: mDNS se configurado e resolvido, senão o IP fixo.
String enderecoServidor() {
  String nome = SERVIDOR_NOME_MDNS;
  if (nome.length() > 0) {
    if (!servidorMdnsResolvido) {
      if (!MDNS.begin("totem-esp32")) { /* segue com o IP fixo */ }
      IPAddress ip = MDNS.queryHost(nome.c_str(), 2000);
      if ((uint32_t)ip != 0) {
        servidorMdns = ip;
        servidorMdnsResolvido = true;
        Serial.printf("mDNS: %s.local = %s\n", nome.c_str(), ip.toString().c_str());
      }
    }
    if (servidorMdnsResolvido) return servidorMdns.toString();
  }
  return String(SERVIDOR_IP);
}

// --- Envio ------------------------------------------------------------------------
// Monta o JSON à mão (sem biblioteca extra). Formato em esp32.py (servidor).
int enviarEstado(const float corrente[], const float tensao[], const bool presente[],
                 const bool leituraOk[]) {
  String json = "{\"fw\":\"" FIRMWARE_VERSAO "\",\"portas\":[";
  for (int i = 0; i < TOTAL_PORTAS; i++) {
    if (i > 0) json += ",";
    json += "{\"porta\":" + String(i + 1);
    json += ",\"corrente_ma\":" + String(corrente[i], 1);
    json += ",\"tensao_v\":" + String(tensao[i], 2);
    json += ",\"presente\":" + String(presente[i] ? "true" : "false");
    json += ",\"leitura_ok\":" + String(leituraOk[i] ? "true" : "false") + "}";
  }
  json += "]}";

  String url = "http://" + enderecoServidor() + ":" + String(SERVIDOR_PORTA) + "/api/esp32/portas";
  HTTPClient http;
  http.setTimeout(TIMEOUT_HTTP_MS);
  if (!http.begin(url)) return -1;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-ESP32-Token", TOKEN_ESP32);
  int codigo = http.POST(json);
  corServidor = (codigo == 200) ? extrairSemaforo(http.getString()) : "";
  http.end();
  return codigo;
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  acenderSemaforo("verde");

  Serial.println("\n==================================================");
  Serial.println("  TOTEM EV - ESP32 + ChargeGrid (Fase 3) v" FIRMWARE_VERSAO);
  Serial.println("==================================================");

  for (int i = 0; i < TOTAL_PORTAS; i++) {
    inaOk[i] = iniciarSensor(i);
    if (!inaOk[i]) {
      Serial.printf("ALERTA: INA%d nao respondeu no GPIO %d/%d\n",
                    i + 1, PINOS_SDA[i], PINOS_SCL[i]);
    }
  }

  conectarWifi();
}

void loop() {
  float corrente[TOTAL_PORTAS] = {0, 0, 0};
  float tensao[TOTAL_PORTAS]   = {0, 0, 0};
  bool presente[TOTAL_PORTAS]  = {false, false, false};
  bool leituraOk[TOTAL_PORTAS] = {false, false, false};
  int veiculos = 0;

  for (int i = 0; i < TOTAL_PORTAS; i++) {
    leituraOk[i] = lerPorta(i, corrente[i], tensao[i]);
    if (!leituraOk[i]) { corrente[i] = 0.0; tensao[i] = 0.0; }
    // O ruído do sensor oscila em torno de zero (-0,4 a +0,3 mA): corrente
    // negativa não existe para o carregador, então vira 0.
    if (leituraOk[i] && corrente[i] < 0) corrente[i] = 0.0;
    presente[i] = leituraOk[i] && corrente[i] >= LIMIAR_PRESENCA_MA;
    if (presente[i]) veiculos++;
  }

  // Painel resumido no Serial
  for (int i = 0; i < TOTAL_PORTAS; i++) {
    Serial.printf("[porta%d %s %.1f mA %.2f V %.2f W] ", i + 1,
                  !leituraOk[i] ? "SEM-SENSOR" : (presente[i] ? "PLUGADA" : "livre"),
                  corrente[i], tensao[i], corrente[i] * tensao[i] / 1000.0);
  }
  Serial.print("| ");

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("sem Wi-Fi");
    corServidor = "";   // sem servidor: volta à regra local
    conectarWifi();
  } else {
    int codigo = enviarEstado(corrente, tensao, presente, leituraOk);
    if (codigo == 200)      Serial.printf("servidor OK | semaforo %s\n", corServidor.length() ? corServidor.c_str() : "(sem cor)");
    else if (codigo == 401) Serial.println("servidor recusou o token (401)");
    else if (codigo == 400) Serial.println("servidor recusou a mensagem (400)");
    else                    Serial.printf("falha no envio (codigo %d)\n", codigo);
  }

  // LEDs: cor do servidor; sem ela (offline, erro), regra local.
  acenderSemaforo(corServidor.length() ? corServidor : corLocal(veiculos));

  delay(INTERVALO_CICLO_MS);
}
