"""SKT AIP 에이전트 Gateway API 클라이언트"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

import requests
import urllib3

from config import AGENT_API_KEY, AGENT_BASE_URL, AGENT_ID, AGENT_VERIFY_SSL, LOG_LEVEL

if not AGENT_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("agent_api")


class AgentApiError(Exception):
    """에이전트 API 오류"""

    def __init__(self, message: str, status_code: int | None = None, raw: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw


def _require_api_key(api_key: str | None = None) -> str:
    key = api_key or AGENT_API_KEY
    if not key:
        raise AgentApiError(
            "AGENT_API_KEY가 설정되지 않았습니다. .env 파일에 API 키를 입력하세요."
        )
    return key


def _agent_url(path: str, agent_id: str | None = None) -> str:
    aid = agent_id or AGENT_ID
    return f"{AGENT_BASE_URL.rstrip('/')}/{aid}{path}"


def build_invoke_body(
    message: str,
    *,
    config: dict | None = None,
    kwargs: dict | None = None,
    additional_kwargs: dict | None = None,
) -> dict[str, Any]:
    """OpenAPI InvokeRequestSchema 형식의 요청 본문 생성"""
    return {
        "config": config or {},
        "input": {
            "messages": [{"content": message, "type": "human"}],
            "additional_kwargs": additional_kwargs or {},
        },
        "kwargs": kwargs or {},
    }


def invoke_agent(
    message: str,
    *,
    agent_id: str | None = None,
    api_key: str | None = None,
    router_path: str = "",
    config: dict | None = None,
    kwargs: dict | None = None,
) -> dict[str, Any]:
    """
    에이전트 동기 호출 (POST /invoke)

    Returns:
        API 응답 JSON (output.content에 답변 텍스트)
    """
    key = _require_api_key(api_key)
    url = _agent_url("/invoke", agent_id)
    params = {"router_path": router_path} if router_path else None
    body = build_invoke_body(message, config=config, kwargs=kwargs)

    logger.info("→ POST %s", url)
    logger.info("  질문: %s", message[:200] + ("..." if len(message) > 200 else ""))
    started = time.perf_counter()

    response = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {key}"},
        params=params,
        timeout=120,
        verify=AGENT_VERIFY_SSL,
    )

    elapsed = time.perf_counter() - started

    if not response.ok:
        logger.error("← HTTP %s (%.1fs) %s", response.status_code, elapsed, _extract_error(response))
        raise AgentApiError(
            _extract_error(response),
            status_code=response.status_code,
            raw=_safe_json(response),
        )

    data = response.json()
    run_id = data.get("config", {}).get("run_id")
    content = _extract_content(data)
    logger.info("← HTTP 200 (%.1fs) run_id=%s", elapsed, run_id)
    logger.info("  답변: %s", content[:200] + ("..." if len(content) > 200 else ""))

    return {
        "content": content,
        "run_id": run_id,
        "raw": data,
    }


def stream_agent(
    message: str,
    *,
    agent_id: str | None = None,
    api_key: str | None = None,
    router_path: str = "",
) -> Iterator[str]:
    """에이전트 스트리밍 호출 (POST /stream) — SSE/청크 텍스트 yield"""
    key = _require_api_key(api_key)
    url = _agent_url("/stream", agent_id)
    params = {"router_path": router_path} if router_path else None
    body = build_invoke_body(message)

    logger.info("→ POST %s (stream)", url)
    logger.info("  질문: %s", message[:200] + ("..." if len(message) > 200 else ""))
    started = time.perf_counter()

    try:
        response = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            params=params,
            timeout=(30, 300),
            stream=True,
            verify=AGENT_VERIFY_SSL,
        )
    except requests.exceptions.Timeout as e:
        raise AgentApiError("에이전트 연결 시간 초과 (30초)") from e
    except requests.exceptions.ConnectionError as e:
        raise AgentApiError(f"에이전트 연결 오류: {e}") from e

    elapsed = time.perf_counter() - started

    if not response.ok:
        logger.error("← HTTP %s (%.1fs) %s", response.status_code, elapsed, _extract_error(response))
        raise AgentApiError(
            _extract_error(response),
            status_code=response.status_code,
            raw=_safe_json(response),
        )

    logger.info("← HTTP 200 (stream 시작, %.1fs)", elapsed)

    full_response = []
    try:
        for line in response.iter_lines(decode_unicode=True):
            if line:
                full_response.append(line)
                yield line
    except requests.exceptions.Timeout as e:
        raise AgentApiError("스트리밍 응답 시간 초과 (300초)") from e
    except requests.exceptions.ConnectionError as e:
        raise AgentApiError(f"스트리밍 연결 끊김: {e}") from e
    finally:
        logger.debug("  스트림 원문: %s", "\n".join(full_response)[:500])


def stream_agent_tokens(
    message: str,
    *,
    agent_id: str | None = None,
    api_key: str | None = None,
    router_path: str = "",
) -> Iterator[str]:
    """스트리밍 응답에서 final_result 텍스트만 추출"""
    collected = []
    for line in stream_agent(
        message, agent_id=agent_id, api_key=api_key, router_path=router_path
    ):
        if '"final_result"' not in line or "data:" not in line:
            continue
        try:
            payload = json.loads(line.split("data:", 1)[-1].strip())
            token = payload.get("final_result", "")
            if token:
                collected.append(token)
                yield token
        except (json.JSONDecodeError, IndexError):
            continue
    if collected:
        logger.info("  최종 답변: %s", "".join(collected)[:300])


def _extract_content(data: dict[str, Any]) -> str:
    output = data.get("output", {})
    if isinstance(output, dict):
        content = output.get("content", "")
        if content:
            return str(content)
    return str(data)


def _extract_error(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
        if isinstance(detail, list):
            return str(detail)
        return str(detail)
    except ValueError:
        return response.text or f"HTTP {response.status_code}"


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
