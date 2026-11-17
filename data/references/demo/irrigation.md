# 합성 데이터 관수 규칙 (demo_only)

실제 작물·농업 처방에 적용하지 않는 소프트웨어 시험용 문서다.
합성 작물 `demo_crop`, 단계 `demo_stage`, 재배방식 `demo_soil`에서
부피수분함량이 20% 미만이면 관수 필요, 그 외에는 관수 불필요로 판정한다.
18% 및 기준 20%는 임의 시험값이다. 토마토 길잡이에서 가져온 값이 아니다.

## 판정 계약 v0.1.0-demo

규칙 ID는 `irrigation_synthetic_001`, 버전은 `0.1.0-demo`, 출처 ID는
`synthetic_rule_reference`다. 아래 순서대로 검사하며 먼저 해당하는 사유 하나를 반환한다.

1. crop, growth_stage, cultivation_system, soil_moisture_value, soil_moisture_unit 중
   null 또는 누락이 있으면 `INSUFFICIENT_INFORMATION` / `MISSING_INPUT`.
2. crop이 demo_crop이 아니면 `INSUFFICIENT_INFORMATION` / `CROP_MISMATCH`.
3. growth_stage가 demo_stage가 아니면 `INSUFFICIENT_INFORMATION` / `STAGE_MISMATCH`.
4. cultivation_system이 demo_soil이 아니면 `INSUFFICIENT_INFORMATION` / `CULTIVATION_MISMATCH`.
5. soil_moisture_unit이 percent_vwc가 아니면 `INSUFFICIENT_INFORMATION` / `UNIT_MISMATCH`.
   kPa를 %로 바꾸지 않는다.
6. soil_moisture_value가 100보다 크면 `INSUFFICIENT_INFORMATION` / `VALUE_OUT_OF_RANGE`.
7. 값이 20.0보다 작으면 `IRRIGATION_REQUIRED` / `RULE_MATCH`.
   20.0과 같거나 크면 `IRRIGATION_NOT_REQUIRED` / `RULE_NOT_MATCH`.

0은 유효한 관측값이며 null로 취급하지 않는다. 이 계약에서 0 이상인 수치만 입력한다.
관수량·물 부피·금액을 계산하는 규칙은 없다. 판정에 필요한 출처 ID는
입력 관측의 `synthetic_fixture`와 구분한다. 모든 결과는 `demo_only=true`로 표시한다.
