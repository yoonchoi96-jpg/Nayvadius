from .io import load_jsonl
from .processor import process_document, parse_llm
from .store import upsert_document, save_result
from .db import cache_get, cache_put, connect
from .providers import LLMProvider
from .writer import write_markdown, write_entities
class Engine:
 def __init__(self,output_path='output'):
  self.output=output_path
  self.llm=LLMProvider()
 def run(self,input_path):
  processed=skipped=errors=0
  for doc in load_jsonl(input_path):
   try:
    if not upsert_document(doc): skipped+=1; continue
    result=None
    if self.llm.key:
     key=self.llm.cache_key(doc.title,doc.content); obj=cache_get(key)
     if obj is None: obj=self.llm.analyze(doc.title,doc.content); cache_put(key,obj) if obj else None
     if obj: result=parse_llm(obj,doc)
    if result is None: result=process_document(doc)
    save_result(result); write_markdown(result,self.output); write_entities(result.entities,self.output); processed+=1
   except Exception as exc:
    errors+=1
    with connect() as db: db.execute("UPDATE documents SET status='error' WHERE id=?",(doc.id,))
    print('ERROR',doc.id,exc)
  return {'processed':processed,'skipped':skipped,'errors':errors}
