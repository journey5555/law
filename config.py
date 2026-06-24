import os
from dotenv import load_dotenv

load_dotenv()

# 국가법령정보센터 Open API
# OC: open.law.go.kr 신청 시 발급 (이메일 ID, 예: g4c@korea.kr → g4c)
LAW_API_OC = os.getenv("LAW_API_OC", "")
LAW_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"

# SKT AIP 에이전트 Gateway
AGENT_ID = os.getenv("AGENT_ID", "")
SUMMARIZE_AGENT_ID      = os.getenv("SUMMARIZE_AGENT_ID",        "")
SUMMARIZE_API_KEY       = os.getenv("SUMMARIZE_API_KEY",          "")
LAW_PREC_AGENT_ID       = os.getenv("LAW_PREC_AGENT_ID",          "")
LAW_PREC_AGENT_API_KEY  = os.getenv("LAW_PREC_AGENT_API_KEY",     "")
LAW_PREC_TEST_AGENT_ID  = os.getenv("LAW_PREC_TEST_AGENT_ID",     "")
LAW_PREC_TEST_AGENT_API_KEY = os.getenv("LAW_PREC_TEST_AGENT_API_KEY", "")
LAW_KEYWORD_AGENT_ID    = os.getenv("LAW_KEYWORD_AGENT_ID",       "")
LAW_KEYWORD_AGENT_API_KEY = os.getenv("LAW_KEYWORD_AGENT_API_KEY", "")

# SKT AIP Knowledge API (Keycloak JWT)
KNOWLEDGE_BASE_URL      = "https://aip.sktai.io/api/v1"
KNOWLEDGE_TOKEN         = os.getenv("KNOWLEDGE_TOKEN", "")
KNOWLEDGE_USER          = os.getenv("KNOWLEDGE_USER", "")
KNOWLEDGE_PASSWORD      = os.getenv("KNOWLEDGE_PASSWORD", "")
KNOWLEDGE_LAW_REPO_ID   = os.getenv("KNOWLEDGE_LAW_REPO_ID", "")
KNOWLEDGE_PREC_REPO_ID  = os.getenv("KNOWLEDGE_PREC_REPO_ID", "")
KNOWLEDGE_SUMM_REPO_ID  = os.getenv("KNOWLEDGE_SUMM_REPO_ID", "")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "https://aip.sktai.io/api/v1/agent_gateway")
AGENT_VERIFY_SSL = os.getenv("AGENT_VERIFY_SSL", "true").lower() in ("1", "true", "yes")

# 채팅 웹 서버
CHAT_HOST = os.getenv("CHAT_HOST", "127.0.0.1")
CHAT_PORT = int(os.getenv("CHAT_PORT", "8080"))

# 로그 (DEBUG, INFO, WARNING)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Pharma Monitor — Gmail OAuth2
PHARMA_ENABLED            = os.getenv("PHARMA_ENABLED", "true").lower() in ("1", "true", "yes")
PHARMA_GMAIL_SCOPES       = ["https://www.googleapis.com/auth/gmail.readonly"]
PHARMA_GMAIL_REDIRECT_URI = os.getenv("PHARMA_GMAIL_REDIRECT_URI", "http://localhost:8080/pharma/oauth/callback")
PHARMA_CHECK_INTERVAL_MIN = int(os.getenv("PHARMA_CHECK_INTERVAL_MINUTES", "30"))