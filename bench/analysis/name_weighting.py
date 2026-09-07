"""Does the BM25 name-weighting poison a mean-pooled static embedding?

search_text emits the identifier, then its split words, then both again --
deliberate, because BM25 rewards term density and a wordy docstring otherwise
outscores a one-token name. A static model mean-pools token vectors, so the
same repetition drags every symbol's vector toward its own name.
"""
import sys
import pathlib, json, sqlite3, sys, numpy as np
from model2vec import StaticModel

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "django"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT.parent / ".benchmarks" / CORPUS / ".code-explorer" / "graph.sqlite"
QS = ROOT / "querysets" / f"{CORPUS}.json"

c = sqlite3.connect(str(DB))
rows = [(r[0], r[1]) for r in c.execute(
    "select file, search_text from Function where search_text is not null")]
rows += [(r[0], r[1]) for r in c.execute(
    "select file, search_text from Class where search_text is not null")]
print(f"{len(rows):,} symbols")

def strip_weighting(text: str) -> str:
    """Drop the qualified name, the bare name and the two split-word lines."""
    lines = text.split("\n")
    return "\n".join(lines[4:]) if len(lines) > 4 else text

variants = {
    "as indexed (name x4 + body)": [t for _, t in rows],
    "without the name weighting":  [strip_weighting(t) for _, t in rows],
}
files = [f for f, _ in rows]

cases = json.load(open(QS))["cases"][:150]
qrels = [{a["file"] for a in c_["answers"]} for c_ in cases]
queries = [c_["query"] for c_ in cases]

m = StaticModel.from_pretrained("minishlab/potion-retrieval-32m")
qv = m.encode(queries); qv /= np.linalg.norm(qv, axis=1, keepdims=True) + 1e-9

for label, texts in variants.items():
    dv = m.encode(texts).astype(np.float32)
    dv /= np.linalg.norm(dv, axis=1, keepdims=True) + 1e-9
    hits10 = hits5 = 0; tot = 0
    for i, rel in enumerate(qrels):
        sims = dv @ qv[i]
        order = np.argsort(-sims)
        seen, top = [], []
        for j in order:
            if files[j] not in seen:
                seen.append(files[j]); top.append(files[j])
            if len(top) == 10: break
        hits10 += len(rel & set(top[:10])); hits5 += len(rel & set(top[:5])); tot += len(rel)
    print(f"  {label:30} recall@5 {hits5/tot:.3f}   recall@10 {hits10/tot:.3f}")
