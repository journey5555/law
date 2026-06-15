"""SKT AIP 에이전트 CLI 테스트: python scripts/agent_cli.py [질문]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import sys

import requests

from clients.agent_client import AgentApiError, invoke_agent, stream_agent
from config import AGENT_API_KEY, AGENT_ID, AGENT_VERIFY_SSL


def print_setup_help(error: AgentApiError) -> None:
    print(f"API 오류: {error}")
    if error.status_code == 401:
        print("\n  [해결] SKT AIP 콘솔에서 API 키 발급 → .env AGENT_API_KEY")
    elif error.status_code == 403:
        print("\n  [해결] API 키 형식 확인 (Bearer {API_KEY})")


def main():
    if not AGENT_API_KEY:
        print("⚠  .env에 AGENT_API_KEY를 설정하세요.")
        print(f"   에이전트 ID: {AGENT_ID}")
        return

    message = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "근로기준법이 뭐야?"

    print(f"=== 에이전트 호출 ===\n질문: {message}")
    if not AGENT_VERIFY_SSL:
        print("(SSL 검증 비활성화)")

    try:
        result = invoke_agent(message)
    except requests.exceptions.SSLError:
        print("SSL 오류 → .env AGENT_VERIFY_SSL=false")
        return
    except AgentApiError as e:
        print_setup_help(e)
        return

    print(f"\n--- 답변 ---\n{result['content']}")
    if result.get("run_id"):
        print(f"\n(run_id: {result['run_id']})")

    print("\n=== 스트리밍 ===")
    try:
        chunks = []
        for line in stream_agent(message):
            if '"final_result"' not in line:
                continue
            try:
                data = json.loads(line.split("data:", 1)[-1].strip())
                text = data.get("final_result", "")
                if text:
                    chunks.append(text)
                    print(text, end="", flush=True)
            except (json.JSONDecodeError, IndexError):
                pass
        if chunks:
            print()
        else:
            print("(스트리밍 파싱 실패)")
    except AgentApiError as e:
        print(f"스트리밍 오류: {e}")


if __name__ == "__main__":
    main()
