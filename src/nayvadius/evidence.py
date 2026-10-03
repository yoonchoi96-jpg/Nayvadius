"""On-demand source evidence access.

Abraham owns collection and selection. Nayvadius uses this client only when a
graph claim needs source verification.
"""

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .db import link_relation_evidence, save_evidence


@dataclass(frozen=True)
class Evidence:
    source: str
    document_id: str
    title: str
    content: str
    url: str = ""


class ReadwiseEvidenceClient:
    endpoint = "https://readwise.io/api/v3/list/"

    def __init__(self, token=None):
        self.token = token or os.getenv("READWISE_ACCESS_TOKEN", "")
        if not self.token:
            raise RuntimeError("READWISE_ACCESS_TOKEN is required for evidence lookup")

    def fetch_document(self, document_id: str) -> Evidence | None:
        query = urllib.parse.urlencode({"id": document_id})
        req = urllib.request.Request(
            self.endpoint + "?" + query,
            headers={"Authorization": f"Token {self.token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.load(response)

        results = payload.get("results", [])
        if not results:
            return None
        item = results[0]
        evidence = Evidence(
            source="readwise",
            document_id=str(item.get("id") or document_id),
            title=str(item.get("title") or document_id),
            content=str(item.get("content") or ""),
            url=str(item.get("url") or ""),
        )
        save_evidence(evidence)
        return evidence

    def verify_relation(
        self,
        document_id: str,
        source_name: str,
        relation: str,
        target_name: str,
        evidence_document_id: str,
        status: str = "checked",
    ) -> None:
        if status not in {"checked", "contradicted", "unverified"}:
            raise ValueError("invalid evidence status: " + status)
        link_relation_evidence(
            document_id,
            source_name,
            relation,
            target_name,
            evidence_document_id,
            status,
        )
