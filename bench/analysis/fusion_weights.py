"""Can a static embedding + BM25 fuse to what the transformer gives alone?

Both channels score ~0.58 recall@10 on their own. Reciprocal rank fusion is
supposed to beat either -- the measured hybrid did not, which points at the
fusion rather than at the embedding. Everything here is offline: the FTS
ranks come from the existing index, the vectors from an in-process encode.
"""
import sys
import pathlib, json, re, sqlite3, numpy as np
from model2vec import StaticModel

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "django"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT.parent / ".benchmarks" / CORPUS / ".code-explorer" / "graph.sqlite"
QS = ROOT / "querysets" / f"{CORPUS}.json"
DEPTH = 100

con = sqlite3.connect(str(DB))
rows = list(con.execute(
    "select node_id, file, search_text from search_fts where search_text is not null"))
ids = [r[0] for r in rows]; files = [r[1] for r in rows]; texts = [r[2] for r in rows]
pos = {nid: i for i, nid in enumerate(ids)}
print(f"{len(rows):,} indexed symbols")

cases = json.load(open(QS))["cases"][:150]
queries = [c["query"] for c in cases]
qrels = [{a["file"] for a in c["answers"]} for c in cases]

def fts_ranking(q):
    """FTS5 bm25(), same shape the backend uses. Returns node_ids best-first."""
    terms = [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", q) if len(t) > 1]
    if not terms:
        return []
    expr = " OR ".join(f'"{t}"' for t in terms)
    try:
        return [r[0] for r in con.execute(
            "select node_id from search_fts where search_fts match ? "
            "order by bm25(search_fts) limit ?", (expr, DEPTH))]
    except sqlite3.OperationalError:
        return []

m = StaticModel.from_pretrained("minishlab/potion-retrieval-32m")
dv = m.encode(texts).astype(np.float32); dv /= np.linalg.norm(dv, axis=1, keepdims=True) + 1e-9
qv = m.encode(queries).astype(np.float32); qv /= np.linalg.norm(qv, axis=1, keepdims=True) + 1e-9

def recall_at(rank_lists, k=10):
    hit = tot = 0
    for i, order in enumerate(rank_lists):
        seen, top = set(), []
        for nid in order:
            f = files[pos[nid]]
            if f not in seen:
                seen.add(f); top.append(f)
            if len(top) == k: break
        hit += len(qrels[i] & set(top)); tot += len(qrels[i])
    return hit / tot

fts = [fts_ranking(q) for q in queries]
vec = [[ids[j] for j in np.argsort(-(dv @ qv[i]))[:DEPTH]] for i in range(len(queries))]

print(f"\n  BM25 alone                    recall@10 {recall_at(fts):.3f}")
print(f"  potion vectors alone          recall@10 {recall_at(vec):.3f}")

def rrf(lists, weights, k):
    score = {}
    for lst, w in zip(lists, weights):
        for r, nid in enumerate(lst, start=1):
            score[nid] = score.get(nid, 0.0) + w / (k + r)
    return [n for n, _ in sorted(score.items(), key=lambda x: -x[1])]

print("\n  RRF sweep (weight on vectors; BM25 weight fixed at 1.0):")
best = (0, None)
for k in (10, 30, 60):
    for wv in (0.25, 0.5, 1.0, 2.0):
        r = recall_at([rrf([fts[i], vec[i]], [1.0, wv], k) for i in range(len(queries))])
        best = max(best, (r, (k, wv)))
        print(f"    k={k:<3} w_vec={wv:<5} recall@10 {r:.3f}")
print(f"\n  best: recall@10 {best[0]:.3f} at k={best[1][0]}, w_vec={best[1][1]}")
print("  (transformer hybrid, measured end to end: 0.631)")
