# Analyses

Scripts ponctuels qui ont produit des chiffres cités ailleurs — dans
`settings.py`, dans `docs/explanation/gap-analysis-vs-zvec.md`. Ils vivent ici
pour que ces nombres restent vérifiables : un chiffre écrit en dur dans un
commentaire, dont le code a disparu, ne peut plus être discuté ni réfuté.

Ils diffèrent de `bench/bench/` : le harnais produit des mesures régulières et
comparables dans le temps, ces scripts répondent à une question précise, une
fois. Ils prennent tous un nom de corpus en argument (défaut : `django`).

| script | ce qu'il établit |
|---|---|
| `ground_truth_composition.py` | de quoi la vérité terrain est faite, et ce que `demote_tests` supprime. Avertit quand un corpus ne peut pas trancher la question de la rétrogradation. |
| `gap_decomposition.py` | d'où vient l'avantage d'un outil sur un autre : tests rétrogradés ou code applicatif. |
| `embedding_throughput.py` | débit Ollama vs Model2Vec sur du vrai `search_text` (319×). |
| `name_weighting.py` | résultat négatif : retirer la pondération du nom dégrade les embeddings statiques. |
| `fusion_depth.py` | balayage de la profondeur de récupération pour BM25, vecteurs et RRF. |
| `fusion_weights.py` | balayage des poids et du `k` de la fusion RRF. |

Les quatre derniers ont besoin de `model2vec` : `uv pip install model2vec`.

## Avertissement

`fusion_depth.py` et `fusion_weights.py` mesurent **hors pipeline** — ils
prennent les 10 premiers *fichiers* uniques d'une liste profonde, là où la CLI
rend 10 *hits* bruts qui se réduisent à ~6 fichiers, puis applique
`demote_tests`. Leurs chiffres ne sont comparables qu'entre eux.

C'est ce qui a fait échouer une prédiction : la fusion en profondeur gagnait
+0,02 hors pipeline et perdait 0,04 de bout en bout, parce que le modèle hors
ligne omettait la rétrogradation des tests. Un résultat hors pipeline est une
hypothèse, pas une mesure.
