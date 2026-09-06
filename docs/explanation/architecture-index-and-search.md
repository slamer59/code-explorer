# Architecture : indexation et recherche

Les deux chemins que traverse une requête. Les valeurs par défaut citées sont
celles du code (`settings.py`, `context.py`), pas des approximations.

## 1. Indexation

Un seul passage de tree-sitter par fichier. Rien n'est reparsé ensuite.

```mermaid
flowchart TD
    A["discover_python_files()<br/><i>git ls-files si racine de dépôt,<br/>sinon parcours filtré</i>"] --> B["Analyse tree-sitter<br/><i>un seul parcours par fichier</i>"]
    B --> C["FileAnalysis<br/>fonctions, classes, docstrings,<br/>appels, imports, bases, décorateurs"]
    C --> D["resolve_import_aware()<br/><i>résolution des appels via les imports</i>"]
    C --> E["_derive_search_text()"]
    E --> E1["nom qualifié<br/>nom<br/>mots du nom ×2<br/>signature<br/>1re ligne de docstring<br/>noms appelés"]
    E1 --> E2{"search_text_mode"}
    E2 -->|"body <i>(défaut)</i>"| E3["+ le corps<br/><i>plafonné à 2 000 car.</i>"]
    E2 -->|skeleton| E4["≈ 44 jetons"]
    D --> F
    E3 --> F
    E4 --> F
    F["ingest → SQLite"] --> G[("graph.sqlite")]
    G --> G1["Tables nœuds<br/>Function, Class, File…"]
    G --> G2["Tables arêtes<br/>CALLS, DEPENDS_ON…"]
    G --> G3["search_fts<br/><i>FTS5, BM25</i>"]
    G --> G4["search_trgm<br/><i>FTS5 trigramme (--fuzzy)</i>"]
    F -.->|"--semantic uniquement"| H["embed_texts()"]
    H --> H1{"embedding_provider"}
    H1 -->|"ollama <i>(défaut)</i>"| H2["transformer, HTTP<br/><i>76 textes/s</i>"]
    H1 -->|model2vec| H3["lookup statique, en process<br/><i>24 211 textes/s</i>"]
    H2 --> I[("graph_vectors.sqlite")]
    H3 --> I
```

**Coût mesuré sur django** (43 663 symboles, 3 585 fichiers) :

| étape | temps | taille |
|---|---|---|
| parse + résolution + SQLite + FTS5 | **0,29 min** | 246 Mo |
| + vecteurs, `ollama/nomic-embed-text` | 8,43 min | +418 Mo |
| + vecteurs, `model2vec/potion-32m` | 0,62 min | — |

L'indexation sans vecteurs est **plus rapide que la construction complète de
zvec-grep** (0,40 min). Les 8 minutes ne sont pas de la lenteur de pipeline :
c'est une passe avant de transformer par symbole.

## 2. Recherche

Deux étapes : trouver la graine, puis étendre le graphe autour d'elle.

```mermaid
flowchart TD
    Q["Requête"] --> M{"Mode"}
    M -->|"défaut"| BM["search_fts MATCH<br/>ORDER BY bm25()"]
    M -->|--fuzzy| TR["search_trgm"]
    M -->|--semantic| VE["recherche vectorielle"]
    BM -.->|"si graph_vectors.sqlite existe"| HY
    VE --> HY
    HY["Fusion RRF <i>(k=60)</i>"] --> RR
    BM --> RR
    TR --> RR
    RR["demote_tests()<br/><i>score des tests × 0,4</i>"] --> TRUNC
    TRUNC["troncature à --limit<br/><i>sur-extraction ×4 en amont</i>"] --> SEED

    SEED["Graine = hit n°1"] --> EXP["ContextAssembler.expand()"]
    EXP --> EX1["Parcours des arêtes CALLS<br/>amont + aval, profondeur 3"]
    EX1 --> EX2["Les nœuds à degré > 60 ne sont<br/>pas traversés <i>(hubs)</i>"]
    EX2 --> EX3["Classement de l'ensemble collecté<br/><i>distance, centralité, BM25</i>"]
    EX3 --> EX4["Budget 4 000 jetons<br/><i>au-delà : dégradation en signature,<br/>jamais de coupe en plein corps</i>"]
    EX4 --> OUT["Bundle markdown<br/><i>graine + voisins, avec leur source</i>"]
    TRUNC --> OUT
```

Le point important pour l'évaluation : **un appel rend les deux** — le tableau
de hits classés *et* le bundle assemblé. Les mesurer séparément ne décrit ce que
reçoit personne (voir `docs/explanation/benchmarking.md`, run `delivered`).

## 3. Ce que chaque étage coûte et rapporte

Mesuré sur django, 150 requêtes minées depuis l'historique git :

| configuration | R@10 | requête | build |
|---|---|---|---|
| skeleton, BM25 | 0.518 | 461 ms | 0,26 min |
| **body, BM25** | 0.586 | **471 ms** | **0,29 min** |
| body, hybride *(défaut)* | **0.631** | 727 ms | 8,43 min |
| body, hybride statique | 0.578 | 1 191 ms | 0,62 min |
| *zvec-grep, pour référence* | *0.629* | *1 165 ms* | *0,40 min* |

La ligne BM25 seule n'est pas significativement battue par zvec-grep sur R@1,
R@10 ni MRR — uniquement sur R@5, dont 83 % de l'écart tient à `demote_tests`.

`hybrid = not fuzzy and not semantic and vector_db_path.exists()` : la bascule
en hybride est un **effet de bord** de l'existence de l'index vectoriel, pas un
choix explicite. Un `--semantic` lancé une fois engage ensuite 8 minutes à
chaque réindexation et +256 ms par requête.
