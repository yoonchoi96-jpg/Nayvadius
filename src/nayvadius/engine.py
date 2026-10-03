from .io import load_jsonl
from .processor import process_document
from .store import upsert_document, save_result
from .writer import write_markdown
from .config import settings

def run(input_path="data/input.jsonl", output_path=None) -> int:
    output_path = output_path or settings.output_path
    processed = 0
    for doc in load_jsonl(input_path):
        if not upsert_document(doc):
            continue
        result = process_document(doc)
        save_result(result)
        write_markdown(result, output_path)
        processed += 1
    return processed
