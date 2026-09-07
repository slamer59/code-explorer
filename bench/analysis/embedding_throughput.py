"""Throughput of a Model2Vec static lookup vs Ollama, on real search_text."""
import sys
import pathlib, sqlite3, time, requests

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "django"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT.parent / ".benchmarks" / CORPUS / ".code-explorer" / "graph.sqlite"
c = sqlite3.connect(str(DB))
texts = [r[0] for r in c.execute(
    "select search_text from Function where search_text is not null limit 500")]
print(f"{len(texts)} real body-mode rows, median "
      f"{sorted(len(t) for t in texts)[len(texts)//2]} chars\n")

t0 = time.perf_counter(); n = 0
for i in range(0, len(texts), 50):
    r = requests.post("http://localhost:11434/api/embed",
                      json={"model": "nomic-embed-text", "input": texts[i:i+50]}, timeout=300)
    n += len(r.json()["embeddings"])
ollama = time.perf_counter() - t0
print(f"ollama/nomic-embed-text : {ollama:7.2f}s  {n/ollama:8.1f} texts/s  (768d)")

from model2vec import StaticModel
t0 = time.perf_counter(); m = StaticModel.from_pretrained("minishlab/potion-retrieval-32m")
load = time.perf_counter() - t0
t0 = time.perf_counter(); v = m.encode(texts); m2v = time.perf_counter() - t0
print(f"model2vec/potion-32m    : {m2v:7.2f}s  {len(texts)/m2v:8.1f} texts/s  "
      f"({v.shape[1]}d, +{load:.1f}s one-time load)")
print(f"\nspeedup: {ollama/m2v:.0f}x")
N = 35000
print(f"extrapolated to ~{N} django symbols: "
      f"ollama {N/(n/ollama)/60:.1f} min  ->  model2vec {N/(len(texts)/m2v)/60:.2f} min")
