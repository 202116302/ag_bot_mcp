"""경로·모델 설정과 API 키 로딩."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"

MODEL = "gpt-5.4-mini-2026-03-17"
REASONING_EFFORT = "none"
MAX_OUTPUT_TOKENS = 1800
MAX_MODEL_CALLS = 8  # 도구 호출 왕복 포함 최대 모델 호출 횟수 (조회 2~3 + 검색 + 판정 + 답변)

EMBED_MODEL = "text-embedding-3-small"
CHROMA_DIR = ROOT / "knowledge" / "chroma"
SEARCH_K = 5  # 검색 문단 수 (두 조건 공통)

# LIVE 시나리오(실시간 API)에서 조회할 대상
LIVE_FARM = {
    "pnu": "5271033027105280033",            # 완주군 이서면 용서리 528-33 (흙토람 처방 확인된 필지)
    "fertilizer_cultivation": "open_field",  # 노지 토마토 04016 (시비는 노지 영역)
    "smartfarm_facility": "PFS_0000001_01",  # 데이터마트 토마토 시설 (과거 자료)
    "smartfarm_date": "2023-07-25",
    "smartfarm_hour": 14,
}

WEATHER_URL = "http://weather-rda.digitalag.kr:8001"
WEATHER_REGION = "전주시완산구"


KEY_FILE = ROOT / "API_key.txt"
# API_key.txt의 '인증키' 줄은 바로 위 제목줄로 어떤 서비스인지 구분한다.
KEY_TITLES = {"비료": "FERTILIZER_API_KEY", "스마트팜": "SMARTFARM_API_KEY"}


def _key_file_values() -> dict:
    values, title = {}, ""
    if not KEY_FILE.exists():
        return values
    for line in KEY_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        name, sep, value = line.replace("：", ":").partition("=") if "=" in line else line.partition(":")
        if not sep:
            title = line
            continue
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name == "인증키":
            name = next((k for word, k in KEY_TITLES.items() if word in title), name)
        values[name] = value
    return values


def get_key(name: str) -> str | None:
    """환경 변수 → 루트 .env → 루트 API_key.txt 순서로 키를 찾는다. 값은 출력하지 않는다."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'")
    return _key_file_values().get(name) or None
