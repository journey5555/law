"""국가법령정보센터 시행일 법령 검색 API 클라이언트"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import LAW_API_OC, LAW_SEARCH_URL, LAW_SERVICE_URL

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist=[404, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update(_HEADERS)
    return s

_http = _session()


class LawApiError(Exception):
    """API 오류 (인증 실패, 파라미터 오류 등)"""

    def __init__(self, message: str, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw or {}


def _require_oc(oc: str | None) -> str:
    auth = oc or LAW_API_OC
    if not auth:
        raise LawApiError(
            "LAW_API_OC가 설정되지 않았습니다. .env 파일에 OC 값을 입력하세요."
        )
    return auth


def _check_api_error(data: dict[str, Any], root_key: str) -> None:
    if "result" in data and root_key not in data:
        raise LawApiError(data.get("result", "API 오류"), raw=data)


def _normalize_list(value: Any) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    return []


def search_eflaw(
    *,
    query: str | None = None,
    search: int | None = None,
    nw: str | None = None,
    lid: str | None = None,
    display: int = 20,
    page: int = 1,
    sort: str | None = None,
    ef_yd: str | None = None,
    date: str | None = None,
    anc_yd: str | None = None,
    anc_no: str | None = None,
    rr_cls_cd: str | None = None,
    nb: int | None = None,
    org: str | None = None,
    knd: str | None = None,
    gana: str | None = None,
    pop_yn: str | None = None,
    oc: str | None = None,
    response_type: str = "JSON",
) -> dict[str, Any]:
    """
    시행일 법령 목록 검색 (target=eflaw)

    Returns:
        {
            "target": str,
            "keyword": str,
            "section": str,
            "total_cnt": int,
            "page": int,
            "laws": list[dict],
        }
    """
    auth = _require_oc(oc)

    params: dict[str, Any] = {
        "OC": auth,
        "target": "eflaw",
        "type": response_type,
        "display": display,
        "page": page,
    }

    optional_params = {
        "query": query,
        "search": search,
        "nw": nw,
        "LID": lid,
        "sort": sort,
        "efYd": ef_yd,
        "date": date,
        "ancYd": anc_yd,
        "ancNo": anc_no,
        "rrClsCd": rr_cls_cd,
        "nb": nb,
        "org": org,
        "knd": knd,
        "gana": gana,
        "popYn": pop_yn,
    }
    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    response = _http.get(LAW_SEARCH_URL, params=params, timeout=15)
    response.raise_for_status()

    if response_type.upper() != "JSON":
        return {"raw": response.text, "params": params}

    data = response.json()
    return _parse_search_response(data)


def format_jo(article: int, sub: int = 0) -> str:
    """조번호를 API 형식으로 변환 (2조 → 000200, 10조의2 → 001002)"""
    return f"{article:04d}{sub:02d}"


def get_eflaw(
    *,
    law_id: str | None = None,
    mst: str | None = None,
    ef_yd: int | None = None,
    jo: str | None = None,
    chr_cls_cd: str | None = None,
    oc: str | None = None,
    response_type: str = "JSON",
) -> dict[str, Any]:
    """
    시행일 법령 본문 조회 (target=eflaw, lawService.do)

    ID 또는 MST 중 하나는 필수.
    - law_id: 현행 법령 본문 조회 (ef_yd 무시)
    - mst + ef_yd: 특정 시행일 버전 조회
    - jo: 조번호 API 형식 문자열 (format_jo(2) → "000200")
    """
    if not law_id and not mst:
        raise LawApiError("ID 또는 MST 중 하나는 반드시 입력해야 합니다.")
    if mst and ef_yd is None:
        raise LawApiError("MST로 조회할 때는 ef_yd(시행일자)가 필수입니다.")

    auth = _require_oc(oc)
    params: dict[str, Any] = {
        "OC": auth,
        "target": "eflaw",
        "type": response_type,
    }

    if law_id:
        params["ID"] = law_id
    else:
        params["MST"] = mst
        params["efYd"] = ef_yd

    if jo is not None:
        params["JO"] = jo
    if chr_cls_cd:
        params["chrClsCd"] = chr_cls_cd

    response = _http.get(LAW_SERVICE_URL, params=params, timeout=15)
    response.raise_for_status()

    if response_type.upper() != "JSON":
        return {"raw": response.text, "params": params}

    data = response.json()
    return _parse_service_response(data)


def search_law(
    *,
    query: str | None = None,
    search: int | None = None,
    display: int = 20,
    page: int = 1,
    sort: str | None = None,
    org: str | None = None,
    knd: str | None = None,
    gana: str | None = None,
    oc: str | None = None,
    response_type: str = "JSON",
) -> dict[str, Any]:
    """
    현행법령 목록 검색 (target=law)

    Returns:
        {
            "target": str,
            "keyword": str,
            "total_cnt": int,
            "page": int,
            "laws": list[dict],
        }
    """
    auth = _require_oc(oc)

    params: dict[str, Any] = {
        "OC": auth,
        "target": "law",
        "type": response_type,
        "display": display,
        "page": page,
    }

    optional_params = {
        "query": query,
        "search": search,
        "sort": sort,
        "org": org,
        "knd": knd,
        "gana": gana,
    }
    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    response = _http.get(LAW_SEARCH_URL, params=params, timeout=15)
    response.raise_for_status()

    if response_type.upper() != "JSON":
        return {"raw": response.text, "params": params}

    return _parse_search_response(response.json())


def get_law(
    *,
    law_id: str | None = None,
    mst: str | None = None,
    jo: str | None = None,
    oc: str | None = None,
    response_type: str = "JSON",
) -> dict[str, Any]:
    """
    현행법령 본문 조회 (target=law)

    ID 또는 MST 중 하나는 필수.
    - jo: 조번호 API 형식 문자열 (format_jo(2) → "000200")
    """
    if not law_id and not mst:
        raise LawApiError("ID 또는 MST 중 하나는 반드시 입력해야 합니다.")

    auth = _require_oc(oc)
    params: dict[str, Any] = {
        "OC": auth,
        "target": "law",
        "type": response_type,
    }

    if law_id:
        params["ID"] = law_id
    else:
        params["MST"] = mst

    if jo is not None:
        params["JO"] = jo

    response = _http.get(LAW_SERVICE_URL, params=params, timeout=15)
    response.raise_for_status()

    if response_type.upper() != "JSON":
        return {"raw": response.text, "params": params}

    return _parse_service_response(response.json())


def search_prec(
    *,
    query: str | None = None,
    search: int | None = None,   # 1=판례명(기본), 2=본문
    jo: str | None = None,       # 참조법령명 (예: "최저임금법")
    display: int = 20,
    page: int = 1,
    sort: str | None = None,
    oc: str | None = None,
    response_type: str = "JSON",
) -> dict[str, Any]:
    """
    판례 목록 검색 (target=prec)

    Returns:
        {
            "keyword": str,
            "total_cnt": int,
            "page": int,
            "precs": list[dict],
        }
    """
    auth = _require_oc(oc)
    params: dict[str, Any] = {
        "OC": auth,
        "target": "prec",
        "type": response_type,
        "display": min(display, 100),
        "page": page,
    }
    if query is not None:
        params["query"] = query
    if search is not None:
        params["search"] = search
    if jo is not None:
        params["JO"] = jo
    if sort is not None:
        params["sort"] = sort

    response = _http.get(LAW_SEARCH_URL, params=params, timeout=15)
    response.raise_for_status()

    if response_type.upper() != "JSON":
        return {"raw": response.text, "params": params}

    return _parse_prec_search_response(response.json())


def get_prec(
    *,
    prec_id: str,
    oc: str | None = None,
    response_type: str = "JSON",
) -> dict[str, Any]:
    """
    판례 본문 조회 (target=prec)

    Returns:
        {
            "prec_id": str,
            "case_no": str,
            "case_name": str,
            "court": str,
            "date": str,
            "case_type": str,
            "issues": str,       # 판시사항
            "summary": str,      # 판결요지
            "ref_articles": str, # 참조조문
            "ref_cases": str,    # 참조판례
            "content": str,      # 판례 전문
        }
    """
    auth = _require_oc(oc)
    params: dict[str, Any] = {
        "OC": auth,
        "target": "prec",
        "type": response_type,
        "ID": prec_id,
    }

    response = _http.get(LAW_SERVICE_URL, params=params, timeout=15)
    response.raise_for_status()

    if response_type.upper() != "JSON":
        return {"raw": response.text, "params": params}

    return _parse_prec_service_response(response.json())


def _parse_prec_search_response(data: dict[str, Any]) -> dict[str, Any]:
    _check_api_error(data, "PrecSearch")
    root = data.get("PrecSearch", data)
    return {
        "keyword": root.get("키워드", ""),
        "total_cnt": int(root.get("totalCnt", 0) or 0),
        "page": int(root.get("page", 1) or 1),
        "precs": _normalize_list(root.get("prec", [])),
        "raw": data,
    }


def _parse_prec_service_response(data: dict[str, Any]) -> dict[str, Any]:
    _check_api_error(data, "PrecService")
    root = data.get("PrecService", data)
    return {
        "prec_id": root.get("판례정보일련번호", ""),
        "case_no": root.get("사건번호", ""),
        "case_name": root.get("사건명", ""),
        "court": root.get("법원명", ""),
        "date": root.get("선고일자", ""),
        "case_type": root.get("사건종류명", ""),
        "judgment_type": root.get("판결유형", ""),
        "issues": root.get("판시사항", ""),
        "summary": root.get("판결요지", ""),
        "ref_articles": root.get("참조조문", ""),
        "ref_cases": root.get("참조판례", ""),
        "content": root.get("판례내용", ""),
        "raw": data,
    }


def _parse_search_response(data: dict[str, Any]) -> dict[str, Any]:
    _check_api_error(data, "LawSearch")

    root = data.get("LawSearch", data)
    laws = _normalize_list(root.get("law", []))

    return {
        "target": root.get("target", ""),
        "keyword": root.get("키워드", root.get("keyword", "")),
        "section": root.get("section", ""),
        "total_cnt": int(root.get("totalCnt", 0) or 0),
        "page": int(root.get("page", 1) or 1),
        "laws": laws,
        "raw": data,
    }


def _parse_service_response(data: dict[str, Any]) -> dict[str, Any]:
    _check_api_error(data, "LawService")

    root = data.get("LawService", data.get("법령", data))
    if "법령" in data:
        root = data["법령"]

    info = root.get("기본정보", root)
    jo_root = root.get("조문", {})
    if isinstance(jo_root, list):
        articles = jo_root
    else:
        articles = _normalize_list(jo_root.get("조문단위", jo_root.get("article", [])))

    return {
        "law_id": info.get("법령ID", root.get("법령ID", "")),
        "law_name": info.get("법령명_한글", root.get("법령명_한글", root.get("법령명한글", ""))),
        "department": info.get("소관부처명", ""),
        "promulgation_date": info.get("공포일자", root.get("공포일자", "")),
        "enforcement_date": info.get("시행일자", root.get("시행일자", "")),
        "articles": articles,
        "raw": data,
    }
