# django: cross-tool summary

150 queries mined from the corpus's own git history: the commit subject is the query, the files it touched are the relevant documents. Scored at **file level**, the only identifier every code search tool can produce.

Generated 2026-09-06T13:22:17+00:00 on fedora5.home (16 CPUs, Python 3.12.13).
Tool at `1df789e6` (dirty), corpus at `b3f4d83a`.


## `delivered`, ground truth = code only

The 133 queries whose answer set contains non-test files (code = « où est-ce implémenté ? »).

```
#    Model                          Recall@1       Recall@5      Recall@10      MRR@10          NDCG@10
---  -----------------------------  -------------  ------------  -------------  --------------  --------------
a    code-explorer                  0.314ᵉⁱʲ       0.615         0.668          0.480           0.512
b    code-explorer-body             0.517ᵃᵉᶠᵍⁱʲᵏ   0.788ᵃᵉʰⁱʲᵏ   0.798ᵃᵉʰⁱʲᵏ    0.668ᵃᵉʰⁱʲᵏ     0.684ᵃᵉʰⁱʲᵏ
c    code-explorer-body-d10         0.517ᵃᵉᶠᵍⁱʲᵏ   0.815ᵃᵉʰⁱʲᵏ   0.824ᵃᵉʰⁱʲᵏ    0.674ᵃᵉᶠʰⁱʲᵏ    0.696ᵃᵉʰⁱʲᵏ
d    code-explorer-body-hybrid      0.567ᵃᵉᶠᵍʰⁱʲᵏ  0.820ᵃᵉᶠʰⁱʲᵏ  0.847ᵃᵇᵉʰⁱʲᵏ   0.723ᵃᵇᵉᶠᵍʰⁱʲᵏ  0.737ᵃᵇᵉᶠᵍʰⁱʲᵏ
e    code-explorer-body-notestdemo  0.210          0.641         0.668          0.421           0.471
f    code-explorer-body-potion      0.439ᵃᵉⁱʲ      0.767ᵃᵉʰⁱʲᵏ   0.814ᵃᵉʰⁱʲᵏ    0.616ᵃᵉⁱʲᵏ      0.653ᵃᵉⁱʲᵏ
g    code-explorer-body-potion-d10  0.432ᵃᵉⁱʲ      0.809ᵃᵉʰⁱʲᵏ   0.855ᵃᵇᵉᶠʰⁱʲᵏ  0.624ᵃᵉⁱʲᵏ      0.670ᵃᵉʰⁱʲᵏ
h    code-explorer-hybrid           0.429ᵃᵉⁱʲ      0.654         0.708          0.577ᵃᵉⁱʲᵏ      0.594ᵃᵉⁱʲ
i    zg                             0.216          0.606         0.646          0.403           0.450
j    zg-full                        0.216          0.606         0.646          0.403           0.450
k    zg-symbol                      0.375ᵉⁱʲ       0.594         0.641          0.492ⁱʲ         0.517
```

## `delivered`, ground truth = test only

The 145 queries whose answer set contains non-test files (test = « qu'est-ce qui couvre ça ? »).

```
#    Model                          Recall@1         Recall@5         Recall@10        MRR@10           NDCG@10
---  -----------------------------  ---------------  ---------------  ---------------  ---------------  ---------------
a    code-explorer                  0.028ᶜᵈᵍ         0.205ᵍ           0.435ᶜᵍ          0.139ᶜᵍ          0.199ᶜᵍ
b    code-explorer-body             0.007            0.271ᵃᶜᵍ         0.444ᶜᵍ          0.120ᶜᵍ          0.193ᶜᵍ
c    code-explorer-body-d10         0.003            0.167            0.347            0.078            0.138
d    code-explorer-body-hybrid      0.003            0.344ᵃᶜᶠᵍ        0.497ᶜᶠᵍ         0.143ᵇᶜᶠᵍ        0.222ᶜᶠᵍ
e    code-explorer-body-notestdemo  0.452ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.712ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.741ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.645ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.637ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ
f    code-explorer-body-potion      0.010            0.205ᵍ           0.412ᵍ           0.107ᶜᵍ          0.174ᶜᵍ
g    code-explorer-body-potion-d10  0.003            0.129            0.299            0.074            0.123
h    code-explorer-hybrid           0.017            0.367ᵃᵇᶜᶠᵍ       0.535ᵃᵇᶜᶠᵍ       0.170ᵃᵇᶜᵈᶠᵍ      0.248ᵃᵇᶜᶠᵍ
i    zg                             0.295ᵃᵇᶜᵈᶠᵍʰᵏ    0.625ᵃᵇᶜᵈᶠᵍʰᵏ    0.651ᵃᵇᶜᵈᶠᵍʰᵏ    0.513ᵃᵇᶜᵈᶠᵍʰᵏ    0.513ᵃᵇᶜᵈᶠᵍʰᵏ
j    zg-full                        0.295ᵃᵇᶜᵈᶠᵍʰᵏ    0.628ᵃᵇᶜᵈᶠᵍʰᵏ    0.651ᵃᵇᶜᵈᶠᵍʰᵏ    0.513ᵃᵇᶜᵈᶠᵍʰᵏ    0.514ᵃᵇᶜᵈᶠᵍʰᵏ
k    zg-symbol                      0.054ᵇᶜᵈᶠᵍ       0.421ᵃᵇᶜᶠᵍ       0.520ᶜᶠᵍ         0.253ᵃᵇᶜᵈᶠᵍʰ     0.296ᵃᵇᶜᵈᶠᵍ
```

## `delivered`

```
#    Model                          Recall@1         Recall@5         Recall@10        MRR@10           NDCG@10
---  -----------------------------  ---------------  ---------------  ---------------  ---------------  ---------------
a    code-explorer                  0.153            0.382            0.518            0.501            0.405
b    code-explorer-body             0.235ᵃᵍ          0.491ᵃᶜᶠᵍ        0.586ᵃᶜᵍ         0.630ᵃᶠᵍ         0.499ᵃᶜᵍ
c    code-explorer-body-d10         0.232ᵃᵍ          0.445ᵃ           0.542            0.615ᵃ           0.468ᵃ
d    code-explorer-body-hybrid      0.252ᵃᶠᵍʰᵏ       0.536ᵃᵇᶜᶠᵍʰ      0.631ᵃᵇᶜᶠᵍᵏ      0.675ᵃᶜᶠᵍʰᵏ      0.542ᵃᵇᶜᶠᵍʰᵏ
e    code-explorer-body-notestdemo  0.328ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.658ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.692ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.792ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.665ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ
f    code-explorer-body-potion      0.203ᵃ           0.446ᵃ           0.578ᵃᵍ          0.578ᵃ           0.469ᵃᵍ
g    code-explorer-body-potion-d10  0.194ᵃ           0.426ᵃ           0.532            0.570ᵃ           0.445
h    code-explorer-hybrid           0.196ᵃ           0.480ᵃᵍ          0.592ᵃᵍ          0.592ᵃ           0.482ᵃ
i    zg                             0.257ᵃᶠᵍʰᵏ       0.597ᵃᵇᶜᶠᵍʰᵏ     0.629ᵃᶜᵍᵏ        0.691ᵃᶜᶠᵍʰᵏ      0.578ᵃᵇᶜᶠᵍʰᵏ
j    zg-full                        0.257ᵃᶠᵍʰᵏ       0.599ᵃᵇᶜᵈᶠᵍʰᵏ    0.629ᵃᶜᵍᵏ        0.691ᵃᶜᶠᵍʰᵏ      0.578ᵃᵇᶜᶠᵍʰᵏ
k    zg-symbol                      0.193            0.488ᵃᵍ          0.559            0.577            0.473ᵃ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `seed`

```
#    Model                          Recall@1         Recall@5       Recall@10      MRR@10           NDCG@10
---  -----------------------------  ---------------  -------------  -------------  ---------------  ---------------
a    code-explorer                  0.153            0.375          0.458          0.498            0.380
b    code-explorer-body             0.235ᵃᵍ          0.471ᵃᶜᵍ       0.505ᶜᵍ        0.629ᵃᶠᵍ         0.464ᵃᶜᵍ
c    code-explorer-body-d10         0.232ᵃᵍ          0.425ᵃ         0.440          0.614ᵃ           0.424ᵃ
d    code-explorer-body-hybrid      0.252ᵃᶠᵍʰᵏ       0.522ᵃᵇᶜᶠᵍʰ    0.575ᵃᵇᶜᶠᵍ     0.675ᵃᶜᶠᵍʰᵏ      0.518ᵃᵇᶜᶠᵍʰ
e    code-explorer-body-notestdemo  0.328ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.645ᵃᵇᶜᵈᶠᵍʰᵏ  0.659ᵃᵇᶜᵈᶠᵍʰᵏ  0.792ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.646ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ
f    code-explorer-body-potion      0.203ᵃ           0.436ᵃ         0.499ᶜᵍ        0.577ᵃ           0.436ᵃᵍ
g    code-explorer-body-potion-d10  0.194ᵃ           0.412          0.461          0.569ᵃ           0.415
h    code-explorer-hybrid           0.196ᵃ           0.463ᵃᵍ        0.533ᵃᶜᵍ       0.592ᵃ           0.455ᵃᵍ
i    zg                             0.257ᵃᶠᵍʰᵏ       0.597ᵃᵇᶜᵈᶠᵍʰᵏ  0.629ᵃᵇᶜᶠᵍʰᵏ   0.691ᵃᶜᶠᵍʰᵏ      0.578ᵃᵇᶜᵈᶠᵍʰᵏ
j    zg-full                        0.257ᵃᶠᵍʰᵏ       0.599ᵃᵇᶜᵈᶠᵍʰᵏ  0.629ᵃᵇᶜᶠᵍʰᵏ   0.691ᵃᶜᶠᵍʰᵏ      0.578ᵃᵇᶜᵈᶠᵍʰᵏ
k    zg-symbol                      0.193            0.488ᵃᶜᵍ       0.559ᵃᶜᶠᵍ      0.577ᵃ           0.473ᵃᵍ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## `bundle`

```
#    Model                          Recall@1         Recall@5        Recall@10       MRR@10         NDCG@10
---  -----------------------------  ---------------  --------------  --------------  -------------  --------------
a    code-explorer                  0.153            0.278           0.282           0.387          0.288
b    code-explorer-body             0.235ᵃᵍ          0.382ᵃ          0.382ᵃ          0.547ᵃᵍ        0.407ᵃᵍ
c    code-explorer-body-d10         0.232ᵃᵍ          0.379ᵃ          0.379ᵃ          0.540ᵃᵍ        0.403ᵃᵍ
d    code-explorer-body-hybrid      0.252ᵃᶠᵍʰᵏ       0.391ᵃᵍʰ        0.394ᵃᵍʰ        0.580ᵃᶠᵍʰ      0.422ᵃᶠᵍʰ
e    code-explorer-body-notestdemo  0.328ᵃᵇᶜᵈᶠᵍʰⁱʲᵏ  0.454ᵃᵇᶜᵈᶠᵍʰ    0.454ᵃᵇᶜᵈᶠᵍʰ    0.747ᵃᵇᶜᵈᶠᵍʰᵏ  0.512ᵃᵇᶜᵈᶠᵍʰ
f    code-explorer-body-potion      0.203ᵃ           0.361ᵃᵍ         0.364ᵃ          0.485ᵃ         0.374ᵃ
g    code-explorer-body-potion-d10  0.194ᵃ           0.337ᵃ          0.342ᵃ          0.470ᵃ         0.353ᵃ
h    code-explorer-hybrid           0.196ᵃ           0.332ᵃ          0.336ᵃ          0.472ᵃ         0.353ᵃ
i    zg                             0.257ᵃᶠᵍʰᵏ       0.597ᵃᵇᶜᵈᵉᶠᵍʰᵏ  0.629ᵃᵇᶜᵈᵉᶠᵍʰᵏ  0.691ᵃᵇᶜᵈᶠᵍʰᵏ  0.578ᵃᵇᶜᵈᵉᶠᵍʰᵏ
j    zg-full                        0.257ᵃᶠᵍʰᵏ       0.599ᵃᵇᶜᵈᵉᶠᵍʰᵏ  0.629ᵃᵇᶜᵈᵉᶠᵍʰᵏ  0.691ᵃᵇᶜᵈᶠᵍʰᵏ  0.578ᵃᵇᶜᵈᵉᶠᵍʰᵏ
k    zg-symbol                      0.193            0.488ᵃᵇᶜᵈᶠᵍʰ    0.559ᵃᵇᶜᵈᵉᶠᵍʰ   0.577ᵃᶠᵍʰ      0.473ᵃᵇᶜᶠᵍʰ
```

A superscript marks a win that is statistically significant over the lettered model (paired Fisher randomization, p < 0.05). A bare number is a gap the data does not support.

## Complementarity

Recall says who retrieves more. It cannot say whether two tools retrieve the *same* things -- and that is the difference between a tool being redundant and a tool being worth running alongside another.

| tool | vs | relevant files it alone found | relevant files it found | share unique |
|---|---|---|---|---|
| code-explorer | code-explorer-body | 29 | 182 | 16% |
| code-explorer | code-explorer-body-d10 | 40 | 182 | 22% |
| code-explorer | code-explorer-body-hybrid | 25 | 182 | 14% |
| code-explorer | code-explorer-body-notestdemo | 18 | 182 | 10% |
| code-explorer | code-explorer-body-potion | 39 | 182 | 21% |
| code-explorer | code-explorer-body-potion-d10 | 44 | 182 | 24% |
| code-explorer | code-explorer-hybrid | 16 | 182 | 9% |
| code-explorer | zg | 46 | 182 | 25% |
| code-explorer | zg-full | 46 | 182 | 25% |
| code-explorer | zg-symbol | 52 | 182 | 29% |
| code-explorer-body | code-explorer | 51 | 204 | 25% |
| code-explorer-body | code-explorer-body-d10 | 21 | 204 | 10% |
| code-explorer-body | code-explorer-body-hybrid | 16 | 204 | 8% |
| code-explorer-body | code-explorer-body-notestdemo | 20 | 204 | 10% |
| code-explorer-body | code-explorer-body-potion | 29 | 204 | 14% |
| code-explorer-body | code-explorer-body-potion-d10 | 37 | 204 | 18% |
| code-explorer-body | code-explorer-hybrid | 40 | 204 | 20% |
| code-explorer-body | zg | 50 | 204 | 25% |
| code-explorer-body | zg-full | 50 | 204 | 25% |
| code-explorer-body | zg-symbol | 56 | 204 | 27% |
| code-explorer-body-d10 | code-explorer | 45 | 187 | 24% |
| code-explorer-body-d10 | code-explorer-body | 4 | 187 | 2% |
| code-explorer-body-d10 | code-explorer-body-hybrid | 14 | 187 | 7% |
| code-explorer-body-d10 | code-explorer-body-notestdemo | 24 | 187 | 13% |
| code-explorer-body-d10 | code-explorer-body-potion | 24 | 187 | 13% |
| code-explorer-body-d10 | code-explorer-body-potion-d10 | 25 | 187 | 13% |
| code-explorer-body-d10 | code-explorer-hybrid | 36 | 187 | 19% |
| code-explorer-body-d10 | zg | 46 | 187 | 25% |
| code-explorer-body-d10 | zg-full | 46 | 187 | 25% |
| code-explorer-body-d10 | zg-symbol | 51 | 187 | 27% |
| code-explorer-body-hybrid | code-explorer | 61 | 218 | 28% |
| code-explorer-body-hybrid | code-explorer-body | 30 | 218 | 14% |
| code-explorer-body-hybrid | code-explorer-body-d10 | 45 | 218 | 21% |
| code-explorer-body-hybrid | code-explorer-body-notestdemo | 32 | 218 | 15% |
| code-explorer-body-hybrid | code-explorer-body-potion | 31 | 218 | 14% |
| code-explorer-body-hybrid | code-explorer-body-potion-d10 | 44 | 218 | 20% |
| code-explorer-body-hybrid | code-explorer-hybrid | 34 | 218 | 16% |
| code-explorer-body-hybrid | zg | 52 | 218 | 24% |
| code-explorer-body-hybrid | zg-full | 52 | 218 | 24% |
| code-explorer-body-hybrid | zg-symbol | 61 | 218 | 28% |
| code-explorer-body-notestdemo | code-explorer | 76 | 240 | 32% |
| code-explorer-body-notestdemo | code-explorer-body | 56 | 240 | 23% |
| code-explorer-body-notestdemo | code-explorer-body-d10 | 77 | 240 | 32% |
| code-explorer-body-notestdemo | code-explorer-body-hybrid | 54 | 240 | 22% |
| code-explorer-body-notestdemo | code-explorer-body-potion | 66 | 240 | 28% |
| code-explorer-body-notestdemo | code-explorer-body-potion-d10 | 85 | 240 | 35% |
| code-explorer-body-notestdemo | code-explorer-hybrid | 59 | 240 | 25% |
| code-explorer-body-notestdemo | zg | 45 | 240 | 19% |
| code-explorer-body-notestdemo | zg-full | 45 | 240 | 19% |
| code-explorer-body-notestdemo | zg-symbol | 68 | 240 | 28% |
| code-explorer-body-potion | code-explorer | 55 | 198 | 28% |
| code-explorer-body-potion | code-explorer-body | 23 | 198 | 12% |
| code-explorer-body-potion | code-explorer-body-d10 | 35 | 198 | 18% |
| code-explorer-body-potion | code-explorer-body-hybrid | 11 | 198 | 6% |
| code-explorer-body-potion | code-explorer-body-notestdemo | 24 | 198 | 12% |
| code-explorer-body-potion | code-explorer-body-potion-d10 | 22 | 198 | 11% |
| code-explorer-body-potion | code-explorer-hybrid | 36 | 198 | 18% |
| code-explorer-body-potion | zg | 43 | 198 | 22% |
| code-explorer-body-potion | zg-full | 43 | 198 | 22% |
| code-explorer-body-potion | zg-symbol | 53 | 198 | 27% |
| code-explorer-body-potion-d10 | code-explorer | 46 | 184 | 25% |
| code-explorer-body-potion-d10 | code-explorer-body | 17 | 184 | 9% |
| code-explorer-body-potion-d10 | code-explorer-body-d10 | 22 | 184 | 12% |
| code-explorer-body-potion-d10 | code-explorer-body-hybrid | 10 | 184 | 5% |
| code-explorer-body-potion-d10 | code-explorer-body-notestdemo | 29 | 184 | 16% |
| code-explorer-body-potion-d10 | code-explorer-body-potion | 8 | 184 | 4% |
| code-explorer-body-potion-d10 | code-explorer-hybrid | 32 | 184 | 17% |
| code-explorer-body-potion-d10 | zg | 46 | 184 | 25% |
| code-explorer-body-potion-d10 | zg-full | 46 | 184 | 25% |
| code-explorer-body-potion-d10 | zg-symbol | 52 | 184 | 28% |
| code-explorer-hybrid | code-explorer | 42 | 208 | 20% |
| code-explorer-hybrid | code-explorer-body | 44 | 208 | 21% |
| code-explorer-hybrid | code-explorer-body-d10 | 57 | 208 | 27% |
| code-explorer-hybrid | code-explorer-body-hybrid | 24 | 208 | 12% |
| code-explorer-hybrid | code-explorer-body-notestdemo | 27 | 208 | 13% |
| code-explorer-hybrid | code-explorer-body-potion | 46 | 208 | 22% |
| code-explorer-hybrid | code-explorer-body-potion-d10 | 56 | 208 | 27% |
| code-explorer-hybrid | zg | 49 | 208 | 24% |
| code-explorer-hybrid | zg-full | 49 | 208 | 24% |
| code-explorer-hybrid | zg-symbol | 59 | 208 | 28% |
| zg | code-explorer | 84 | 220 | 38% |
| zg | code-explorer-body | 66 | 220 | 30% |
| zg | code-explorer-body-d10 | 79 | 220 | 36% |
| zg | code-explorer-body-hybrid | 54 | 220 | 25% |
| zg | code-explorer-body-notestdemo | 25 | 220 | 11% |
| zg | code-explorer-body-potion | 65 | 220 | 30% |
| zg | code-explorer-body-potion-d10 | 82 | 220 | 37% |
| zg | code-explorer-hybrid | 61 | 220 | 28% |
| zg | zg-full | 0 | 220 | 0% |
| zg | zg-symbol | 38 | 220 | 17% |
| zg-full | code-explorer | 84 | 220 | 38% |
| zg-full | code-explorer-body | 66 | 220 | 30% |
| zg-full | code-explorer-body-d10 | 79 | 220 | 36% |
| zg-full | code-explorer-body-hybrid | 54 | 220 | 25% |
| zg-full | code-explorer-body-notestdemo | 25 | 220 | 11% |
| zg-full | code-explorer-body-potion | 65 | 220 | 30% |
| zg-full | code-explorer-body-potion-d10 | 82 | 220 | 37% |
| zg-full | code-explorer-hybrid | 61 | 220 | 28% |
| zg-full | zg | 0 | 220 | 0% |
| zg-full | zg-symbol | 38 | 220 | 17% |
| zg-symbol | code-explorer | 67 | 197 | 34% |
| zg-symbol | code-explorer-body | 49 | 197 | 25% |
| zg-symbol | code-explorer-body-d10 | 61 | 197 | 31% |
| zg-symbol | code-explorer-body-hybrid | 40 | 197 | 20% |
| zg-symbol | code-explorer-body-notestdemo | 25 | 197 | 13% |
| zg-symbol | code-explorer-body-potion | 52 | 197 | 26% |
| zg-symbol | code-explorer-body-potion-d10 | 65 | 197 | 33% |
| zg-symbol | code-explorer-hybrid | 48 | 197 | 24% |
| zg-symbol | zg | 15 | 197 | 8% |
| zg-symbol | zg-full | 15 | 197 | 8% |

A high share-unique against a stronger tool means the two are complementary rather than ranked: the files behind that number are ones the other tool never returned at any rank.

## Cost

Query latency and tokens are paid on every question the agent asks. Index build is paid once per corpus, and is only reported for a run that actually rebuilt -- a tool whose index was reused shows `reused`, never a misleadingly small number.

| tool | errors | median latency | mean tokens | index build |
|---|---|---|---|---|
| code-explorer | 0 | 461 ms | 1840 | 0.3 min |
| code-explorer-body | 0 | 471 ms | 2300 | 0.3 min |
| code-explorer-body-d10 | 0 | 473 ms | 2310 | 0.3 min |
| code-explorer-body-hybrid | 0 | 727 ms | 2201 | 8.4 min |
| code-explorer-body-notestdemo | 0 | 474 ms | 1507 | 0.3 min |
| code-explorer-body-potion | 0 | 1191 ms | 2234 | 0.6 min |
| code-explorer-body-potion-d10 | 0 | 1192 ms | 2238 | 0.6 min |
| code-explorer-hybrid | 0 | 718 ms | 1727 | 6.1 min |
| zg | 0 | 1165 ms | 344 | reused |
| zg-full | 0 | 1165 ms | 4056 | 0.0 min |
| zg-symbol | 0 | 1172 ms | 325 | 0.0 min |
## What actually ran

| tool | observed retrieval mode(s) | vector model | expansion step |
|---|---|---|---|
| code-explorer | BM25 | none | yes |
| code-explorer-body | BM25 | none | yes |
| code-explorer-body-d10 | BM25 | none | yes |
| code-explorer-body-hybrid | hybrid BM25+vector | ollama/nomic-embed-text | yes |
| code-explorer-body-notestdemo | BM25 | none | yes |
| code-explorer-body-potion | hybrid BM25+vector | model2vec/potion-retrieval-32m | yes |
| code-explorer-body-potion-d10 | hybrid BM25+vector | model2vec/potion-retrieval-32m | yes |
| code-explorer-hybrid | hybrid BM25+vector | none | yes |
| zg | fts+vector, fts+vector,vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | local/potion-retrieval-32m | no |
| zg-full | fts+vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | none | no |
| zg-symbol | fts+vector, fts,fts+vector, fts,fts+vector,vector, fts,vector | none | no |

Retrieval mode is read back from each tool per query, not assumed: it usually depends on which indexes were built rather than on a documented default. The vector model is recorded because a hybrid tool's quality is a property of its embedding as much as of its retrieval logic -- two tools compared under different models are partly a comparison of the models.

## Asymmetries

Declared by each adapter, stated and not corrected for -- silently normalising them would hide real differences in what each tool is for.

- **code-explorer** -- Indexes Python only, so a relevant non-Python file is unreachable for it by construction.
- **code-explorer** -- Full-text search (SQLite FTS5/BM25) with no vector component, because no vector index was built for this configuration.
- **code-explorer** -- Returns whole symbols, and has a second expansion step, so its `bundle` row differs from its `seed` row.
- **code-explorer-body** -- Indexes Python only.
- **code-explorer-body** -- FTS/BM25 over name + signature + docstring + callee names + the source body (capped at 2,000 chars). No vector component.
- **code-explorer-body** -- Returns whole symbols, and has a second expansion step.
- **code-explorer-body-d10** -- BM25 over the source body, fetching 100 deep. The control: depth without a second channel should barely move.
- **code-explorer-body-hybrid** -- Indexes Python only.
- **code-explorer-body-hybrid** -- Hybrid: FTS/BM25 fused with a vector index, both built over the source body rather than the skeleton.
- **code-explorer-body-hybrid** -- Returns whole symbols, and has a second expansion step.
- **code-explorer-body-notestdemo** -- BM25 over the source body with test demotion disabled.
- **code-explorer-body-potion** -- Indexes Python only.
- **code-explorer-body-potion** -- Hybrid over the source body, with the same static Model2Vec model class zvec-grep defaults to -- the controlled comparison for zg.
- **code-explorer-body-potion** -- Returns whole symbols, and has a second expansion step.
- **code-explorer-body-potion-d10** -- Hybrid over the source body with static embeddings, fusing 100-deep lists instead of 40.
- **code-explorer-hybrid** -- Indexes Python only, so a relevant non-Python file is unreachable for it by construction.
- **code-explorer-hybrid** -- Hybrid: FTS/BM25 fused with a vector index (Ollama nomic-embed-text) by reciprocal rank fusion.
- **code-explorer-hybrid** -- Returns whole symbols, and has a second expansion step, so its `bundle` row differs from its `seed` row.
- **zg** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg** -- Hybrid FTS+vector by default. Both tools have full-text search; the difference is whether a vector component is fused, which the observed-mode table above records per run.
- **zg** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg** -- Has no expansion step, so its `bundle` row repeats its `seed` row. That is its correct answer, not a missing measurement.
- **zg-full** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg-full** -- Hybrid FTS+vector, returning full source previews -- the configuration whose token cost is comparable to an assembled context bundle.
- **zg-full** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg-full** -- Has no expansion step, so its `bundle` row repeats its `seed` row.
- **zg-symbol** -- Indexes every file type, so it can reach relevant files code-explorer never sees.
- **zg-symbol** -- Hybrid FTS+vector, biased toward exact indexed symbols (--prefer-symbol) -- the closest match to how code-explorer is meant to be queried.
- **zg-symbol** -- Returns text chunks, not whole symbols -- which is why scoring is at file level.
- **zg-symbol** -- Has no expansion step, so its `bundle` row repeats its `seed` row.

