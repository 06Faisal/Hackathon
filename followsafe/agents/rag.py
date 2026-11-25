"""RAG retriever over approved templates + patient-education content (TF-IDF)."""
import json, pathlib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB = pathlib.Path(__file__).resolve().parents[2] / "data" / "kb" / "templates.json"

class Retriever:
    def __init__(self, path=KB):
        self.docs = json.loads(pathlib.Path(path).read_text())
        self.vec = TfidfVectorizer().fit([d["topic"] + " " + d["text"] for d in self.docs])
        self.mat = self.vec.transform([d["topic"] + " " + d["text"] for d in self.docs])

    def search(self, query: str, k: int = 3, min_score: float = 0.05):
        sims = cosine_similarity(self.vec.transform([query]), self.mat)[0]
        ranked = sorted(zip(sims, self.docs), key=lambda x: -x[0])
        return [d for s, d in ranked[:k] if s >= min_score]
