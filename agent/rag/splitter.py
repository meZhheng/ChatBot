from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.utils.config_handler import rag_config


class DocumentSplitter:
    def __init__(self):
        splitter_config = rag_config.get("text_splitter", {})

        self.min_split_length = splitter_config.get("min_split_length", 500)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=splitter_config.get("chunk_size", 1000),
            chunk_overlap=splitter_config.get("chunk_overlap", 200),
            separators=splitter_config.get("separators", ["\n\n", "\n", " ", ""]),
            length_function=len,
        )

    def split(self, text: str) -> list[str]:
        if len(text) > self.min_split_length:
            return self.splitter.split_text(text)
        return [text]
