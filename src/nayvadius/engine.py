import json
from .io import load_jsonl
from .processor import process_document, parse_llm
from .models import Vocabulary
from .store import upsert_document, save_result, result_is_current, link_vocabulary, reconcile_all_vocabularies, reconcile_document_vocabularies
from .db import cache_get, cache_put, connect, status, prune_orphan_entities, record_failure, clear_failure
from .providers import LLMProvider
from .writer import write_markdown, write_entities, write_entities_from_db, write_entity_moc, write_vocabulary_from_db, write_vocabulary_moc, write_hsk_mocs
from .graph import write_graph


class Engine:
    def __init__(self, output_path="output"):
        self.output = output_path
        self.llm = LLMProvider()

    def run(self, input_path, offset=0, limit=0):
        return self.run_documents(load_jsonl(input_path), offset=offset, limit=limit)

    def _select(self, items, offset, limit):
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 0:
            raise ValueError("limit must be >= 0")
        items = list(items)
        if offset:
            items = items[offset:]
        if limit:
            items = items[:limit]
        return items

    def _persist(self, result, stats):
        doc = result.document
        try:
            if stats.get("force_refresh", False) and result_is_current(result):
                clear_failure(doc.id)
                stats["skipped"] += 1
                return
            if not upsert_document(doc, force=stats.get("force_refresh", False)):
                clear_failure(doc.id)
                stats["skipped"] += 1
                return
            save_result(result)
            write_markdown(result, self.output)
            write_entities(result.entities, self.output)
            clear_failure(doc.id)
            stats["processed"] += 1
        except Exception as exc:
            stats["errors"] += 1
            record_failure(doc.id, exc)
            with connect() as db:
                db.execute("UPDATE documents SET status='error' WHERE id=?", (doc.id,))
            print("ERROR", doc.id, exc)

    def run_documents(self, docs, offset=0, limit=0):
        docs = self._select(docs, offset, limit)
        stats = {"selected": len(docs), "offset": offset, "limit": limit,
                 "processed": 0, "skipped": 0, "errors": 0,
                 "llm_calls": 0, "cache_hits": 0, "llm_fallbacks": 0}

        for doc in docs:
            try:
                result = None
                if self.llm.key:
                    try:
                        key = self.llm.cache_key(doc.title, doc.content)
                        obj = cache_get(key)
                        if obj is not None:
                            stats["cache_hits"] += 1
                        else:
                            stats["llm_calls"] += 1
                            obj = self.llm.analyze(doc.title, doc.content)
                            if obj:
                                cache_put(key, obj)
                        if obj:
                            result = parse_llm(obj, doc)
                    except Exception as exc:
                        stats["llm_fallbacks"] += 1
                        print("LLM fallback", doc.id, exc)
                if result is None:
                    result = process_document(doc)
                self._persist(result, stats)
            except Exception as exc:
                stats["errors"] += 1
                record_failure(doc.id, exc)
                print("ERROR", doc.id, exc)

        return self._finish(stats)

    def run_processed(self, records, offset=0, limit=0):
        records = self._select(records, offset, limit)
        stats = {"selected": len(records), "offset": offset, "limit": limit,
                 "processed": 0, "skipped": 0, "errors": 0,
                 "llm_calls": 0, "cache_hits": 0, "llm_fallbacks": 0,
                 "abraham_records": len(records), "force_refresh": True}
        for result in records:
            self._persist(result, stats)

        # Deterministic Abel vocabulary linking; zero LLM/API calls.
        try:
            with connect() as db:
                pending = []
                for result in records:
                    metadata = result.document.metadata if isinstance(result.document.metadata, dict) else {}
                    explicit = metadata.get("vocabulary_ids", []) if isinstance(metadata, dict) else []
                    pending.append((result.document.id, result.document.content, explicit))
            stats["vocabulary_links"] = reconcile_all_vocabularies()
            stats["document_vocabulary_links"] = reconcile_document_vocabularies(pending)
        except Exception as exc:
            stats["errors"] += 1
            print("Vocabulary/document relink error", exc)

        return self._finish(stats)

    def run_vocabulary(self, vocabularies, offset=0, limit=0):
        vocabularies = self._select(vocabularies, offset, limit)
        stats = {"selected": len(vocabularies), "offset": offset, "limit": limit, "processed": 0, "links": 0}
        for vocabulary in vocabularies:
            explicit = vocabulary.metadata.get("entities", []) if isinstance(vocabulary.metadata, dict) else []
            try:
                stats["links"] += len(link_vocabulary(vocabulary, explicit))
                stats["processed"] += 1
            except Exception as exc:
                stats.setdefault("errors", 0)
                stats["errors"] += 1
                print("ERROR vocabulary", vocabulary.id, exc)

        # A newly imported Abel batch must immediately become visible to
        # existing Abraham documents. This is deterministic and uses no LLM/API.
        try:
            with connect() as db:
                documents = db.execute("SELECT id,content FROM documents").fetchall()
            stats["document_vocabulary_links"] = reconcile_document_vocabularies(
                [(doc_id, content, ()) for doc_id, content in documents]
            )
        except Exception as exc:
            stats.setdefault("errors", 0)
            stats["errors"] += 1
            print("Document/vocabulary reconciliation error", exc)
        return self._finish(stats)

    def _finish(self, stats):
        prune_orphan_entities()
        with connect() as db:
            write_graph(db, self.output)
            write_entities_from_db(db, self.output)
            write_entity_moc(db, self.output)
            write_vocabulary_from_db(db, self.output)
            write_vocabulary_moc(db, self.output)
            write_hsk_mocs(db, self.output)
        stats["db"] = status()
        return stats
