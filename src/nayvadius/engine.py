from .io import load_jsonl
from .processor import process_document, parse_llm
from .store import upsert_document, save_result
from .db import cache_get, cache_put, connect, status
from .providers import LLMProvider
from .writer import write_markdown, write_entities
from .graph import write_graph


class Engine:
    def __init__(self, output_path="output"):
        self.output = output_path
        self.llm = LLMProvider()

    def run(self, input_path, offset=0, limit=0):
        return self.run_documents(load_jsonl(input_path), offset=offset, limit=limit)

    def run_documents(self, docs, offset=0, limit=0):
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 0:
            raise ValueError("limit must be >= 0")

        docs = list(docs)
        if offset:
            docs = docs[offset:]
        if limit:
            docs = docs[:limit]

        processed = skipped = errors = 0
        llm_calls = cache_hits = llm_fallbacks = 0

        for doc in docs:
            try:
                if not upsert_document(doc):
                    skipped += 1
                    continue

                result = None
                if self.llm.key:
                    try:
                        key = self.llm.cache_key(doc.title, doc.content)
                        obj = cache_get(key)
                        if obj is not None:
                            cache_hits += 1
                        else:
                            llm_calls += 1
                            obj = self.llm.analyze(doc.title, doc.content)
                            if obj:
                                cache_put(key, obj)
                        if obj:
                            result = parse_llm(obj, doc)
                    except Exception as exc:
                        llm_fallbacks += 1
                        print("LLM fallback", doc.id, exc)

                if result is None:
                    result = process_document(doc)

                save_result(result)
                write_markdown(result, self.output)
                write_entities(result.entities, self.output)
                processed += 1
            except Exception as exc:
                errors += 1
                with connect() as db:
                    db.execute(
                        "UPDATE documents SET status='error' WHERE id=?", (doc.id,)
                    )
                print("ERROR", doc.id, exc)

        with connect() as db:
            write_graph(db, self.output)

        return {
            "selected": len(docs),
            "offset": offset,
            "limit": limit,
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
            "llm_calls": llm_calls,
            "cache_hits": cache_hits,
            "llm_fallbacks": llm_fallbacks,
            "db": status(),
        }
