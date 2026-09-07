"""Isolate fetch depth. All rows use one protocol, so only depth varies.

These numbers are NOT comparable to the end-to-end benchmark: they take the
top 10 unique files, where the CLI returns 10 raw hits that collapse to ~6
files. Only the columns against each other are meaningful.
"""
import sys
import pathlib, json, re, sqlite3, numpy as np
from model2vec import StaticModel

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "django"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT.parent / ".benchmarks" / CORPUS / ".code-explorer" / "graph.sqlite"
QS = ROOT / "querysets" / f"{CORPUS}.json"
con = sqlite3.connect(str(DB))
rows = list(con.execute("select node_id, file, search_text from search_fts where search_text is not null"))
ids=[r[0] for r in rows]; files=[r[1] for r in rows]; texts=[r[2] for r in rows]
pos={n:i for i,n in enumerate(ids)}
cases=json.load(open(QS))["cases"][:150]
queries=[c["query"] for c in cases]; qrels=[{a["file"] for a in c["answers"]} for c in cases]

def fts(q, d):
    terms=[t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", q) if len(t)>1]
    if not terms: return []
    expr=" OR ".join(f'"{t}"' for t in terms)
    try:
        return [r[0] for r in con.execute(
            "select node_id from search_fts where search_fts match ? order by bm25(search_fts) limit ?",(expr,d))]
    except sqlite3.OperationalError: return []

m=StaticModel.from_pretrained("minishlab/potion-retrieval-32m")
dv=m.encode(texts).astype(np.float32); dv/=np.linalg.norm(dv,axis=1,keepdims=True)+1e-9
qv=m.encode(queries).astype(np.float32); qv/=np.linalg.norm(qv,axis=1,keepdims=True)+1e-9
sims=[dv@qv[i] for i in range(len(queries))]

def recall(lists,k=10):
    hit=tot=0
    for i,order in enumerate(lists):
        seen,top=set(),[]
        for n in order:
            f=files[pos[n]]
            if f not in seen: seen.add(f); top.append(f)
            if len(top)==k: break
        hit+=len(qrels[i]&set(top)); tot+=len(qrels[i])
    return hit/tot

def rrf(a,b,k=60):
    sc={}
    for lst in (a,b):
        for r,n in enumerate(lst,1): sc[n]=sc.get(n,0.0)+1.0/(k+r)
    return [n for n,_ in sorted(sc.items(),key=lambda x:-x[1])]

print(f"{'fetch depth':>12} {'BM25':>8} {'vectors':>9} {'RRF fused':>11}")
for d in (10, 20, 40, 100, 300):
    F=[fts(q,d) for q in queries]
    V=[[ids[j] for j in np.argsort(-sims[i])[:d]] for i in range(len(queries))]
    print(f"{d:>12} {recall(F):>8.3f} {recall(V):>9.3f} {recall([rrf(F[i],V[i]) for i in range(len(queries))]):>11.3f}")
print("\n  (the CLI currently fetches limit x _RERANK_OVERFETCH = 40)")
