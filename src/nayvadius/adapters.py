from abc import ABC, abstractmethod
import json
import os
import urllib.parse
import urllib.request

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


class ReadwiseReaderAdapter(DocumentAdapter):
    """Read Reader documents through the Readwise Reader v3 API.

    Requires READWISE_ACCESS_TOKEN. Optional:
    READWISE_LOCATION (new/later/shortlist/archive/feed)
    READWISE_LIMIT (maximum documents per run; 0 means all pages)
    """

    def __init__(self, token=None, location=None, limit=0):
        self.token = token or os.getenv("READWISE_ACCESS_TOKEN", "")
        self.location = location or os.getenv("READWISE_LOCATION", "archive")
        self.limit = int(limit or os.getenv("READWISE_LIMIT", "0"))
        if not self.token:
            raise RuntimeError("READWISE_ACCESS_TOKEN is required")

    def load(self) -> list[Document]:
        docs = []
        url = "https://readwise.io/api/v3/list/"
        params = {"location": self.location}
        while url:
            query = urllib.parse.urlencode(params)
            request_url = url + ("&" if "?" in url else "?") + query if params else url
            req = urllib.request.Request(
                request_url,
                headers={
                    "Authorization": f"Token {self.token}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.load(response)

            for item in payload.get("results", []):
                doc_id = str(item.get("id", "")).strip()
                content = str(item.get("content") or "").strip()
                if not doc_id or not content:
                    continue
                title = str(item.get("title") or doc_id)
                source = str(item.get("source") or item.get("site_name") or "readwise")
                metadata = {
                    "url": item.get("url"),
                    "source_url": item.get("source_url"),
                    "author": item.get("author"),
                    "category": item.get("category"),
                    "tags": item.get("tags"),
                    "location": item.get("location"),
                    "published_date": item.get("published_date"),
                    "updated_at": item.get("updated_at"),
                }
                docs.append(Document(doc_id, title, content, source, metadata))
                if self.limit and len(docs) >= self.limit:
                    return docs[: self.limit]

            url = payload.get("next")
            params = {}

        return docs


def load_documents(adapter: DocumentAdapter) -> list[Document]:
    return adapter.load()
