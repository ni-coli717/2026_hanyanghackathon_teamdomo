/*
 * 냄새 나침반 — 실외 센서 노드 (ESP32 DevKit V1 30핀)
 *
 * 센서:  MQ-137(NH3, 아날로그 → 10k/20k 분압 → GPIO34)
 *        SGP40 (VOC index, I2C 0x59)   SHT31 (온습도, I2C 0x44)
 * 전송:  1분마다 Supabase REST(sensor_readings) 에 1행 INSERT. 실패 시 RAM 버퍼(최대 360건=6시간) 후 재전송.
 * 상태 LED(GPIO2): 켜짐=WiFi 연결, 1초 점멸=WiFi 끊김, 빠른 점멸=전송 실패 누적
 *
 * 라이브러리(Arduino IDE 라이브러리 관리자): Adafruit SHT31, Adafruit SGP40 (+ Adafruit BusIO), ArduinoJson 7
 * 보드: "ESP32 Dev Module", Upload speed 921600
 *
 * 원값만 보낸다. 지수·기준선·보정은 서버(odor_model/sensor_index.py)에서 계산한다.
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <time.h>
#include <ArduinoJson.h>
#include "Adafruit_SHT31.h"
#include "Adafruit_SGP40.h"
#include "config.h"

#define PIN_MQ      34      // ADC1_CH6 (WiFi 사용 중에도 읽힘). ADC2 핀은 쓰지 말 것
#define PIN_LED     2
#define PIN_SDA     21
#define PIN_SCL     22

static const uint32_t SAMPLE_MS   = 10000;   // 10초마다 샘플
static const uint8_t  SAMPLES_PER_ROW = 6;   // 6개 평균 = 1분
static const size_t   BUF_MAX     = 360;     // 6시간

Adafruit_SHT31 sht31;
Adafruit_SGP40 sgp40;
bool haveSht = false, haveSgp = false;

struct Row { time_t ts; uint16_t adc; int16_t voc; float rh; float tc; uint32_t heater; int8_t rssi; };
Row buf[BUF_MAX]; size_t bufN = 0;

uint32_t bootMs; uint32_t lastSample = 0; uint8_t nAcc = 0;
uint32_t accAdc = 0; int32_t accVoc = 0; float accRh = 0, accTc = 0; uint8_t nRh = 0, nVoc = 0;
uint16_t failStreak = 0;

void ledSet(bool on) { digitalWrite(PIN_LED, on ? HIGH : LOW); }

void wifiEnsure() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); ledSet(i & 1); }
  if (WiFi.status() == WL_CONNECTED) {
    configTime(9 * 3600, 0, "kr.pool.ntp.org", "time.google.com");   // KST
  }
}

bool timeValid() { return time(nullptr) > 1700000000; }

uint16_t readMq() {   // 20회 평균
  uint32_t s = 0; for (int i = 0; i < 20; i++) { s += analogRead(PIN_MQ); delay(2); } return s / 20;
}

void sample() {
  float rh = NAN, tc = NAN;
  if (haveSht) { tc = sht31.readTemperature(); rh = sht31.readHumidity(); }
  int32_t voc = -1;
  if (haveSgp) voc = (!isnan(rh) && !isnan(tc)) ? sgp40.measureVocIndex(tc, rh) : sgp40.measureVocIndex();
  accAdc += readMq();
  if (voc >= 0) { accVoc += voc; nVoc++; }
  if (!isnan(rh)) { accRh += rh; accTc += tc; nRh++; }
  nAcc++;
}

void pushRow() {
  Row r;
  r.ts = time(nullptr); r.adc = accAdc / max<uint8_t>(nAcc, 1);
  r.voc = nVoc ? accVoc / nVoc : -1; r.rh = nRh ? accRh / nRh : NAN; r.tc = nRh ? accTc / nRh : NAN;
  r.heater = (millis() - bootMs) / 1000; r.rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  accAdc = 0; accVoc = 0; accRh = 0; accTc = 0; nAcc = 0; nRh = 0; nVoc = 0;
  if (!timeValid()) return;                   // 시각 없으면 버림(NTP 전)
  if (bufN >= BUF_MAX) { memmove(buf, buf + 1, sizeof(Row) * (BUF_MAX - 1)); bufN = BUF_MAX - 1; }
  buf[bufN++] = r;
}

String isoKst(time_t t) {
  struct tm tmv; localtime_r(&t, &tmv); char s[32];
  strftime(s, sizeof s, "%Y-%m-%dT%H:%M:%S+09:00", &tmv); return String(s);
}

bool flush() {   // 버퍼 전체를 한 번에 INSERT (최대 60건씩)
  if (bufN == 0 || WiFi.status() != WL_CONNECTED) return false;
  size_t n = min(bufN, (size_t)60);
  JsonDocument doc; JsonArray arr = doc.to<JsonArray>();
  for (size_t i = 0; i < n; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["site_id"] = SITE_ID; o["ts"] = isoKst(buf[i].ts); o["adc_mq137"] = buf[i].adc;
    if (buf[i].voc >= 0) o["voc_index"] = buf[i].voc;
    if (!isnan(buf[i].rh)) { o["humidity_pct"] = buf[i].rh; o["temperature_c"] = buf[i].tc; }
    o["heater_sec"] = buf[i].heater; o["rssi"] = buf[i].rssi; o["fw_version"] = FW_VERSION;
  }
  String body; serializeJson(doc, body);
  WiFiClientSecure client; client.setInsecure();   // 인증서 고정은 생략(데이터는 공개 센서값)
  HTTPClient http; http.setTimeout(10000);
  http.begin(client, String(SUPABASE_URL) + "/rest/v1/sensor_readings");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("apikey", SUPABASE_ANON); http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON);
  http.addHeader("Prefer", "resolution=ignore-duplicates,return=minimal");
  int code = http.POST(body); http.end();
  if (code == 201 || code == 200) {
    memmove(buf, buf + n, sizeof(Row) * (bufN - n)); bufN -= n; failStreak = 0; return true;
  }
  failStreak++; Serial.printf("POST fail %d\n", code); return false;
}

void setup() {
  Serial.begin(115200); pinMode(PIN_LED, OUTPUT); bootMs = millis();
  analogReadResolution(12); analogSetPinAttenuation(PIN_MQ, ADC_11db);   // 0~3.3V
  Wire.begin(PIN_SDA, PIN_SCL);
  haveSht = sht31.begin(0x44); haveSgp = sgp40.begin();
  Serial.printf("SHT31 %d  SGP40 %d  site %s fw %s\n", haveSht, haveSgp, SITE_ID, FW_VERSION);
  wifiEnsure();
}

void loop() {
  wifiEnsure();
  uint32_t now = millis();
  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now; sample();
    if (nAcc >= SAMPLES_PER_ROW) { pushRow(); flush(); }
  }
  bool wifi = WiFi.status() == WL_CONNECTED;
  if (!wifi) ledSet((now / 500) & 1); else if (failStreak > 3) ledSet((now / 120) & 1); else ledSet(true);
  delay(50);
}
