"""
법령/판례 API 테스트 스크립트

사용법:
  python scripts/api_test.py                       # 기본 (근로기준법 검색)
  python scripts/api_test.py 최저임금법            # 법령 검색
  python scripts/api_test.py --prec 부당해고       # 판례 검색
  python scripts/api_test.py --presets             # 추천 법령 전체 확인
  python scripts/api_test.py --presets --check     # 추천 법령 API 존재 여부 확인
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clients.law_client import LawApiError, search_law, search_prec, get_law

PRESETS_FILE = Path(__file__).resolve().parent.parent / "data" / "law_presets.json"

SEP  = "─" * 60
SEP2 = "═" * 60


def fmt_date(s: str) -> str:
    s = str(s or "").replace("-", "")
    if len(s) == 8:
        return f"{s[:4]}.{s[4:6]}.{s[6:]}"
    return s or "-"


def cmd_search_law(query: str, display: int = 10):
    print(f"\n{SEP2}")
    print(f"  법령 검색: '{query}'")
    print(SEP2)
    try:
        result = search_law(query=query, display=display)
    except LawApiError as e:
        print(f"  ✗ API 오류: {e}")
        return

    total = result["total_cnt"]
    laws  = result["laws"]
    print(f"  총 {total}건 (상위 {len(laws)}개 표시)\n")

    if not laws:
        print("  결과 없음")
        return

    for i, law in enumerate(laws, 1):
        name  = law.get("법령명한글", "-")
        lid   = law.get("법령ID", "-")
        dept  = law.get("소관부처명", "-")
        knd   = law.get("법령구분명", "-")
        ef    = fmt_date(law.get("시행일자", ""))
        print(f"  [{i:2}] {name}")
        print(f"       ID={lid}  구분={knd}  소관={dept}  시행={ef}")

    print()


def cmd_search_prec(query: str, display: int = 5):
    print(f"\n{SEP2}")
    print(f"  판례 검색: '{query}'")
    print(SEP2)
    try:
        result = search_prec(query=query, display=display)
    except LawApiError as e:
        print(f"  ✗ API 오류: {e}")
        return

    total = result["total_cnt"]
    precs = result["precs"]
    print(f"  총 {total}건 (상위 {len(precs)}개 표시)\n")

    if not precs:
        print("  결과 없음")
        return

    for i, p in enumerate(precs, 1):
        name   = p.get("사건명", "-")
        case_no= p.get("사건번호", "-")
        court  = p.get("법원명", "-")
        date   = fmt_date(p.get("선고일자", ""))
        print(f"  [{i:2}] {name}")
        print(f"       {case_no}  {court}  {date}")

    print()


def cmd_check_presets(check_api: bool = False):
    if not PRESETS_FILE.exists():
        print("  ✗ data/law_presets.json 파일이 없습니다.")
        return

    presets = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    print(f"\n{SEP2}")
    print(f"  인사 관련 추천 법령 ({len(presets)}개)")
    print(SEP2)

    by_cat: dict = {}
    for p in presets:
        by_cat.setdefault(p["category"], []).append(p["name"])

    for cat, names in by_cat.items():
        print(f"\n  [{cat}]")
        for name in names:
            if check_api:
                try:
                    res = search_law(query=name, display=3)
                    matched = next(
                        (l for l in res["laws"] if l.get("법령명한글") == name),
                        res["laws"][0] if res["laws"] else None,
                    )
                    if matched:
                        lid = matched.get("법령ID", "?")
                        ef  = fmt_date(matched.get("시행일자", ""))
                        print(f"    ✓  {name}  (ID={lid}, 시행={ef})")
                    else:
                        print(f"    △  {name}  (API 결과 없음, total={res['total_cnt']})")
                except LawApiError as e:
                    print(f"    ✗  {name}  (오류: {e})")
            else:
                print(f"    •  {name}")

    print()


def main():
    args = sys.argv[1:]

    if "--prec" in args:
        idx = args.index("--prec")
        query = args[idx + 1] if idx + 1 < len(args) else "부당해고"
        cmd_search_prec(query)

    elif "--presets" in args:
        check = "--check" in args
        cmd_check_presets(check_api=check)

    else:
        query = args[0] if args else "근로기준법"
        display = int(args[1]) if len(args) > 1 else 10
        cmd_search_law(query, display)


if __name__ == "__main__":
    main()
