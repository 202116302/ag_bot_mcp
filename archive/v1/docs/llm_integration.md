# Mock 및 GPT-5.4-mini 연결

구현일: 2026-11-15. 범위: 선택 필지의 저장된 비료 처방에 대한 도구 호출과 구조화 설명.
RAG 비교나 농업 판단 정확도 평가를 완료한 것은 아니다.

## 2026-11-16 후속 상태 (아래 이전 기록보다 우선)

- 최신 자동 테스트237개 통과. 환경자료 독립 원본 감사와 고정 조건10회 반복을 완료했다.
  GPT 모델 처리50건씩에서 MCP47/50·RAG49/50 전달 검증 통과, 오류4건은 차단·보존했다.
  API 없는 재집계도 동일했다. [환경 반복 평가](environment_experiment.md)를 따른다.
- 과거 환경자료와 토마토 문헌을 함께 보여주는 별도 environment-ask MCP/RAG 경로 구현 완료.
  최신 자동 테스트231개 통과. 수정 후 실제 모델 처리10건·로컬 보류8건 점검 통과.
  단위/적용 조건 미확인에 따른 판단 보류를 유지하며 초기 실패 기록도 보존했다.
  [환경 문헌 질의응답](environment_literature_qa.md)을 따른다.
- 현재 실험은 관수를 제외한 비료 처방 전달·근거 추적·반복 일관성이다.
  최신 자동 테스트175개 통과. 실제 GPT 질문4개 ×10회에서 MCP38/40, RAG39/40 전달 검증 통과.
  실패3건은 네트워크 오류로 보존했고 받은 최종 응답77건에서는 수치·단위·출처·고지 오류가 없었다.
  [현재 결과](fertilizer_delivery_results.md), [현재 프로토콜](fertilizer_delivery_protocol.md)을 따른다.
- 합성 관수의 RAG 직접 판정/MCP 규칙 판정과 반복 평가를 추가했다. 최신 테스트 **156 passed**.
  Mock 경로별 100/100, 실제 GPT 경로별 3/3 합성 기대 판정·사유 일치.
  자세한 범위와 산출물은 [관수 비교](irrigation_experiment.md)를 따른다.
- 실제 GPT의 MCP 도구 선택·조회·구조화 응답 검증 완료. 분야별 10문항은 10/10 예상 흐름 일치(6개는 로컬 보류).
- `ask --path rag` 추가. 같은 정규화 비료 자료를 PNU·작물 메타데이터로 검색해 도구 없이 모델에 전달한다.
- `scripts/compare_fertilizer_paths.py`: 같은 질문·자료·모델·설정·검사기로 두 경로를 실행하고 원본과 실패를 보존한다.
- 전체 자동 테스트 **128 passed**. Mock 비교 1쌍과 실제 GPT 비교 1쌍 모두 완료·구조화 응답 일치.
- 실제 GPT 보고서: `outputs/path_comparison/20261116T050429871534Z/report.md`.
- 이는 비료 자료 전달 점검이다. 문헌 기준에 대한 직접 판단, 독립 농업 정답 및 정확도 지표는 아직 없다.
- 키는 루트 `.env`에 설정되어 있다. 키 값은 기록하지 않는다.
- 후속 범위·프로토콜: [RAG 비교](rag_comparison.md).

## 후속: 분야 분기와 부분응답

`routing.py`에 로컬 키워드 기반 지원 범위 검사를 추가했다. 시비만 모델/MCP 경로로 보내고,
미지원 분야는 모델·MCP 호출 전에 `deferred`로 보류한다. 명시된 미등록 PNU와 다른 작물도 보류한다.
시비와 미지원 분야를 함께 묻는 경우 비료 조회 후 `partial`과 분야별 한계를 반환한다.
모델은 컨텍스트의 `required_notices`를 정확히 포함해야 하며 누락 시 설명 검증이 실패한다.
실행 로그의 `routing.method`로 로컬 분기를 명시한다. 사전 보류된 질문은 모델 호출 0회다.
이는 GPT가 분야를 분류한 결과가 아니며 복잡한 부정문·모든 작물명/주소/언어를 지원하지 않는다.

Mock 재점검: **10/10 예상 흐름 일치**, 비료 도구 4회, 나머지 6개 질문은 도구 호출 없이 보류.
복합 사례 2개는 관수 판단/기상 예측 성공이 아니라 비료 조회와 해당 분야 미지원 안내다.
최신 전체 테스트 **102 passed**. 보고서: `outputs/mock_flow/20261115T055205601129Z/report.md`.
시나리오 v1.1은 시비+관수의 정상 부분응답 상태 `partial`도 허용하도록 v1.0을 확장했다.
기대 경로 라벨은 평가기에만 쓰고 모델 입력이나 분기 함수에는 전달하지 않는다.
초기 3/10 보고서는 `outputs/mock_flow/20261115T054454533998Z/`에 별도로 보존한다.

API 키는 로컬 설정이 아직 없어 실제 GPT 재검증은 미수행이다. 채팅으로 공유된 키를
코드/실행 기록에 복사하지 않았다. 로컬 키 설정 후 단일 `ask`부터 실행하고 소량 사례 점검을 진행한다.

## 구성과 검증

- `llm.py`: 공통 비동기 모델 인터페이스, 결정적인 Mock, requests 기반 OpenAI Responses 어댑터.
- `assistant.py`: MCP 도구 탐색 → 함수 스키마 제공 → 모델 도구 선택 → 실제 stdio 도구 호출 →
  모델에 근거 반환 → 구조화 답변 검증. 모델 응답의 reasoning 등 output 항목도 후속 input에 보존한다.
- `explanation.py`: 10개 성분·퇴비 수치, 단위, PNU, 작물, 업무 상태, 출처 SHA-256,
  5개 한계 표기를 검사한다. 수치 비교는 Decimal을 사용하고 0과 null을 구분한다.
- 최종 한국어 문장은 검증된 필드를 템플릿으로 렌더링한다. LLM 자유서술의 의미 모순을
  포괄적으로 탐지한다고 주장하지 않는다.
- 공개하는 도구는 `get_fertilizer_prescription` 하나다. 모델은 auto 모드로 도구 사용을 선택한다.
  선택되지 않은 PNU/작물, 다른 도구, 경로 입력, 중복 call_id, 잘못된 인자를 실행 전에 거부한다.
- 수치 없는 공급자 오류와 자료 없음은 정상 처방으로 승격하지 않는다.
- 모델 호출 최대 3회, 도구 호출 최대 2회, 요청 연결/읽기 제한 8/45초, 전체 180초.
  API 자동 재시도 없음. 원본 응답·tool trace·usage·해시·설정·시간을 로컬 실행 기록에 저장한다.
- 재현 가능한 모델 ID는 `gpt-5.4-mini-2026-03-17`. 추론 설정은 none이며 설정 파일에서 변경한다.
  Mock 모델 ID는 별도로 `mock-fertilizer-v1`; synthetic_model 플래그를 기록한다.

공식 계약 확인: [함수 호출](https://developers.openai.com/api/docs/guides/function-calling),
[구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs),
[모델 사양과 고정 버전](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
Responses의 `text.format` JSON Schema, `store=false`, `parallel_tool_calls=false`를 사용한다.
로컬에 있던 OpenAI SDK 1.35.8은 사용하지 않는다. 기존 requests 의존성으로 REST 요청을 보낸다.

## 실행

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m agri_dss ask --provider mock
python -m agri_dss ask --provider openai
python -m pytest -q
```

OpenAI 키는 환경 변수 또는 루트 `.env`의 `OPENAI_API_KEY=...`로 설정한다.
환경 변수가 우선하며 키는 API 요청 Authorization 헤더에만 쓴다. 저장할 요청 헤더는 없다.
HTTP/네트워크 예외는 상세 본문이나 URL 대신 정해진 오류코드로 남긴다.
모델 응답에 키 원문이 되돌아오는 경우에도 저장 전 마스킹한다.

## 실제 확인 결과

- 전체 테스트 **83 passed**.
- Mock CLI가 실제 MCP 서버를 호출해 모델 2회·도구 1회로 완료.
- 변경된 수치/단위/출처, 누락/중복 필드, 0과 결측 혼동, 근거 없는 답변,
  미등록 필지/다른 도구/경로 입력, API 401/429/500, 거절/불완전 응답과 반복 제한을 검증.
- 실제 GPT 실행 명령은 `OPENAI_API_KEY_MISSING`으로 안전하게 종료.
  GPT 서버 연결·모델 접근 권한·실제 응답 품질·사용 비용은 아직 확인하지 못했다.
- 실행 기록: `outputs/llm/mock_smoke.json`, `outputs/llm/openai_smoke.json`.
  이는 점검 기록이며 비교 실험 결과가 아니다.

## 다음 작업

1. OpenAI 키 설정 후 1개 질문 실호출로 스키마 지원·도구 호출·검증 통과 여부 확인.
2. 질문/스냅샷/문서를 고정하고 RAG 경로 구현. 이 비료 처방 조회는 문헌 기반 자체 규칙과 별도 과제다.
3. 독립 정답과 평가 프로토콜을 정한 뒤 반복 실험. 모델/추론 설정을 양쪽 경로에 동일하게 적용한다.
