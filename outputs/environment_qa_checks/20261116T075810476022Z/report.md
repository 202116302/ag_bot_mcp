# 환경자료·재배문서 질의응답 점검

- 공급자: openai, 경로별 사례 합계: 18, 계약 일치: 16
과거 환경자료의 수치·문헌 인용·판단 보류 계약을 확인했다. 환경 적정성이나 제어 정확도 평가는 아니다.
5개 자료/문헌 질문과 4개 로컬 보류 질문을 경로별로 실행했다. 로컬 보류는 모델 평가가 아니다.
RAG 실모델은 원시 환경값에서 건수·최솟값·최댓값을 읽고, MCP는 Python 요약 도구를 호출한다.
문헌 인용은 검토된 5개 문단의 topic/type 필터다. 자유서술 의미나 일반 검색 품질을 검증하지 않는다.

| 사례 | 경로 | 상태 | 계약 일치 | 오류 |
|---|---|---|---|---|
| overview | mcp | conflict | False | ENVIRONMENT_ANSWER_CONFLICT |
| overview | rag | partial | True |  |
| general_temperature | mcp | partial | True |  |
| general_temperature | rag | partial | True |  |
| cherry_temperature | mcp | partial | True |  |
| cherry_temperature | rag | partial | True |  |
| humidity | mcp | partial | True |  |
| humidity | rag | partial | True |  |
| co2 | mcp | tool_error | False | UNSELECTED_ENVIRONMENT_CONTEXT |
| co2 | rag | partial | True |  |
| irrigation_excluded | mcp | deferred | True |  |
| irrigation_excluded | rag | deferred | True |  |
| current_control | mcp | deferred | True |  |
| current_control | rag | deferred | True |  |
| different_parcel | mcp | deferred | True |  |
| different_parcel | rag | deferred | True |  |
| different_facility | mcp | deferred | True |  |
| different_facility | rag | deferred | True |  |
