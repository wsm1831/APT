# 내 아파트 실거래가 (MVP)

관심 아파트의 최근 10년 실거래가(매매, 전월세, 분양권)를 한 화면에서 보고, 현재 호가는 네이버 부동산으로 바로 이동해 확인하는 개인용 Streamlit 앱입니다.

## 매일 자동 수집 + 대시보드 (휴대폰용)

`collect.py`가 GitHub Actions에서 매일 오전 7시경 실행되어 보유 단지와 인근 단지의 **전용 84㎡ 매매·전세 실거래**를 모읍니다.

- 결과: `docs/data/market.json` → 대시보드 `docs/index.html`(GitHub Pages)에서 확인
- 새로 신고된 거래가 있으면 이슈를 만들어 GitHub 알림(앱·메일)을 보냅니다
- 인증키: 저장소 Settings → Secrets and variables → Actions에 `DATA_GO_KR_KEY`
- 대시보드 켜기: Settings → Pages → Branch를 `claude/apt-price-mvp`, 폴더 `/docs`로 저장
- 비교 단지: `complexes.json`의 `compare`에 직접 지정 (단지명이 실거래 자료와 안 맞으면 Actions 로그에 같은 동 단지명 목록이 경고로 나옵니다)
- 수동 실행: Actions → 실거래가 수집 → Run workflow

## 1. 인증키 발급 (최초 1회)

[공공데이터포털](https://www.data.go.kr)에 가입한 뒤 아래 3개 API에 **활용신청**을 합니다. 개발계정은 보통 바로 승인됩니다.

- 국토교통부_아파트 매매 실거래가 상세 자료
- 국토교통부_아파트 전월세 실거래가 자료
- 국토교통부_아파트 분양권전매 실거래가 자료

마이페이지에서 **일반 인증키(Decoding)** 를 복사합니다.

## 2. 실행

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 인증키 입력
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다. 인증키가 없으면 **샘플 데이터**(실제 거래 아님)로 화면만 보여줍니다.

첫 조회는 단지마다 API를 약 360번(120개월 × 3종) 호출하므로 1~2분 걸립니다. 결과는 `data/rtms.sqlite`에 저장되고, 이후에는 최근 3개월만 다시 받습니다.

## 3. 단지 추가/수정: `complexes.json`

| 필드 | 설명 |
|---|---|
| `lawd_cd` | 법정동코드 앞 5자리 (시군구). 대구 중구 27110, 동구 27140, 수성구 27260 |
| `umd` | 법정동 이름. 같은 구의 동명 단지를 걸러냅니다 |
| `keywords` | 실거래 데이터의 단지명(`aptNm`)에 포함되는 문자열. 띄어쓰기는 무시합니다 |
| `compare` | 비교 단지 목록 `[{"name": "더샵디어엘로", "lawd_cd": "27140", "umd": "신천동", "keywords": ["디어엘로"]}]`. 남구는 27200 |
| `naver_complex_id` | 네이버 부동산 단지 번호. 네이버 부동산에서 단지를 열었을 때 주소의 `/complexes/숫자` 부분. 비워 두면 검색 결과로 연결됩니다 |

## 구성

- `rtms.py`: API 호출, XML 파싱, SQLite 캐시, 단지 필터
- `app.py`: Streamlit 화면 (단지 상세, 단지 비교)
- `collect.py`, `.github/workflows/collect.yml`: 매일 자동 수집과 새 거래 알림
- `docs/index.html`: 휴대폰용 정적 대시보드
- `sample_data.py`: 인증키 없을 때 쓰는 합성 데이터
- `tests/`: 파서와 필터 테스트 (`python -m pytest`)
