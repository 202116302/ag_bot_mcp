# 농업 의사결정지원 연구 프로토타입

저장소: [202116302/ag_bot_mcp](https://github.com/202116302/ag_bot_mcp)
소스·문서·첨부 PDF·마스킹된 API 원본·실험 결과를 함께 보관한다.
`.env`, 인증키 파일, 로컬 도구·캐시는 제외하며 실험 해시 보존을 위해 파일 줄바꿈을 자동 변환하지 않는다.

**작업 재개:** [인수인계 메모](docs/HANDOFF.md)를 먼저 읽는다. 현재 구현·API 조회 결과·사용자 결정·다음 작업을 정리했다.

**전체 현황:** [시스템 구성·완료 작업·실험 결과·앞으로 할 작업](시스템_구성_및_개발현황.md)을 한 문서로 정리했다.

현재 실험 범위는 **저장된 비료 처방 정보의 전달 정확성·근거 추적·반복 일관성 비교**다.
MCP는 공급자가 계산한 처방을 도구로 조회하고, RAG는 같은 정규화 자료를 검색해 모델에 전달한다.
관수는 사용자 결정으로 이번 실험에서 제외했다. 관련 코드·문헌·합성 시험 기록은 보관한다.
현재 비료 MCP는 자체 시비 판정을 하지 않으며, 본 결과는 농업 판정 정확도나 MCP의 일반적 우월성을 뜻하지 않는다.

사용자 요청으로 **직접 센서 대신 스마트팜 데이터마트 API를 사용하는 환경자료 경로**를 추가했다.
과거 하루의 내부온도·습도·CO₂ 각24건을 확보했고 CLI/MCP에서 저장 자료를 읽을 수 있다.
환경자료와 문헌을 함께 쓰는 전용 GPT 질의응답을 추가했다. [환경자료 연결 기록](docs/smartfarm_environment_integration.md),
[문헌 질의응답 사용법](docs/environment_literature_qa.md)을 참고한다.

현재 환경 질의응답은 일반/방울토마토 온도·공기습도·CO₂의 검토 문단과 과거 수치를 함께 보여준다.
단위·적용 조건 미확인에 따른 수치 적합성·설비 제어 판단은 보류한다.
최종 실제 GPT 점검은 모델 처리10건·로컬 보류8건 통과이며, 이전 실패 기록도 보존했다.

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m agri_dss environment
python -m agri_dss environment-ask --provider mock --path mcp
python -m agri_dss environment-ask --provider openai --path rag --question "과거 습도 자료와 토마토 문헌 근거를 보여줘."
```

### 현재 비료 전달 반복 평가

```powershell
python scripts/compare_fertilizer_paths.py --suite --repeats 10
python scripts/compare_fertilizer_paths.py --suite --provider openai --repeats 10 --case prescription_full --case unregistered_parcel --case unregistered_crop
```

원본 XML과 대조한 고정 전사값으로 원시 모델 응답의 수치·단위·PNU·작물·상태·출처·한계 고지를
별도 채점한다. 런타임 검증에서 차단된 오류와 누락 로그도 분모에 남긴다.
모델 전달 질문 4개와 로컬 보류 검사 2개를 구분하며, 보류는 모델 성능 통계에서 제외한다.
질문과 참조값은 `configs/scenarios/fertilizer_delivery.json`에 고정했다.
원본·CSV·요약은 `outputs/fertilizer_delivery/<시각>/`에 저장한다.
API 없이 `python scripts/compare_fertilizer_paths.py --analyze <실행 폴더>`로 재집계할 수 있다.
[범위·평가 프로토콜](docs/fertilizer_delivery_protocol.md)을 참고한다.

실제 GPT 질문4개 ×10회에서 전달 검증 통과는 **MCP 38/40, RAG 39/40**이었다.
실패3건은 모두 네트워크 오류로 보존했다. 받은 최종 응답77건에서는 수치·단위·출처·고지 오류가 없었다.
이는 단일 자료의 전달 비교이며 농업 정확도나 두 방법의 우열을 뜻하지 않는다.
[실측 결과와 CSV 위치](docs/fertilizer_delivery_results.md)를 참고한다.

### LLM으로 MCP 비료 조회

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m agri_dss ask --provider mock
python -m agri_dss ask --provider openai
```

Mock은 키·네트워크 없이 실제 MCP subprocess를 호출한다. OpenAI 실행은 환경 변수
`OPENAI_API_KEY`를 우선 사용하며, 없으면 프로젝트 루트 `.env`의 `OPENAI_API_KEY=...`를 읽는다.
키는 채팅·소스 코드에 넣지 않는다. 기존 비료·스마트팜 키를 OpenAI 키로 사용하지 않는다.
이 `.env` 로더는 OpenAI 키 한 항목만 처리하며 다른 API 스크립트의 환경 변수 로딩을 변경하지 않는다.

`configs/llm.json`은 GPT-5.4-mini의 고정 버전 `gpt-5.4-mini-2026-03-17`,
추론 수준 `none`, 응답당 최대 1800 출력 토큰, 모델 최대 3회·MCP 도구 최대 2회를 설정한다.
실호출은 OpenAI Responses API로 전송하며, 별도 OpenAI SDK 설치 없이 기존 requests를 쓴다.
API 자동 재시도와 다른 모델로의 자동 전환은 하지 않는다.

모델이 선택 필지·작물로 비료 도구를 호출하면 실제 MCP 결과를 다시 모델에 전달한다.
모델의 구조화된 수치·단위·출처·결측·한계 표기를 검사하고 통과한 필드를 한국어 템플릿으로 출력한다.
자유서술 전체의 사실성을 판정하는 기능은 아니다. 질문 범위는 현재 선택 필지의 저장된 비료 처방이다.
검증 실패, 근거 없는 답변, 도구 오류, 모델 거절·불완전 응답은 실패 상태로 남기고 사용자 처방 설명을 출력하지 않는다.

원본 모델 응답·사용량(공급자가 반환할 때)·도구 기록·해시·설정·실행 시간은
`outputs/llm/<run-id>.json`에 저장한다. `--output <파일>`로 경로를 지정하고,
`--json`으로 전체 실행 기록을 출력할 수 있다. 실패도 기록되며 CLI는 0 이외의 코드로 종료한다.
Mock 완료는 GPT 성능이나 농업 정확도가 아니다. 실제 GPT 검증은 자료 전달과 구조화 응답 계약 범위다.

최신 전체 테스트: **237 passed**. [LLM 연결 구현 기록](docs/llm_integration.md) 참고.

환경자료 원본을 앱과 별도로 감사하고 고정 조건의 반복 평가·CSV·API 없는 재집계를 추가했다.
[환경자료 감사·반복 평가](docs/environment_experiment.md)를 참고한다.
실제 GPT 환경 질문5개 ×10회 반복의 전달 검증은 **MCP47/50, RAG49/50**이다.
수치 누락·항목 구성 오류4건을 차단·보존했으며 인용·한계 고지·식별/해시는 양쪽50/50 일치했다.
단일 시설·하루의 조회 과제이므로 농업/제어 정확도나 방법의 우월성으로 해석하지 않는다.

```powershell
python scripts/run_environment_experiment.py --repeats 10
python scripts/run_environment_experiment.py --provider openai --repeats 10
```

### 보관된 합성 관수 시험 (현재 실험 범위에서 제외)

```powershell
python -m agri_dss irrigation-ask --path rag --case SYNTHETIC-EQUAL
python scripts/compare_irrigation_paths.py --repeats 10
python scripts/compare_irrigation_paths.py --provider openai --case SYNTHETIC-EQUAL --case SYNTHETIC-MISSING --case SYNTHETIC-UNIT
```

앞의 `PYTHONPATH=src`, UTF-8 설정 후 실행한다. 이 명령은 실제 필지 질문과 별도의 합성 시험이다.
RAG 실모델은 기준 원문과 입력으로 직접 판정하고, MCP는 실제 도구의 Python 판정을 모델이 설명한다.
독립적으로 작성한 합성 기대 라벨은 평가기에만 전달한다. 잘못된 RAG 판정도 원문 그대로 보존해 평가한다.
Mock RAG는 엔진 기반 시험 대역이므로 독립 추론이나 모델 성능 검증이 아니다.

10개 사례 × 경로별 10회 Mock 시험은 각 **100/100** 기대 판정·사유 일치.
실제 GPT는 경계값·결측·단위 불일치 3개 사례에서 각 경로 **3/3** 일치했다.
원본 JSON·CSV·요약·보고서는 `outputs/irrigation_comparison/`에 있으며
API 없이 `--analyze <실행 폴더>`로 재집계할 수 있다.
[관수 비교 프로토콜·결과·남은 조건](docs/irrigation_experiment.md)을 참고한다.
문헌에서 확인한 토마토 수분 범위는 실행 불가 후보로 보존하며, 이 합성 임계값을 실제 처방으로 적용하지 않는다.

후속 [토마토 문헌 검토](docs/tomato_literature_review.md)에서 PDF132쪽의
**토양 관비재배 텐시오미터 관수개시점 −20 kPa**와 품종별 범위를 확인했다.
현재는 적용 조건·부호·경계 형식화를 분리한 후보이며 실행 규칙으로 승격하지 않았다.

### 같은 비료 자료로 MCP/RAG 비교

```powershell
python -m agri_dss ask --provider mock --path rag
python -m agri_dss ask --provider openai --path rag
python scripts/compare_fertilizer_paths.py
python scripts/compare_fertilizer_paths.py --provider openai
```

위 명령은 앞의 `PYTHONPATH=src`, UTF-8 설정 후 실행한다. `ask`의 기본 경로는 `mcp`다.
RAG는 선택 필지·작물에 해당하는 정규화 처방 문서 1개를 메타데이터로 검색해 모델에 전달한다.
MCP 도구를 호출하지 않으며, 같은 수치·단위·출처·결측·한계 검사로 결과를 검증한다.
이는 공급자 처방 전달 비교이며 문헌 검색이나 자체 농업 규칙 판정의 정확도 평가는 아니다.

비교 명령의 기본 실행은 각 경로 1회이며 `--repeats 1..10`, `--question`을 지원한다.
원본·정규화 자료 해시, 모델·설정·코드·질문·응답 스키마가 같은지 검사하고,
실패를 포함한 개별 실행 JSON·요약·보고서를 `outputs/path_comparison/<시각>/`에 저장한다.
금번 실제 GPT 1쌍은 두 경로 모두 완료했고 구조화 응답이 일치했다.
결과: `outputs/path_comparison/20261116T050429871534Z/report.md`.
상세 범위와 후속 연구 조건은 [비교 프로토콜](docs/rag_comparison.md)을 참고한다.

분야별 Mock 호출 흐름은 별도로 확인했다. `python scripts/check_mock_flows.py`로
사람이 작성한 10개 질문의 기대 경로와 실제 stdio MCP 호출을 비교한다.
최초 점검은 **3개 일치·7개 불일치**였다. 후속 수정으로 로컬 지원 범위 검사를 추가했고,
재점검은 **10개 모두 일치**했다. 관수·기상·생육·환경제어·토양검정은 `deferred`로 보류하고,
시비와 결합된 질문은 비료만 조회한 뒤 `partial`과 해당 분야의 한계 표기를 반환한다.
미등록 PNU나 다른 작물 요청은 기본 필지·시설 토마토로 대체하지 않는다.
이 분기는 제한된 키워드 규칙이며 GPT 분야 분류 능력이나 농업 정확도 평가는 아니다.
부정문·복잡한 지시·미등록 표현 전반을 해석하는 기능은 없으며 별도 사례 확장이 필요하다.
시비+관수의 일치는 비료 조회 및 관수 자료 부재 고지만 뜻한다.
점검 명령은 불일치가 있으면 종료 코드 1을 반환하고 `outputs/mock_flow/<시각>/`에 보고서를 저장한다.
`ask`의 `completed/partial/deferred`는 정상 업무 상태로 종료 코드 0이며, 실행·검증 오류는 0 이외다.
GPT 키를 로컬에 설정한 뒤 `python scripts/check_mock_flows.py --provider openai`로 같은 사례를 실행할 수 있다.

2026-11-15 사용자 선택에 따라 기본 필지를 **완주군 이서면 용서리 528-33,
`5271033027105280033`**으로 변경했다. 시험 작물은 토마토(시설) `04017`이다.
이전 PNU는 설정의 `previous_pnu_code`에 보존한다.

### 선택 필지 비료 데이터 사용

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m agri_dss fertilizer
python -m agri_dss fertilizer --output data/snapshots/wanju_fertilizer.json
python -m agri_dss mcp-demo
```

`fertilizer`는 저장된 실제 API 응답을 읽으며 네트워크·인증키 없이 재현 가능하다.
원본은 `data/references/fertilizer/wanju_tomato_20261115.json`, 정규화 자료는
`data/snapshots/wanju_fertilizer.json`이다. 금액이 아닌 비료 성분/퇴비 처방량이며 단위는
API 명세의 `kg/10a`를 보존한다. 소수 정밀도를 보존하기 위해 JSON 수치는 십진 문자열로 직렬화한다.

MCP의 `get_fertilizer_prescription(pnu_code="5271033027105280033", crop_code="04017")`로
같은 자료를 조회할 수 있다. 미등록 필지·작물은 거부한다.
`mcp-demo`는 기존 관수 데모와 이 실제 비료 응답의 조회를 함께 점검한다.

결과에는 공급자 처방임을 나타내는 `result_origin`, 원본 SHA-256, 조회 시각,
원본 항목명, 단위, 결측값과 업무 상태를 기록한다. HTTP 실패·업무 오류·데이터 없음은
처방 수치로 변환하지 않는다. 검정 일자는 응답에 없어 `null`이며 실제 재배 작물과 적용 적합성은 미확인이다.
이는 자체 Python 시비 규칙이나 독립 정답이 아니며 관수 수분 입력과 결합하지 않았다.

비료 연결 단계에서 테스트 **55개 통과**: 실제 MCP 왕복, 비료 응답의 요청/응답 식별자 일치,
누락/0 구분, 오류 응답 차단, 단위·출처 보존을 포함한다.

## 설치 및 실행

Python 3.11 이상. 프로젝트 루트에서 실행한다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,mcp]"
python -m agri_dss demo
python -m agri_dss mcp-demo
python -m pytest -q
```

이미 의존성이 설치된 환경에서는 패키지 설치 없이 다음으로 실행할 수 있다. 이번 작업에서는 이 방식으로 검증했다.

```powershell
$env:PYTHONPATH = 'src'
python -m agri_dss demo
python -m agri_dss mcp-demo
python -m pytest -q
```

별도 입력·규칙을 지정하려면:

```powershell
python -m agri_dss evaluate --snapshot data/snapshots/demo_irrigation.json --rule configs/rules/demo/irrigation.json --mode demo
```

`demo` 예시는 합성 수분값 18%, 임계값 20% 미만 조건을 사용해 `IRRIGATION_REQUIRED`를 반환한다.
이는 실제 토마토 처방이 아니다. 결과에 `demo_only`, 사용 입력, 중간 비교, 출처와 규칙 버전이 기록된다.
입력 부족은 `INSUFFICIENT_INFORMATION`, 잘못된 자료형은 입력 오류다. 데모 규칙에 `--mode research`를 지정하면 종료 코드 2로 거부한다.

## API 연결 점검

2026-11-15 전북 추가 시험: 흙토람 공개 목록에서 고른 완주군 6개 필지의 `52…` PNU로
시설 토마토·벼 처방 12건을 확보했다. 같은 지번의 `45…` 비교 요청 12건은 자료 없음이었다.
탐색 당시 기본 PNU는 유지했으며 이후 사용자 선택으로 위 성공 필지로 변경했다. [상세 결과](docs/api_connection_report.md) 참고.
재실행: `python scripts/probe_apis.py --fertilizer-jeonbuk` (비료 호출 최대 24건).

```powershell
python scripts/probe_apis.py
python scripts/probe_apis.py --discover
python scripts/probe_apis.py --sample
python scripts/probe_apis.py --sensors
python scripts/probe_apis.py --fertilizer-example
```

명령은 각각 최초 연결, 지역·작기 탐색, 기상 및 작기 환경 첫 페이지, 시설·일자별 센서 조회를 수행한다.
`--fertilizer-example`은 명세서 PNU `4571033027106720012`로 벼·시설 토마토만 추가 조회하며 기본 PNU를 변경하지 않는다.
외부 네트워크가 필요하며 `--sample`과 `--sensors`는 `--discover` 결과를 사용한다.
`--discover`는 최초 조회 목록의 토마토 농가 3곳만 탐색한다. 이는 편의 표본으로 대표성 있는 연구 표본이 아니다.
작기 환경 첫 페이지는 페이지당 최대 1000건이며 전체 작기를 모두 수집하지 않는다.

인증은 `FERTILIZER_API_KEY`, `SMARTFARM_API_KEY` 환경 변수를 우선 사용한다.
값이 없으면 기존 `data/API_key.txt`의 `인증키 : 값` 두 줄을 비료·스마트팜 순서로 읽는다.
`.env.example`은 변수명 안내이며 `.env` 파일을 자동 로딩하지 않는다.
키와 인증 URL은 콘솔에 출력하지 않는다. 로컬 응답 저장 시 키를 마스킹하며 예외는 종류만 기록한다.
인증키 파일과 산출물은 Git 제외 대상이다.

기본 PNU는 `5271033027105280033`, 시험 작물코드는 `04017`(토마토 시설)이다.
`configs/data_sources.json`에서 변경할 수 있다. 다른 작물을 시험할 때 코드와 이름을 함께 수정한다.
전주시완산구는 기상 연결 시험용 지역이며 해당 필지·스마트팜과 같은 위치라는 가정은 하지 않는다.

응답은 `outputs/api_probe/<UTC 실행시각>/`에 저장된다. HTTP 성공과 서비스 성공은 다르다.
기상은 빈 배열, 스마트팜은 상태 `03`, 비료는 결과 `301`로 데이터 없음을 표현할 수 있다.
현재 스크립트는 진단 자료 수집기다. 네트워크 실패도 파일로 기록하고 끝나므로 프로세스 종료 코드만으로 데이터 확보 성공을 판정하면 안 된다.

## 검증 상태 (2026-11-14)

- 자동 테스트 38개 통과. 실제 MCP subprocess 통신 포함.
- 비료: 기본 PNU + 시설 토마토에 `301 요청 데이터 없음`. 기본 PNU 유지.
- 비료 명세서 예시 PNU도 벼·시설 토마토 모두 `301 요청 데이터 없음`.
- 스마트팜: 아이덴티티 목록 2319개, 토마토 품목 레코드 531개. 시험 농가의 2023-07-25 온도 데이터 24개 조회.
- 시험 농가·날짜의 토양함수율(MC), 수분장력(MT)은 `03 NODATA_ERROR`.
- 작기 환경 첫 페이지 조회는 읽기 시간 초과로 기록. 하루·항목 단위 조회로 온도 데이터 확보.
- 기상: 전주시완산구 실황 1개 및 강수확률 예보 3개 조회 성공.
- 실제 농업 규칙의 검토 승인, LLM 비교 실험과 성능 수치 산출은 미수행.

## 개발 가정과 남은 작업

1. 노지·시설 토경·수경 기준을 구별하며 서로 다른 센서 단위를 임의 변환하지 않는다.
2. 스마트팜 작기와 기상은 동일 기간·위치임을 확인해야 결합한다. 과거 작기에 현재 날씨를 붙이지 않는다.
3. 실측 관수 판정에는 수분 센서 데이터와 단위, 생육단계 및 재배방식 확인이 필요하다.
4. 토마토 문헌의 서로 다른 관리 범위 및 경계 해석은 검토 전까지 규칙 후보로 둔다.
5. 연구 모드에서 규칙·출처 검증 플래그를 검사한다. 자동으로 원문 사실성을 심사하는 기능은 없으며, 검증된 규칙 파일은 아직 제공하지 않는다.
6. 비료 체험 V2는 토양 화학성 입력값과 해당 서비스 승인 여부 확인 후 연결한다. 필지 조회 실패를 임의 분석값으로 우회하지 않는다.
7. LLM의 비료 MCP 도구 선택·설명과 같은 자료를 직접 전달하는 RAG 비교를 구현했다. 문헌 기준 직접 판정과 독립 정답 기반 평가는 후속 작업이다.
8. 설치 버전 전체를 잠근 재현 환경은 실험 단계에서 구축한다. 현재 검증 환경의 주요 패키지 버전은 `docs/runtime_manifest.json`에 기록한다.

설계: [구현 설계](docs/implementation_design.md), [자료·API 검토](docs/data_integration_design.md).
실제 연결 기록: [API 점검 결과](docs/api_connection_report.md).
포스터용 연구 그래프는 아직 없다. 초기 구성도는 구현 설계 문서의 Mermaid를 참고한다.
