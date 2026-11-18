# agbot v3: 토마토 재배 의사결정지원 — RAG vs MCP 판정 비교

한국생물환경조절학회 포스터 연구용 시스템이다. 연구 제목은 "다중 출처 농업 데이터를 연계한 MCP 기반 LLM 의사결정지원시스템 개발"이다.
상세 명세는 [`mcp_agri_dss_spec.md`](mcp_agri_dss_spec.md)에 있다.

같은 질문, 같은 농장 상황, 같은 문서를 주고 판정 방식만 달리해서 비교한다.

| 조건 | 현재 상황 값 | 문서 | 판정 주체 | LLM 역할 |
|---|---|---|---|---|
| **RAG** | 프롬프트의 `[현재 상황]` 텍스트 | 벡터 검색 상위 5개 문단 | LLM | 문서 해석, 판정, 계산, 설명 |
| **MCP** | 조회 도구 `get_*` | `search_guideline` 도구 | Python 규칙 도구 | 도구 선택, 값 전달, 결과 설명 |

## 범위

관수는 제외했다. 다루는 영역은 5개이고, 영역마다 시나리오가 5개씩 총 25개다.

| 재배 | 영역 | 판정 도구 | 근거 문서 |
|---|---|---|---|
| 시설(양액) | 환경제어 | `climate_control_decision` | JEJU-TOMATO, RDA-WEATHER-2025 |
| 시설(양액) | 양액관리 | `nutrient_decision` | MOON-2018 (급액 EC 1.2~1.5, pH 5.8~6.0), JEJU-TOMATO |
| 노지 | 시비 | `fertilizer_schedule` | JEJU-TOMATO (흙토람 처방 → 제품량 환산, 웃거름 시기) |
| 노지 | 기상대응 | `weather_risk_decision` | JEJU-TOMATO, RDA-WEATHER-2025 |
| 공통 | 작업관리 | `task_decision` | JEJU-TOMATO (적심, 착과제, 수확) |

- 시설 작형(촉성, 반촉성, 억제, 노지)은 입력값으로 받는다.
- 문서에 기준이 없는 경우(예: 촉성 적심 단수)는 `no_rule`로 판정을 보류한다.

## 구조

```
agbot/
  config.py       모델·경로 설정, API 키 로딩
  data.py         스냅샷 로더, 시나리오 로더 (DEMO = 실제 수집 자료)
  docs.py         문서 검색 (Chroma + OpenAI 임베딩 / Mock은 키워드)
  rules.py        판정 규칙 엔진 (명세 5.3 출력 형식)
  mcp_server.py   MCP 서버: 조회 7개 + 판정 5개 도구
  llm.py          OpenAI Responses 호출, 공통 응답 스키마, Mock 모델
  chat.py         ask(질문, 시나리오, condition="rag"|"mcp")
knowledge/
  rules.yaml      규칙표 (rule_id ↔ doc_id·원문 clause·임계값·경계 처리)
  chunks.jsonl    RAG 문서 137개 문단 (PDF 추출 + 표 3개는 사람이 텍스트로 정리)
  curated.jsonl   사람이 정리한 표 문단
  chroma/         벡터DB (build_index.py로 생성, git 제외)
scenarios/        시나리오 25개 (영역별 JSON)
scripts/          build_chunks.py, build_index.py
experiment/       run.py → judge.py → plot.py
archive/          v1(이전 연구 코드)·v2(조회 전달 비교) 보관
```

## 외부 API 연결

MCP의 **조회 도구**가 농장의 현재 상황을 가져오고, **판정 도구**가 그 값을 문헌 기준과 비교한다. API는 조회 도구 쪽에 연결된다.

| API | 인증 | 조회 도구 | 이어지는 판정 |
|---|---|---|---|
| 흙토람 비료사용처방 | `FERTILIZER_API_KEY` | `get_fertilizer_prescription` (노지 토마토 04016) | `fertilizer_schedule` |
| 스마트팜 빅데이터 데이터마트 | `SMARTFARM_API_KEY` | `get_greenhouse_env` (하우스 온도·습도) | `climate_control_decision` |
| 기상 (weather-rda.digitalag.kr) | 주소만 필요 | `get_weather` (실황 + 내일 최저·최고·평균기온, 강수) | `weather_risk_decision`, 착과제 농도, 외기온 |
| OpenAI | `OPENAI_API_KEY` | LLM 응답 생성, 문서 임베딩 | 두 조건 공통 |

- **키 위치**: 환경 변수, 루트 `.env`, 루트 `API_key.txt` 순서로 찾는다.
  - `API_key.txt`에서는 제목줄(비료 / 스마트팜) 아래의 `인증키:` 줄을 해당 서비스 키로 읽는다.
  - `API_key.txt`는 git에서 제외되어 있다.
- **시나리오별 조회 방식**
  - `--scenario LIVE`: 조회 도구가 불릴 때 해당 API를 실시간으로 호출한다. 조회 대상은 `config.LIVE_FARM`이다.
  - `--scenario DEMO`: 저장해 둔 실제 자료 스냅샷을 쓴다.
  - 실험 시나리오 25개: 재현성을 위해 고정값을 쓴다(명세 1.3).
- **스마트팜 자료**: 데이터마트는 과거 자료다. 직접 센서는 연결하지 않았다. API가 단위를 표기하지 않아 ℃와 %로 가정했다.
- **기상 API 한계**: 호우 특보를 제공하지 않아 `heavy_rain_warning`은 `null`이다.

```powershell
python -m agbot live                                                 # 실시간 API 값 확인
python -m agbot ask "내일 날씨 보고 대비할 거 있어?" --scenario LIVE
```

## 설치와 준비

```powershell
pip install -e ".[dev]"
```

키는 `API_key.txt`나 `.env`에 둔다(위 표 참고).

```powershell
python scripts/build_chunks.py   # PDF → knowledge/chunks.jsonl (이미 생성되어 있음)
python scripts/build_index.py    # chunks → Chroma 벡터DB (OpenAI 임베딩, 1회)
```

## 실행

```powershell
python -m agbot scenarios                                         # 시나리오 목록
python -m agbot ask --scenario TSK-OF-003 --condition mcp         # 시나리오 질문 그대로
python -m agbot ask --scenario TSK-OF-003 --condition rag
python -m agbot ask "지금 하우스 환기해야 돼?" --scenario DEMO      # DEMO: 실제 수집 자료 기반 상황
python -m agbot ask --scenario NUT-GH-004 --mock                  # API 없이 흐름 점검
python -m pytest -q
```

## 실험 (명세 7~8절)

```powershell
python experiment/run.py --mock --repeats 1           # 파이프라인 점검
python experiment/run.py --repeats 10                 # 25 시나리오 × 2 조건 × 10회 = 500 응답
python experiment/judge.py outputs/v3/<폴더>           # LLM 채점 (+500 호출)
python experiment/plot.py outputs/v3/<폴더>
```

| 지표 | 정의 |
|---|---|
| 판정 정확도 | 채점기가 정답 판정과 일치한다고 본 비율 |
| 판정 일치율 | 시나리오별로 10회 중 가장 많이 나온 행동 목록의 비율, 시나리오 평균 |
| 필수 항목 누락률 | `required_items` 중 응답에서 빠진 항목의 비율 |
| 근거 제시율 | 기준값과 출처 문서를 함께 제시한 비율 |

- **입력값 전달 오류(MCP)**: 판정 도구 인자를 시나리오의 `reference_call`과 코드로 비교한다(`input_mismatch` 열).
- **오류 유형**: 명세 8.3에 따라 `errors.csv`에 집계한다.
- **수치 허용오차**: 상대 ±1%로 사전에 고정했다.
- **사람 검수**: `results.csv`에서 `review_sample=1`로 표시된 약 10%를 사람이 확인한다.

## 정답과 규칙 확인

- `tests/test_rules.py`: 규칙의 원문 clause가 모두 RAG 문서 문단에 들어 있는지 확인한다(원칙 2, 문서 동일). 경계값, 누락, 계산, 작형 분기, 규칙 충돌도 시험한다.
- `tests/test_scenarios.py`: 각 시나리오의 정답이 규칙 엔진 판정(`reference_call`)과 일치하는지 확인한다.
- 정답은 출처 문서를 기준으로 연구자가 작성했다. 정답과 MCP 규칙의 출처가 같기 때문에, MCP 조건의 오류는 주로 입력값 전달 오류와 설명 오류를 반영한다(명세 7.5).

## 확정한 경계 처리 (`rules.yaml`)

- 문서의 "이상/이하"는 경계값을 포함한다.
  - 30℃는 고온 기준에 해당한다.
  - 배액률 20%와 30%는 범위 안이다.
  - 최저기온 10℃는 보온 피복 대상이다.
- 착과제 농도: 평균기온 20℃ 이하이면 50배액, 20℃ 초과이면 100배액이다.
- 착색 단계 경계: 10% 이하 변색기, 30%까지 최색기, 60%까지 도색기, 90% 미만 담적색기, 90% 이상 완숙기.
- 규칙이 충돌할 때의 우선순위:
  - 야간 고습인데 외기온이 10℃ 이하이면 환기 대신 송풍한다(ENV-08).
  - 배액률 기준과 근권 EC 조절 방향이 반대이면 배액률 기준을 우선한다.

## 웹 챗봇 (모바일)

MCP 방식 + 실시간 API(LIVE: 기상청·흙토람·스마트팜 데이터마트)로 답하는 대화형 챗봇이다. 그래프 요청과 ToBRFV 질문에도 답한다.

```bash
# 서버: 저장소 루트에 .env 작성 (git에 올리지 않음)
#   OPENAI_API_KEY=... / FERTILIZER_API_KEY=... / SMARTFARM_API_KEY=... / APP_PASSCODE=<접속 코드>
docker build -t agbot-chat .
docker run -d --name agbot-chat --env-file .env -p 8110:8110 -v agbot_chroma:/app/knowledge/chroma --restart unless-stopped agbot-chat
```

- 첫 실행 때 문서 벡터 DB(721문단)를 OpenAI 임베딩으로 만든다(1~2분).
- `agbot/web.py`(FastAPI), `agbot/app_chat.py`(대화·그래프), `webapp/index.html`(화면).
- ToBRFV 자료: `knowledge/tobrfv_sources.md` (2026-11-18 웹 조사, 문단별 출처).
