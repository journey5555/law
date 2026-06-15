"""프로젝트 루트를 sys.path에 추가 (어디서 실행해도 import 가능하게)"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
