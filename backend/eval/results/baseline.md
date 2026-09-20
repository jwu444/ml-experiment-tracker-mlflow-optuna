# Retrieval eval — baseline

## Configuration

| Setting | Value |
| --- | --- |
| `chunk_max_chars` | 1000 |
| `chunk_overfetch` | 4 |
| `retrieval_top_k` | 8 |
| `voyage_model` | voyage-4 |

## Aggregate

- queries: **20**
- MRR: **0.942**
- precision@3: 0.567
- precision@5: 0.400
- precision@8: 0.269
- recall@3: 0.708
- recall@5: 0.792
- recall@8: 0.846

## Per query

| query | RR | P@3 | P@5 | P@8 |
| --- | --- | --- | --- | --- |
| which-model-won-revenue | 1.00 | 0.33 | 0.20 | 0.12 |
| which-ridge-run-won-pc-video-card | 1.00 | 0.67 | 0.40 | 0.25 |
| gradient-boosting-vs-random-forest-revenue | 0.33 | 0.33 | 0.20 | 0.25 |
| worst-model-family-revenue | 1.00 | 0.33 | 0.20 | 0.25 |
| baseline-vs-random-forest-revenue | 1.00 | 0.33 | 0.40 | 0.25 |
| ridge-alpha-range-revenue | 1.00 | 0.67 | 0.80 | 0.50 |
| ridge-alpha-range-pc-video-card | 1.00 | 0.67 | 0.60 | 0.38 |
| gradient-boosting-hyperparam-range-revenue | 1.00 | 1.00 | 0.80 | 0.50 |
| random-forest-hyperparam-range-revenue | 1.00 | 1.00 | 0.80 | 0.50 |
| feature-count-comparison | 1.00 | 0.33 | 0.20 | 0.12 |
| gradient-boosting-worse-than-baseline | 1.00 | 1.00 | 0.60 | 0.50 |
| ridge-alpha-outlier-revenue | 1.00 | 0.67 | 0.40 | 0.25 |
| random-forest-worst-run-settings | 0.50 | 0.67 | 0.40 | 0.25 |
| runs-with-diagnostic-writeups | 1.00 | 1.00 | 0.60 | 0.38 |
| pc-video-card-worst-run-diagnosis | 1.00 | 0.33 | 0.20 | 0.12 |
| revenue-panel-missingness | 1.00 | 0.33 | 0.20 | 0.12 |
| revenue-panel-shape | 1.00 | 0.33 | 0.20 | 0.12 |
| revenue-panel-feature-correlations | 1.00 | 0.33 | 0.20 | 0.12 |
| revenue-eda-and-baseline-performance | 1.00 | 0.67 | 0.40 | 0.25 |
| revenue-target-variable-eda | 1.00 | 0.33 | 0.20 | 0.12 |

## Notes

**Weakest query: `gradient-boosting-vs-random-forest-revenue` (RR 0.33, first relevant hit
at rank 3).** The query asks which of the two model families won on revenue-nowcast; the
two labelled sources are the notes for `random_forest`'s and `gradient_boosting`'s best
runs (`df3293ff`, `5f90c1ac`). Ranks 1–2 are instead two *other* random-forest
hyperparameter-sweep notes (`40b66746`, unlabelled here). The corpus holds four approved
notes per family on the same dataset, written to a similar template (params + holdout
rmse), so cosine similarity clusters all of one family's run notes together and cannot
reliably separate "the best one" from its siblings by hyperparameter values alone. This
looks like a real limitation of note-level embedding granularity on this corpus rather
than a retrieval bug — checked by hand via `retrieval.search_runs` outside the harness,
not `POST /agent/chat` (the server was down for this run; the ranked list itself makes the
cause legible without it).

**Second-weakest: `random-forest-worst-run-settings` (RR 0.50).** Same failure mode: rank 1
is `40b66746`, a random-forest note from the hyperparameter-sweep family, ahead of both
labelled sources (`e1d835ba` at rank 2, `df3293ff` at rank 3). This is the same
within-family clustering as above, not an independent issue.

**Systematic pattern by query shape.** Grouping the 20 queries into the four shapes from
Task 6: the "which model/run won" comparison shape (5 queries) averages RR 0.866 and is
the only shape with any query below RR 1.00 — both queries above are in it. The
parameter-range shape (RR 1.00 avg) and the diagnostics/what-went-wrong shape (RR 0.90 avg,
dragged down by the second query above) both fare better. Comparison queries are
structurally harder here: the labelled answer is one specific run's note inside a cluster
of 3-4 near-identical siblings from the same model family and dataset, while a
parameter-range query's relevant set is usually *all* of that cluster, so within-cluster
confusion barely costs it anything.

**No query scored 0.0 across every cutoff** — the lowest RR (0.33) still landed inside the
top 3, and every query's `P@3` is nonzero.

**The four single-relevant-source EDA queries** (`revenue-panel-missingness`,
`revenue-panel-shape`, `revenue-panel-feature-correlations`, `revenue-target-variable-eda`)
show `P@3 = 0.33`, `P@5 = 0.20`, `P@8 = 0.12` — exactly `1/k` — because the corpus has
exactly one indexed EDA document (three approved write-ups on `revenue-nowcast`
concatenate into a single chunk-table key) and it was found in all four cases (RR 1.00).
This is an arithmetic ceiling on precision, identical across every configuration the sweep
will try, not a retrieval weakness; `recall@k` and MRR are what actually discriminate for
these four, and both are perfect.

**Recall is monotonic** — `recall@3` 0.708 ≤ `recall@5` 0.792 ≤ `recall@8` 0.846 — as
expected from three cutoffs over one ranked list.

**MRR (0.942) is comfortably short of 1.000**, driven entirely by the two queries above;
no restatement-of-answer concern (D44).
