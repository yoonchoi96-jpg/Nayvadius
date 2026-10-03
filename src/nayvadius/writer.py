from pathlib import Path

def safe(s):
    return ''.join(c if c.isalnum() or c in ' -_' else '_' for c in s).strip()[:120] or 'untitled'

def write_markdown(result, root):
    p = Path(root) / 'documents'
    p.mkdir(parents=True, exist_ok=True)
    out = p / (safe(result.document.id) + '.md')
    tags = ', '.join(result.tags)
    ents = '\n'.join('- [[' + e.name + ']] (' + e.entity_type + ')' for e in result.entities) or '- None'
    rels = '\n'.join('- [[' + x.source + ']] - ' + x.relation + ' -> [[' + x.target + ']]' for x in result.relations) or '- None'
    text = ('---\n' + 'id: ' + result.document.id + '\n' +
        'title: ' + result.document.title + '\n' +
        'source: ' + result.document.source + '\n' +
        'importance: ' + str(result.importance) + '\n' +
        'document_type: ' + result.document_type + '\n' +
        'tags: [' + tags + ']\n---\n\n' +
        '# ' + result.document.title + '\n\n' +
        '## Summary\n' + result.summary + '\n\n' +
        '## Korean\n' + result.translation_ko + '\n\n' +
        '## Entities\n' + ents + '\n\n' +
        '## Relations\n' + rels + '\n')
    out.write_text(text, encoding='utf-8')

def write_entities(entities, root):
    p = Path(root) / 'entities'
    p.mkdir(parents=True, exist_ok=True)
    for e in entities:
        out = p / (safe(e.name) + '.md')
        if not out.exists():
            aliases = ', '.join(e.aliases)
            out.write_text('---\nname: ' + e.name + '\ntype: ' + e.entity_type +
                           '\naliases: [' + aliases + ']\n---\n\n# ' + e.name + '\n',
                           encoding='utf-8')
