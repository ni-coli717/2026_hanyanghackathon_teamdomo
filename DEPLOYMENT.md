# Streamlit Community Cloud 배포 체크리스트

## GitHub에 올리기

GitHub에서 빈 저장소(권장 이름: `odor-compass`)를 만든 뒤 이 폴더에서 실행합니다.

```powershell
git remote add origin https://github.com/YOUR_ID/odor-compass.git
git push -u origin main
```

GitHub가 비밀번호를 요구하면 일반 비밀번호가 아니라 브라우저 로그인 또는 Personal Access Token을 사용합니다.

## Streamlit에 연결하기

1. <https://share.streamlit.io> 접속
2. GitHub 로그인 및 저장소 접근 승인
3. **Create app → Yup, I have an app**
4. Repository: `YOUR_ID/odor-compass`
5. Branch: `main`
6. Main file path: `app.py`
7. Advanced settings → Python `3.11`
8. Deploy

배포 후 `https://원하는이름.streamlit.app` 주소를 공유할 수 있습니다.

## 현재 배포 특성

- 공개 샘플 시연: 가능
- AI 학습/재학습: 가능하나 컨테이너 재시작 시 모델 파일 초기화 가능
- 주민 기록: 실행 중에는 가능하나 SQLite가 영구 저장되지 않음
- Arduino: 클라우드에서는 USB 포트가 없어 자동 시뮬레이션
- 장기 주민 수집: `Repository`의 Supabase/Postgres 구현이 필요

