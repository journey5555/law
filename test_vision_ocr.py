"""vision OCR 테스트 — PDF 1페이지 → base64 → Agent invoke"""
import base64
import sys
from pathlib import Path

import fitz  # pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from clients.agent_client import invoke_agent
from config import PHARMA_KNOWLEDGE_AGENT_ID, PHARMA_KNOWLEDGE_API_KEY

PDF_PATH = Path(__file__).parent / "data" / "pharma_attachments" / "19f3a231_지출결의서_법인차량유지비.pdf"


def pdf_page_to_base64(path: Path, page_num: int = 0, dpi: int = 150) -> str:
    doc = fitz.open(str(path))
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    return base64.b64encode(pix.tobytes("jpeg")).decode()


if __name__ == "__main__":
    print(f"PDF: {PDF_PATH}")
    b64 = pdf_page_to_base64(PDF_PATH)
    print(f"base64 길이: {len(b64):,} chars")

    query = f"data:image/jpeg;base64,{b64}"
    print("Agent 호출 중...")

    try:
        result = invoke_agent(query, agent_id=PHARMA_KNOWLEDGE_AGENT_ID, api_key=PHARMA_KNOWLEDGE_API_KEY)
        print("\n=== 응답 ===")
        print(result)
    except Exception as e:
        print(f"오류: {e}")
