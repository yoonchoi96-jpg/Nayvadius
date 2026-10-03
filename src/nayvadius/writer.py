from pathlib import Path

def safe(s): return ''.join(c if c.isalnum() or c in ' -_' else '_' for c in s).strip()[:120] or 'untitled'
def write_markdown(result,root):
 p=Path(root)/'documents'; p.mkdir(parents=True,exist_ok=True); out=p/(safe(result.document.title)+'.md')
 ents='\n'.join('- [['+e.name+']] ('+e.entity_type+')' for e in result.entities) or '- None'
 rels='\n'.join('- [['+x.source+']] — '+x.relation+' → [['+x.target+']]' for x in result.relations) or '- None'
 out.write_text('---\ntitle: '+result.document.title+'\nsource: '+result.document.source+'\nimportance: '+str(result.importance)+'\ndocument_type: '+result.document_type+'\ntags: ['+', '.join(result.tags)+']\n---\n\n# '+result.document.title+'\n\n## Summary\n'+result.summary+'\n\n## Korean\n'+result.translation_ko+'\n\n## Entities\n'+ents+'\n\n## Relations\n'+rels+'\n',encoding='utf-8')
def write_entities(entities,root):
 p=Path(root)/'entities'; p.mkdir(parents=True,exist_ok=True)
 for e in entities:
  out=p/(safe(e.name)+'.md')
  if not out.exists(): out.write_text('---\nname: '+e.name+'\ntype: '+e.entity_type+'\n---\n\n# '+e.name+'\n',encoding='utf-8')
