"""법령 조회: python scripts/law_query.py [법령명] [조문수]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clients.law_client import LawApiError, get_eflaw, search_eflaw

QUERY = sys.argv[1] if len(sys.argv) > 1 else "근로기준법"
MAX_ARTICLES = int(sys.argv[2]) if len(sys.argv) > 2 else 15


def main():
    try:
        result = search_eflaw(query=QUERY, display=5)
    except LawApiError as e:
        print(f"API 오류: {e}")
        if e.raw.get("msg"):
            print(e.raw["msg"])
        return

    print(f"=== '{QUERY}' ({result['total_cnt']}건) ===")
    for law in result["laws"]:
        print(f"  ID={law.get('법령ID')} | {law.get('법령명한글')} | {law.get('현행연혁코드', '')}")

    if not result["laws"]:
        return

    detail = get_eflaw(law_id=str(result["laws"][0]["법령ID"]))
    print(f"\n법령명: {detail['law_name']} | 조문 {len(detail['articles'])}개\n")

    for art in detail["articles"][:MAX_ARTICLES]:
        num = art.get("조문번호", "")
        title = art.get("조문제목", "")
        content = art.get("조문내용", "").replace("\n", " ")
        print(f"[{num}조] {title}\n  {content[:300]}\n")


if __name__ == "__main__":
    main()
