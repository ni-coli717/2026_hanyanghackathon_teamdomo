/*
  냄새 나침반 — 공기청정기 모듈 (ESP32 DevKit V1 30핀, Wi-Fi 직결판)
  PC 브리지 없이 보드가 Supabase device_get / device_report / device_set 을 직접 호출한다.

  배선 (Uno 판과 같은 역할, 핀만 다름)
    GPIO26  팬 제어 (릴레이 모듈 IN 또는 팬 모듈 신호)   ※ 팬 전원은 보드 5V 가 아니라 별도 전원에서
    GPIO27  초록 LED (가동)   + 220Ω
    GPIO25  빨간 LED (대기)   + 220Ω
    GPIO33  택트 스위치 (다른 쪽은 GND, INPUT_PULLUP)
    GPIO2   보드 내장 LED = 팬 상태 미러 (부품 없이도 동작 확인용)
    GPIO21/22  I2C LCD (선택, USE_LCD 1)
    ※ 0, 2, 12, 15 는 부팅 스트랩 핀이라 입력에 쓰지 않는다. 34~39 는 풀업이 없다.

  동작
    - POLL_MS 마다 device_get → command(ON/OFF/HOLD) 그대로 따른다. 보드는 풍향을 보고 판단하지 않는다.
    - HOLD 면 직전 상태 유지. LINK_TIMEOUT 동안 서버 응답이 없으면 팬을 끄고 NO SIGNAL.
    - 버튼 짧게: 수동 켜기/끄기 → device_set(mode on/off, 2시간). 서버가 같은 값을 돌려주므로 앱에도 '수동'이 보인다.
      서버에 못 보내면 보드에서만 바꾸고 다음 폴링 때 서버 값으로 돌아간다.
    - 버튼 길게(0.8초): 냄새 신고 → device_report note='button:smell' (device_status.note 에 남는다)
    - 상태 변화 때와 60초마다 device_report(fan, mode, fw, rssi).

  라이브러리(Arduino IDE 라이브러리 관리자): ArduinoJson 7, (USE_LCD 면) LiquidCrystal I2C
  보드: "ESP32 Dev Module", Upload speed 921600
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"
#if USE_LCD
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
LiquidCrystal_I2C lcd(0x27, 16, 2);
#endif

#define PIN_FAN    26
#define PIN_GREEN  27
#define PIN_RED    25
#define PIN_BTN    33
#define PIN_BOARD  2

static const uint32_t POLL_MS       = 20000;
static const uint32_t REPORT_MS     = 60000;
static const uint32_t LINK_TIMEOUT  = 5UL * 60 * 1000;   // 5분 무응답 → 안전 정지
static const uint32_t LONG_PRESS_MS = 800;
static const uint32_t DEBOUNCE_MS   = 50;
static const uint32_t PAGE_MS       = 5000;

bool   fanOn = false, linkAlive = false, manualMode = false;
String command = "HOLD", level = "HOLD", wind = "NA", basis = "FCST";
uint32_t lastPoll = 0, lastOk = 0, lastReport = 0, lastPage = 0;
bool reportedFan = false; String reportedMode = "";
int  lcdPage = 0;

int  btnState = HIGH, btnLast = HIGH; uint32_t btnChanged = 0, pressStart = 0; bool pressHandled = false;

/* ---------------- 출력 ---------------- */
void applyState() {
  digitalWrite(PIN_FAN, (fanOn != (bool)FAN_ACTIVE_LOW) ? HIGH : LOW);
  digitalWrite(PIN_GREEN, fanOn ? HIGH : LOW);
  digitalWrite(PIN_RED,   fanOn ? LOW  : HIGH);
  digitalWrite(PIN_BOARD, fanOn ? HIGH : LOW);
  drawPage();
}

void drawPage() {
#if USE_LCD
  lcd.clear();
  if (!linkAlive && !manualMode) {
    lcd.setCursor(0, 0); lcd.print("NO SIGNAL");
    lcd.setCursor(0, 1); lcd.print(WiFi.status() == WL_CONNECTED ? "CHECK SERVER" : "CHECK WIFI");
    return;
  }
  if (lcdPage == 0) {
    lcd.setCursor(0, 0); lcd.print("WIND FROM:"); lcd.print(wind);
    lcd.setCursor(0, 1); lcd.print("EST:"); lcd.print(level);
    lcd.setCursor(11, 1); lcd.print(manualMode ? "MANUAL" : basis);
  } else if (fanOn) {
    lcd.setCursor(0, 0); lcd.print(manualMode ? "MANUAL RUN" : "ODOR INFLOW EST");
    lcd.setCursor(0, 1); lcd.print("PURIFYING AIR");
  } else if (level == "HOLD") {
    lcd.setCursor(0, 0); lcd.print("NO ESTIMATE");
    lcd.setCursor(0, 1); lcd.print("DATA HOLD");
  } else {
    lcd.setCursor(0, 0); lcd.print("AIRFLOW: "); lcd.print(wind);
    lcd.setCursor(0, 1); lcd.print("SYSTEM: STANDBY");
  }
#endif
}

/* ---------------- 네트워크 ---------------- */
void wifiEnsure() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); digitalWrite(PIN_BOARD, i & 1); }
  Serial.printf("wifi %s\n", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "FAIL");
}

// Supabase RPC 호출. 성공하면 true, 응답 본문은 out 에.
bool rpc(const char* name, JsonDocument& body, String& out) {
  if (WiFi.status() != WL_CONNECTED) return false;
  body["p_device"] = DEVICE_ID; body["p_token"] = DEVICE_TOKEN;
  String payload; serializeJson(body, payload);
  WiFiClientSecure client; client.setInsecure();   // 시연용. 상용이면 Supabase 루트 CA 를 setCACert 로 고정할 것
  HTTPClient http; http.setTimeout(10000);
  http.begin(client, String(SUPABASE_URL) + "/rest/v1/rpc/" + name);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("apikey", SUPABASE_ANON);
  if (String(SUPABASE_ANON).startsWith("eyJ")) http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON);
  int code = http.POST(payload);
  out = (code > 0) ? http.getString() : "";
  http.end();
  if (code < 200 || code >= 300) { Serial.printf("%s fail %d %s\n", name, code, out.substring(0, 80).c_str()); return false; }
  return true;
}

void poll() {
  JsonDocument body; String out;
  if (!rpc("device_get", body, out)) return;
  JsonDocument doc;
  if (deserializeJson(doc, out)) { Serial.println("json fail"); return; }
  lastOk = millis(); linkAlive = true;
  command = doc["command"] | "HOLD";
  const char* mode = doc["settings"]["mode"] | "auto";
  manualMode = strcmp(mode, "auto") != 0;
  JsonObject plan = doc["plan"];
  if (!plan.isNull()) {
    const char* b = plan["basis"] | "";
    basis = (strcmp(b, "demo") == 0) ? "DEMO" : "FCST";
    JsonArray eps = plan["episodes"];
    level = "LOW"; wind = "NA";
    if (!eps.isNull() && eps.size() > 0) {
      level = eps[0]["peak_level"] | "LOW";
      wind  = eps[0]["wind_sector"] | "NA";
      if (level == "높음") level = "HIGH"; else if (level == "보통") level = "MID"; else if (level == "낮음") level = "LOW";
    }
    const char* st = plan["state"] | "";
    if (strcmp(st, "hold") == 0) level = "HOLD";
  } else { level = "HOLD"; }
  bool before = fanOn;
  if (command == "ON") fanOn = true; else if (command == "OFF") fanOn = false;   // HOLD 면 유지
  Serial.printf("get command=%s source=%s mode=%s level=%s wind=%s\n", command.c_str(),
                (const char*)(doc["source"] | "?"), mode, level.c_str(), wind.c_str());
  if (before != fanOn) applyState(); else drawPage();
}

void report(const char* note) {
  JsonDocument body; String out;
  body["p_fan"] = fanOn; body["p_mode"] = manualMode ? "manual" : "auto";
  body["p_fw"] = FW_VERSION; body["p_rssi"] = WiFi.RSSI();
  if (note) body["p_note"] = note;
  if (rpc("device_report", body, out)) { reportedFan = fanOn; reportedMode = manualMode ? "manual" : "auto"; lastReport = millis(); }
}

void setManual(bool on) {
  JsonDocument body; String out;
  body["p_mode"] = on ? "on" : "off";
  if (rpc("device_set", body, out)) { Serial.printf("manual %s sent\n", on ? "on" : "off"); lastPoll = 0; }   // 바로 다시 읽기
}

/* ---------------- 버튼 ---------------- */
void readButton() {
  int reading = digitalRead(PIN_BTN);
  if (reading != btnLast) { btnChanged = millis(); btnLast = reading; }
  if (millis() - btnChanged > DEBOUNCE_MS && reading != btnState) {
    btnState = reading;
    if (btnState == LOW) { pressStart = millis(); pressHandled = false; }
    else if (!pressHandled) {                 // 짧게 누름 = 수동 토글
      fanOn = !fanOn; manualMode = true; applyState();
      setManual(fanOn); report(fanOn ? "button:on" : "button:off");
      pressHandled = true;
    }
  }
  if (btnState == LOW && !pressHandled && millis() - pressStart > LONG_PRESS_MS) {   // 길게 = 냄새 신고
    report("button:smell"); pressHandled = true;
#if USE_LCD
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("REPORT SENT"); lcd.setCursor(0, 1); lcd.print("THANK YOU");
    lastPage = millis();
#endif
    Serial.println("smell reported");
  }
}

/* ---------------- 메인 ---------------- */
void setup() {
  Serial.begin(115200);
  digitalWrite(PIN_FAN, FAN_ACTIVE_LOW ? HIGH : LOW); pinMode(PIN_FAN, OUTPUT); digitalWrite(PIN_FAN, FAN_ACTIVE_LOW ? HIGH : LOW);
  pinMode(PIN_GREEN, OUTPUT); pinMode(PIN_RED, OUTPUT); pinMode(PIN_BOARD, OUTPUT); pinMode(PIN_BTN, INPUT_PULLUP);
#if USE_LCD
  Wire.begin(21, 22); lcd.init(); lcd.backlight();
#endif
  applyState();
  wifiEnsure();
  Serial.printf("odor purifier %s device %s\n", FW_VERSION, DEVICE_ID);
}

void loop() {
  wifiEnsure();
  readButton();
  uint32_t now = millis();
  if (now - lastPoll >= POLL_MS) { lastPoll = now; poll(); }
  if (linkAlive && now - lastOk > LINK_TIMEOUT) {        // 서버 무응답 → 안전 정지
    linkAlive = false;
    if (!manualMode) { fanOn = false; level = "HOLD"; }
    Serial.println("NO SIGNAL");
    applyState();
  }
  if (linkAlive && (fanOn != reportedFan || reportedMode != (manualMode ? "manual" : "auto") || now - lastReport >= REPORT_MS)) report(nullptr);
  if (now - lastPage >= PAGE_MS) { lastPage = now; lcdPage ^= 1; drawPage(); }
  delay(20);
}
