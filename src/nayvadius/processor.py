import math,re
from .models import Document,Entity,Relation,ProcessedDocument
def process_document(doc: Document) -> ProcessedDocument:
 words=doc.content.split(); names=[]
 for n in re.findall(r"\b[A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})*\b",doc.content):
  if n not in names: names.append(n)
 return ProcessedDocument(doc," ".join(words[:120]),[Entity(n,"Concept",0.5) for n in names[:30]],[f"source/{doc.source}"],[])
def parse_llm(obj: dict,doc: Document)->ProcessedDocument:
 if not isinstance(obj,dict): raise ValueError("LLM payload must be an object")
 def text(v,d=""): return v.strip() if isinstance(v,str) else d
 def confidence(v,d=1.0):
  try: x=float(v)
  except (TypeError,ValueError): return d
  return max(0.0,min(1.0,x)) if math.isfinite(x) else d
 entities=[]
 for raw in obj.get("entities",[]) or []:
  if not isinstance(raw,dict): continue
  name=text(raw.get("name"))
  if not name: continue
  aliases=raw.get("aliases",[]) or []
  if not isinstance(aliases,(list,tuple)): aliases=[]
  entities.append(Entity(name,text(raw.get("entity_type"),"Concept"),confidence(raw.get("confidence")),tuple(str(x).strip() for x in aliases if str(x).strip())))
 relations=[]
 for raw in obj.get("relations",[]) or []:
  if not isinstance(raw,dict): continue
  source,target,relation=text(raw.get("source")),text(raw.get("target")),text(raw.get("relation"))
  if source and target and relation: relations.append(Relation(source,relation,target,confidence(raw.get("confidence"))))
 raw_tags=obj.get("tags",[]) or []; raw_related=obj.get("related_ids",[]) or []
 if not isinstance(raw_tags,(list,tuple)): raw_tags=[]
 if not isinstance(raw_related,(list,tuple)): raw_related=[]
 tags=[str(x).strip() for x in raw_tags if str(x).strip()]; related=[str(x).strip() for x in raw_related if str(x).strip()]
 return ProcessedDocument(doc,text(obj.get("summary"),doc.content[:500]),entities,tags or [f"source/{doc.source}"],related,relations,confidence(obj.get("importance"),0.5),text(obj.get("document_type"),"note"),text(obj.get("translation_ko")))
