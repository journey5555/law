"""법령 API 데모: python scripts/law_demo.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clients.law_client import LawApiError, get_eflaw, search_eflaw
from config import LAW_API_OC


def main():
    if not LAW_API_OC:
        print("⚠  .env에 LAW_API_OC 설정 필요")
        return

    print("=== 법령 검색: 자동차관리법 ===")
    try:
        result = search_eflaw(query="자동차관리법", display=5)
    except LawApiError as e:
        print(f"API 오류: {e}")
        if e.raw.get("msg"):
            print(e.raw["msg"])
        return

    print(f"검색건수: {result['total_cnt']}건")
    for law in result["laws"]:
        print(f"  [{law.get('법령ID')}] {law.get('법령명한글')}")

    if not result["laws"]:
        return

    detail = get_eflaw(law_id=str(result["laws"][0]["법령ID"]))
    print(f"\n=== 본문: {detail['law_name']} ===")
    print(f"조문 수: {len(detail['articles'])}")


if __name__ == "__main__":
    main()
