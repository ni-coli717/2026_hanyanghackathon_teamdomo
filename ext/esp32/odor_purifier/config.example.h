// config.example.h → 복사해서 config.h 로 저장하고 값만 채운다. config.h 는 git 에 올라가지 않는다.
#pragma once
#define WIFI_SSID      "집 와이파이 이름"
#define WIFI_PASS      "와이파이 비밀번호"
#define SUPABASE_URL   "https://xxxxxxxxxxxx.supabase.co"      // secrets.toml [database].url
#define SUPABASE_ANON  "sb_publishable_..."                    // secrets.toml [database].anon_key
#define DEVICE_ID      "..."                                   // secrets.toml [device].id
#define DEVICE_TOKEN   "..."                                   // secrets.toml [device].token
#define FW_VERSION     "esp32-purifier-1"
#define USE_LCD        0        // I2C 16x2 LCD(0x27) 를 달았으면 1
#define FAN_ACTIVE_LOW 0        // 릴레이/팬 모듈이 LOW 에서 도는 제품이면 1
