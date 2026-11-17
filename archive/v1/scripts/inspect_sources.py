"""Extract local PDF text with page numbers; never read credential files."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools' / 'pdf'))
from pypdf import PdfReader

destination = ROOT / 'outputs' / 'source_review'
destination.mkdir(parents=True, exist_ok=True)
for path in sorted((ROOT / 'data').glob('*.pdf')):
    reader = PdfReader(path)
    pages = [(page.extract_text() or '').replace('\x00', ' ') for page in reader.pages]
    target = destination / (path.stem + '.txt')
    target.write_text('\n\n'.join(f'--- PDF PAGE {i} ---\n{text}' for i, text in enumerate(pages, 1)), encoding='utf-8')
    print(json.dumps({'file': path.name, 'pages': len(pages), 'characters': sum(map(len, pages))}, ensure_ascii=False))
