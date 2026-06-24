import os
from dotenv import load_dotenv

load_dotenv(override=True)

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
VECTOR_STORE_ID = os.environ["VECTOR_STORE_ID"]

ZENDESK_BASE_URL = os.getenv("ZENDESK_BASE_URL", "https://support.optisigns.com")
ZENDESK_LOCALE = os.getenv("ZENDESK_LOCALE", "en-us")

ARTICLES_DIR = os.getenv("ARTICLES_DIR", "articles")
STATE_PATH = os.getenv("STATE_PATH", "state/articles.json")

MIN_ARTICLES = int(os.getenv("MIN_ARTICLES", "30"))
PER_PAGE = 100
