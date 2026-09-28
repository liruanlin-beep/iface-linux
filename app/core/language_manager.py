import json

from app.core.paths import TRANSLATIONS_DIR


class LanguageManager:
    def __init__(self, language="en_US"):
        self.language = language
        self.labels = {}
        self.load(language)

    def load(self, language):
        self.language = language
        path = TRANSLATIONS_DIR / f"{language}.json"
        if not path.exists():
            path = TRANSLATIONS_DIR / "en_US.json"
        self.labels = json.loads(path.read_text(encoding="utf-8"))

    def t(self, key):
        return self.labels.get(key, key)
