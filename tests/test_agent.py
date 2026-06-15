"""SKT AIP 에이전트 API 테스트"""

import os
from unittest.mock import patch

import pytest

from clients.agent_client import AgentApiError, build_invoke_body, invoke_agent

SAMPLE_RESPONSE = {
    "config": {"run_id": "test-run-id"},
    "output": {
        "content": "안녕하세요! 무엇을 도와드릴까요?",
        "messages": [],
        "additional_kwargs": {},
    },
}


class TestBuildBody:
    def test_build_invoke_body(self):
        body = build_invoke_body("근로기준법이 뭐야?")
        assert body["input"]["messages"][0]["content"] == "근로기준법이 뭐야?"
        assert body["input"]["messages"][0]["type"] == "human"


class TestInvokeAgent:
    def test_invoke_success(self):
        with patch("clients.agent_client.requests.post") as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.ok = True
            mock_resp.status_code = 200
            mock_resp.json.return_value = SAMPLE_RESPONSE

            result = invoke_agent("hello", api_key="test-key")

        assert result["content"] == "안녕하세요! 무엇을 도와드릴까요?"
        assert result["run_id"] == "test-run-id"

    def test_missing_api_key(self):
        with patch("clients.agent_client.AGENT_API_KEY", ""):
            with pytest.raises(AgentApiError, match="AGENT_API_KEY"):
                invoke_agent("hello")

    def test_auth_error(self):
        with patch("clients.agent_client.requests.post") as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.ok = False
            mock_resp.status_code = 401
            mock_resp.json.return_value = {"detail": "401: API-KEY not found"}
            mock_resp.text = ""

            with pytest.raises(AgentApiError, match="API-KEY"):
                invoke_agent("hello", api_key="bad-key")


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("AGENT_API_KEY"), reason="AGENT_API_KEY 미설정")
class TestLiveAgent:
    def test_invoke_live(self):
        result = invoke_agent("근로기준법에 대해 한 줄로 설명해줘")
        assert result["content"]
