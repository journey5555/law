"""채팅 웹 서버 실행: python run.py"""

import bootstrap  # noqa: F401

from web.app import start_server

if __name__ == "__main__":
    start_server()
