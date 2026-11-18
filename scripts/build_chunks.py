"""PDF 문서 → knowledge/chunks.jsonl

python scripts/build_chunks.py

- 쪽 단위로 텍스트를 추출해 약 CHUNK_CHARS 글자 단위(줄 경계)로 자르고, 앞 chunk와 OVERLAP 글자를 겹친다.
- PDF 표가 깨져서 추출되는 부분은 knowledge/curated.jsonl에 사람이 텍스트로 정리해 두고 함께 넣는다.
- 메타데이터(cultivation, domain)는 키워드로 단순 태깅한다.
"""
import json
import re
import sys
from pathlib import Path

import pypdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "knowledge" / "chunks.jsonl"
CURATED = ROOT / "knowledge" / "curated.jsonl"
CHUNK_CHARS = 700
OVERLAP = 200

DOCS = [
    {"doc_id": "JEJU-TOMATO", "file": "과채류(토마토).pdf", "title": "제주특별자치도농업기술원 과채류(토마토)", "pages": None},
    {"doc_id": "RDA-WEATHER-2025", "file": "000000323533_01.PDF",
     "title": "농촌진흥청 2025 기상재해 대응기술 가이드북 (토마토)", "pages": range(42, 46)},
    {"doc_id": "MOON-2018", "file": "암면배지의 수분제어가 토마토의 생육 및 생산성에 미치는 영향.pdf",
     "title": "문두경 외 (2018) 한국농림기상학회지 20(2)", "pages": None},
    {"doc_id": "NONGSARO-TOMATO", "file": "29 토마토_저화질_단면.pdf",
     "title": "농촌진흥청 농업기술길잡이 106 토마토 (2020 개정판)", "pages": None},
    {"doc_id": "HWANG-2012",
     "file": "토마토 수경재배 시 배액제로 센서를 이용한 배액제로화가 근권환경, 생육 및 수량에 미치는 영향.pdf",
     "title": "황연현 외 (2012) 생물환경조절학회지 21(4)", "pages": None},
]

DOMAIN_WORDS = {
    "climate": ["온도", "℃", "습도", "환기", "차광", "난방", "보온", "송풍", "포그", "탄산가스"],
    "nutrient": ["양액", "배액", "급액", "EC", "pH", "배양액", "일사"],
    "fertilizer": ["시비", "비료", "거름", "질소", "인산", "칼리", "요소", "퇴비"],
    "weather": ["재해", "침수", "폭염", "저온", "고온", "강우", "피해율"],
    "task": ["적심", "순지르기", "착과제", "토마토톤", "수확", "착색", "화방", "곁순", "적엽"],
}
CULTIVATION_WORDS = {
    "greenhouse_hydroponic": ["양액", "암면", "배지", "하우스", "시설", "온실"],
    "open_field": ["노지", "고냉지"],
}


def clean(text: str) -> str:
    text = text.replace("　", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def split(text: str) -> list[str]:
    """줄 경계로 CHUNK_CHARS 근처에서 자르고 OVERLAP만큼 겹친다."""
    lines, chunks, cur = text.splitlines(), [], ""
    for line in lines:
        if cur and len(cur) + len(line) > CHUNK_CHARS:
            chunks.append(cur)
            tail = cur[-OVERLAP:]
            cur = tail[tail.find("\n") + 1:] if "\n" in tail else tail
        cur = f"{cur}\n{line}" if cur else line
    if cur.strip():
        chunks.append(cur)
    return chunks


def tags(text: str, table: dict) -> list[str]:
    found = [k for k, words in table.items() if any(w in text for w in words)]
    return found or ["common"]


TOBRFV = ROOT / "knowledge" / "tobrfv_sources.md"


def tobrfv_chunks() -> list[dict]:
    """웹 조사 문서(knowledge/tobrfv_sources.md): 문단 하나 + 바로 아래 '출처:' 줄 = 문단 1개(출처 포함)."""
    if not TOBRFV.exists():
        return []
    rows, section, para = [], "", []
    for line in TOBRFV.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith("출처:") and para:
            text = f"[ToBRFV · {section}]\n" + " ".join(para) + "\n" + line
            rows.append({"doc_id": "TOBRFV-2026", "chunk_id": f"TOBRFV-2026-{len(rows) + 1:03d}", "page": 0,
                         "source_title": "ToBRFV(토마토갈색주름과실바이러스) 웹 조사 자료 (2026-11-18)", "text": text,
                         "crop": "tomato", "cultivation": ["common"], "domain": ["pest"]})
            para = []
        elif line.strip() and not line.startswith(("#", "- ")):
            para.append(line.strip())
        elif not line.strip():
            pass
    print(f"TOBRFV-2026: {len(rows)} chunks")
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for doc in DOCS:
        reader = pypdf.PdfReader(ROOT / "data" / doc["file"])
        pages = doc["pages"] or range(1, len(reader.pages) + 1)
        n = 0
        for page in pages:
            text = clean(reader.pages[page - 1].extract_text() or "")
            if len(text) < 30:
                continue
            for piece in split(text):
                n += 1
                rows.append({
                    "doc_id": doc["doc_id"], "chunk_id": f"{doc['doc_id']}-{n:03d}", "page": page,
                    "source_title": doc["title"], "text": piece, "crop": "tomato",
                    "cultivation": tags(piece, CULTIVATION_WORDS), "domain": tags(piece, DOMAIN_WORDS),
                })
        print(f"{doc['doc_id']}: {n} chunks")
    rows += tobrfv_chunks()
    if CURATED.exists():
        curated = [json.loads(line) for line in CURATED.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows += curated
        print(f"curated: {len(curated)} chunks")
    with OUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"→ {OUT} ({len(rows)} chunks)")


if __name__ == "__main__":
    main()
