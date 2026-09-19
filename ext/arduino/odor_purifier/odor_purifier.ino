/*
  냄새 나침반 — 공기질 관리 모듈 (Arduino Uno R3)
  웹앱(Streamlit) ↔ USB 시리얼 연동판

  배선 (기존 유지)
    D7  택트 스위치 (INPUT_PULLUP)
    D9  빨간 LED  (대기)
    D11 팬 제어 모듈 (LOW=회전, HIGH=정지 / 액티브 로우 모듈 기준)
    D12 초록 LED (가동)
    I2C 16x2 LCD (0x27)

  프로토콜 (Python → Arduino, 1줄)
    ODOR|<WIND>|<LEVEL>|<ACTION>|<BASIS>
      WIND   : N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW / CALM / NA
      LEVEL  : LOW MID HIGH HOLD      (HOLD = 자료 없음·추정 보류)
      ACTION : ON OFF HOLD            (제어 규칙이 결정. 보드는 판단하지 않는다)
      BASIS  : OBS EST DEMO FCST      (관측/추정/시연/예보)
    예) ODOR|ENE|HIGH|ON|FCST
    PING                              (5초 주기 하트비트)

  프로토콜 (Arduino → Python, 1줄)
    ACK|<LEVEL>|<ACTION>|<MODE>       MODE = AUTO / MANUAL
    REPORT|SMELL                      주민이 버튼을 길게 눌러 '냄새 남'을 신고
    OVERRIDE|ON  /  OVERRIDE|OFF      버튼 짧게 눌러 수동 켜기·끄기

  안전 규칙
    - 보드는 스스로 풍향을 보고 판단하지 않는다. ACTION 값만 따른다.
    - LINK_TIMEOUT 동안 수신이 없으면 팬을 끄고 NO SIGNAL을 표시한다.
    - LEVEL=HOLD는 '냄새 없음'이 아니라 '판단 보류'로 표시한다.
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C lcd(0x27, 16, 2);

const int RED_LED    = 9;
const int GREEN_LED  = 12;
const int FAN_PIN    = 11;
const int SWITCH_PIN = 7;

const int  RED_BRIGHTNESS   = 10;
const bool FAN_ACTIVE_LOW   = true;          // 모듈이 HIGH에서 도는 제품이면 false
const unsigned long LINK_TIMEOUT   = 15000;  // 수신 없음 판정
const unsigned long LONG_PRESS_MS  = 800;    // 길게 누르면 냄새 신고
const unsigned long DEBOUNCE_MS    = 50;
const unsigned long PAGE_MS        = 5000;
const unsigned long DOT_MS         = 500;

bool   fanOn        = false;
bool   manualMode   = false;   // 수동 조작 중이면 자동 명령 무시
bool   linkAlive    = false;
String windDir      = "NA";
String riskLevel    = "HOLD";
String basis        = "DEMO";

unsigned long lastRxTime   = 0;
unsigned long lastPage     = 0;
unsigned long lastDot      = 0;
int  lcdPage = 0, dotCount = 0;

int  swState = HIGH, swLast = HIGH;
unsigned long swChanged = 0, pressStart = 0;
bool pressHandled = false;

String rxBuf = "";

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(20);

  // 팬 글리치 방지: 핀을 출력으로 바꾸기 전에 정지 레벨을 먼저 써 둔다.
  digitalWrite(FAN_PIN, FAN_ACTIVE_LOW ? HIGH : LOW);
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, FAN_ACTIVE_LOW ? HIGH : LOW);

  pinMode(RED_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(SWITCH_PIN, INPUT_PULLUP);

  lcd.init();
  lcd.backlight();
  applyState();
}

void loop() {
  readSerial();
  readButton();

  if (linkAlive && millis() - lastRxTime > LINK_TIMEOUT) {   // 통신 끊김 → 안전 정지
    linkAlive = false;
    if (!manualMode) { fanOn = false; riskLevel = "HOLD"; }
    applyState();
  }

  if (millis() - lastPage > PAGE_MS) {
    lcdPage = (lcdPage + 1) % 2;
    drawPage();
    lastPage = millis();
  }

  if (fanOn && lcdPage == 1 && millis() - lastDot > DOT_MS) {
    dotCount = (dotCount + 1) % 4;
    drawDots();
    lastDot = millis();
  }
}

/* ---------------- 시리얼 수신 (논블로킹) ---------------- */
void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (rxBuf.length() > 0) { handleLine(rxBuf); rxBuf = ""; }
    } else if (rxBuf.length() < 60) {
      rxBuf += c;
    }
  }
}

void handleLine(String line) {
  line.trim();
  line.toUpperCase();
  lastRxTime = millis();
  linkAlive  = true;

  if (line == "PING") { sendAck(); return; }
  if (line.startsWith("MODE|AUTO")) { manualMode = false; applyState(); return; }

  if (!line.startsWith("ODOR|")) return;

  String f[4]; int idx = 0, from = 5;
  while (idx < 4) {
    int p = line.indexOf('|', from);
    f[idx++] = (p == -1) ? line.substring(from) : line.substring(from, p);
    if (p == -1) break;
    from = p + 1;
  }
  if (f[0].length()) windDir   = f[0];
  if (f[1].length()) riskLevel = f[1];
  if (f[3].length()) basis     = f[3];

  if (!manualMode) {                       // 수동 조작 중이면 자동 명령을 덮어쓰지 않는다
    if (f[2] == "ON")       fanOn = true;
    else if (f[2] == "OFF") fanOn = false;
    // HOLD면 직전 상태 유지
  }
  applyState();
  sendAck();
}

void sendAck() {
  Serial.print("ACK|"); Serial.print(riskLevel);
  Serial.print("|");    Serial.print(fanOn ? "ON" : "OFF");
  Serial.print("|");    Serial.println(manualMode ? "MANUAL" : "AUTO");
}

/* ---------------- 버튼: 짧게=수동 토글, 길게=냄새 신고 ---------------- */
void readButton() {
  int reading = digitalRead(SWITCH_PIN);
  if (reading != swLast) { swChanged = millis(); swLast = reading; }

  if (millis() - swChanged > DEBOUNCE_MS && reading != swState) {
    swState = reading;
    if (swState == LOW) { pressStart = millis(); pressHandled = false; }
    else if (!pressHandled) {                      // 뗐을 때 = 짧게 누름
      manualMode = true;
      fanOn = !fanOn;
      Serial.println(fanOn ? "OVERRIDE|ON" : "OVERRIDE|OFF");
      applyState();
      pressHandled = true;
    }
  }

  if (swState == LOW && !pressHandled && millis() - pressStart > LONG_PRESS_MS) {
    Serial.println("REPORT|SMELL");              // 주민 신고를 웹앱으로 올림
    pressHandled = true;
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("REPORT SENT");
    lcd.setCursor(0, 1); lcd.print("THANK YOU");
    lastPage = millis();
  }
}

/* ---------------- 출력 ---------------- */
void applyState() {
  digitalWrite(FAN_PIN, (fanOn == FAN_ACTIVE_LOW) ? LOW : HIGH);
  if (fanOn) { analogWrite(RED_LED, 0);               digitalWrite(GREEN_LED, HIGH); }
  else       { analogWrite(RED_LED, RED_BRIGHTNESS);  digitalWrite(GREEN_LED, LOW);  }
  drawPage();
}

void drawPage() {
  lcd.clear();
  if (!linkAlive && !manualMode) {                 // 통신 없음 = 판단 불가
    lcd.setCursor(0, 0); lcd.print("NO SIGNAL");
    lcd.setCursor(0, 1); lcd.print("CHECK USB LINK");
    return;
  }
  if (lcdPage == 0) {
    lcd.setCursor(0, 0);
    lcd.print("WIND FROM:"); lcd.print(windDir);
    lcd.setCursor(0, 1);
    lcd.print("EST:"); lcd.print(riskLevel);
    lcd.setCursor(11, 1); lcd.print(manualMode ? "MANUAL" : basis);
  } else {
    if (fanOn) {
      lcd.setCursor(0, 0); lcd.print(manualMode ? "MANUAL RUN" : "ODOR INFLOW EST");
      lcd.setCursor(0, 1); lcd.print("PURIFYING AIR");
      drawDots();
    } else if (riskLevel == "HOLD") {
      lcd.setCursor(0, 0); lcd.print("NO ESTIMATE");
      lcd.setCursor(0, 1); lcd.print("DATA HOLD");
    } else {
      lcd.setCursor(0, 0); lcd.print("AIRFLOW: "); lcd.print(windDir);
      lcd.setCursor(0, 1); lcd.print("SYSTEM: STANDBY");
    }
  }
}

void drawDots() {
  lcd.setCursor(13, 1);
  if      (dotCount == 0) lcd.print("   ");
  else if (dotCount == 1) lcd.print(".  ");
  else if (dotCount == 2) lcd.print(".. ");
  else                    lcd.print("...");
}
