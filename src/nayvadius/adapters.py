from abc import ABC, abstractmethod
from .models import Document

class DocumentAdapter(ABC):
    @abstractmethod
    def load(self) -> list[Document]:
        raise NotImplementedError

class JsonlAdapter(DocumentAdapter):
    def __init__(self, path: str):
        self.path = path
    def load(self) -> list[Document]:
        from .io import load_jsonl
        return load_jsonl(self.path)

def load_documents(adapter: DocumentAdapter) -> list[Document]:
    return adapter.load()
