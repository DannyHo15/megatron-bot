from dotenv import load_dotenv

# Load .env (override=True so the .env key wins over any stale shell export).
load_dotenv(override=True)

from openai import OpenAI  # noqa: E402 (must run after load_dotenv)

client = OpenAI()
vs = client.vector_stores.create(name="megatron-sync")
print("VECTOR_STORE_ID=", vs.id)