from collections import deque


class VocabularyMatcher:
    """Unicode-safe Aho-Corasick matcher for vocabulary forms."""

    def __init__(self, rows, min_cjk_length=2, min_latin_length=3):
        self.next = [{}]
        self.fail = [0]
        self.outputs = [[]]
        self.forms = {}
        for vid, word, traditional in rows:
            for form in {str(word or "").strip(), str(traditional or "").strip()}:
                if not form:
                    continue
                normalized = form.casefold()
                if self._too_short(normalized, min_cjk_length, min_latin_length):
                    continue
                self.forms.setdefault(normalized, set()).add(vid)
        for form in self.forms:
            node = 0
            for ch in form:
                if ch not in self.next[node]:
                    self.next[node][ch] = len(self.next)
                    self.next.append({})
                    self.fail.append(0)
                    self.outputs.append([])
                node = self.next[node][ch]
            self.outputs[node].append(form)
        queue = deque()
        for node in self.next[0].values():
            queue.append(node)
        while queue:
            node = queue.popleft()
            for ch, child in self.next[node].items():
                queue.append(child)
                fallback = self.fail[node]
                while fallback and ch not in self.next[fallback]:
                    fallback = self.fail[fallback]
                self.fail[child] = self.next[fallback].get(ch, 0)
                self.outputs[child].extend(self.outputs[self.fail[child]])

    @staticmethod
    def _too_short(form, min_cjk_length, min_latin_length):
        cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in form)
        return len(form) < (min_cjk_length if cjk else min_latin_length)

    def match(self, text):
        text = str(text or "").casefold()
        node = 0
        found = {}
        for ch in text:
            while node and ch not in self.next[node]:
                node = self.fail[node]
            node = self.next[node].get(ch, 0)
            for form in self.outputs[node]:
                for vid in self.forms[form]:
                    found[vid] = found.get(vid, 0) + 1
        return found
