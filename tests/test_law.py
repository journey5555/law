"""국가법령정보센터 API 테스트"""

import os
from unittest.mock import patch

import pytest

from clients.law_client import LawApiError, format_jo, get_eflaw, search_eflaw

SAMPLE_SUCCESS = {
    "LawSearch": {
        "target": "eflaw",
        "키워드": "자동차관리법",
        "totalCnt": "1",
        "page": "1",
        "law": {"법령명한글": "자동차관리법", "법령ID": "001234"},
    }
}

SAMPLE_ERROR = {
    "result": "사용자 정보 검증에 실패하였습니다.",
    "msg": "IP주소 등록 필요",
}

SAMPLE_SERVICE = {
    "LawService": {
        "법령ID": "001234",
        "법령명_한글": "자동차관리법",
        "조문": [{"조문번호": "1", "조문제목": "목적", "조문내용": "..."}],
    }
}


class TestFormatJo:
    def test_format_jo(self):
        assert format_jo(2) == "000200"
        assert format_jo(10, 2) == "001002"


class TestSearchEflaw:
    def test_parse_success(self):
        with patch("clients.law_client.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = SAMPLE_SUCCESS
            mock_get.return_value.raise_for_status = lambda: None

            result = search_eflaw(query="자동차관리법", oc="test")

        assert result["total_cnt"] == 1
        assert result["laws"][0]["법령명한글"] == "자동차관리법"

    def test_auth_error(self):
        with patch("clients.law_client.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = SAMPLE_ERROR
            mock_get.return_value.raise_for_status = lambda: None

            with pytest.raises(LawApiError, match="사용자 정보 검증"):
                search_eflaw(oc="invalid")


class TestGetEflaw:
    def test_get_by_law_id(self):
        with patch("clients.law_client.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = SAMPLE_SERVICE
            mock_get.return_value.raise_for_status = lambda: None

            result = get_eflaw(law_id="001234", oc="test")

        assert result["law_id"] == "001234"
        assert len(result["articles"]) == 1


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("LAW_API_OC"), reason="LAW_API_OC 미설정")
class TestLiveLaw:
    def test_search(self):
        result = search_eflaw(query="자동차관리법", display=1)
        assert isinstance(result["laws"], list)
