import os
from dotenv import load_dotenv

load_dotenv()


class MemoryConfig:
    def __init__(self):
        self.chroma_persist_dir = "data/chroma"
        os.makedirs(self.chroma_persist_dir, exist_ok=True)

        self.collection_name = "knowledge_base"

        self.qwen_api_key = os.getenv("DASHSCOPE_API_KEY")
        self.qwen_base_url = os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.qwen_chat_model = os.getenv("QWEN_CHAT_MODEL", "qwen3.6-flash")
        self.qwen_embedding_model = os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4")

        self.chunk_size = 1000
        self.chunk_overlap = 200
        self.separators = ["\n\n", "\n", " ", ""]
        self.min_split_length = 500
