import json, os, time, urllib.error, urllib.request
from .hash import content_hash
SCHEMA_VERSION='v5'
class LLMProvider:
    def __init__(self):
        self.key=os.getenv('NAYVADIUS_LLM_API_KEY','')
        self.url=os.getenv('NAYVADIUS_LLM_BASE_URL','https://api.openai.com/v1/chat/completions')
        self.model=os.getenv('NAYVADIUS_LLM_MODEL','gpt-4.1-mini')
    def cache_key(self,title,content): return content_hash(self.model+'|'+SCHEMA_VERSION+'|'+title+'|'+content)
    def analyze(self,title,content):
        if not self.key: return None
        prompt='Return JSON only with summary, document_type, importance, tags, entities, relations, translation_ko. Never invent entities or relations. TITLE: '+title+' CONTENT: '+content[:20000]
        body=json.dumps({'model':self.model,'temperature':0,'messages':[{'role':'system','content':'Precise knowledge extraction engine.'},{'role':'user','content':prompt}]}).encode()
        req=urllib.request.Request(self.url,data=body,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        last_error = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=90) as response:
                    data = json.load(response)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        else:
            raise last_error or RuntimeError("LLM request failed")
        text=data['choices'][0]['message']['content'].strip()
        if text.startswith('```'): text=text.split('```')[1].removeprefix('json').strip()
        return json.loads(text)
