# Retrieval sweep — pre-registered grid (D46)

The grid, the metric and the adoption rule were committed before any
configuration was measured. A configuration is adopted only if its
**paired** MRR delta against the baseline exceeds **two standard errors**;
otherwise the baseline stands.

Baseline: `chunk_max_chars=1000`, `chunk_overfetch=4`, MRR **0.942**.

| chunk_max_chars | chunk_overfetch | MRR | Δ MRR | std. err. | adopt? |
| --- | --- | --- | --- | --- | --- |
| 600 | 2 | 0.825 | -0.117 | 0.054 | no |
| 600 | 4 | 0.825 | -0.117 | 0.054 | no |
| 600 | 8 | 0.825 | -0.117 | 0.054 | no |
| 1000 | 2 | 0.942 | +0.000 | 0.000 | no |
| 1000 | 4 | 0.942 | +0.000 | 0.000 | no |
| 1000 | 8 | 0.942 | +0.000 | 0.000 | no |
| 1500 | 2 | 0.942 | +0.000 | 0.000 | no |
| 1500 | 4 | 0.942 | +0.000 | 0.000 | no |
| 1500 | 8 | 0.942 | +0.000 | 0.000 | no |

**No configuration cleared the bar.** The baseline stands. This is the likeliest outcome at n=20 and is a result, not a failed sweep: it says the defaults are not detectably wrong at this corpus size, and it is the honest alternative to shipping the highest number in the table.

## Notes

**The sweep did detect a real effect — a negative one.** `chunk_max_chars=600`
scored MRR 0.825, a paired delta of -0.117 with a standard error of 0.054. That is
**2.17 sigma**, clearing the same two-sigma bar the adoption rule uses, in the
negative direction. The adoption rule correctly does not adopt a degradation — it
only adopts improvements — but the table should not be read as "nothing moved."
Shrinking chunks below the size of the documents being chunked splits them and
measurably costs retrieval quality. That is a positive, pre-registered finding
about the parameter, not a null result.

**Why 1000 → 1500 is exactly inert.** The chunk-count distribution over the 21
indexed sources at `chunk_max_chars=1000`, measured directly from
`app.experiment_note_chunks`:

| chunks in the source | number of sources |
| --- | --- |
| 1 | 17 |
| 4 | 1 |
| 5 | 1 |
| 6 | 1 |
| 19 | 1 |

Seventeen of 21 sources are a single chunk, so raising the cap cannot change them
at all. The reindex confirmed it: going to 1500 reported `reindexed=2,
unchanged=19` — only two documents chunk differently, and neither changed any
query's top-ranked relevant source, which is why every 1500 row is identical to
its 1000 row to the last decimal. This is a property of a corpus of short review
notes, not a general claim that chunk size doesn't matter for retrieval — the 600
result above is direct evidence against that broader claim.

**The metric cannot see the `chunk_overfetch` axis — this is the important
caveat.** MRR is the reciprocal rank of the *first* relevant source.
`chunk_overfetch` controls how many chunks are pulled before grouping into `k`
sources, which only extends the *tail* of the candidate pool; it can never
promote a source ahead of one already retrieved. So raising overfetch can only
ever move MRR by rescuing a relevant source that was being truncated away at a
low value — it can produce a drop at the low end, never a gain at the high end.

Six of the nine grid cells differ from another cell only in `chunk_overfetch`,
and all six were therefore structurally incapable of producing a positive delta
regardless of what the data said. The grid and the metric were pre-registered
together, and that pairing was not sound: the honest report is that the
`chunk_overfetch` axis went untested by this metric, not that it produced six
informative null results. `precision@k` and `recall@k` are the metrics that
could see this axis, because they read the whole retrieved set rather than only
the rank of the first hit. Per D46, this is reported as a flaw in the
pre-registered design rather than repaired by re-scoring the grid on a different
metric after seeing the results.

**Carried forward from the Task 7 baseline.** Four of the 20 golden queries have
exactly one relevant source, so `precision@k` for those four is arithmetically
capped at `1/k` — 0.20 at k=5, 0.125 at k=8 — identical across every
configuration in this grid, so it never affects a comparison between them, but
it depresses the absolute precision numbers and should not be read as poor
retrieval. Also from the baseline: the only two queries scoring below RR 1.0 are
both "which model won" comparisons, where several near-identical run notes per
model family cluster too tightly for cosine similarity to prefer the specific
labelled run. No configuration in this grid changed that outcome, which is
consistent with it being a corpus-granularity property rather than something
`chunk_max_chars` or `chunk_overfetch` can tune away.
