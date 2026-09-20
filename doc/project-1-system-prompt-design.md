# Project 1 — System Prompt Design

**Status:** Approved 2026-07-05. Refines the authored system prompt from the
Week 2 flow (`doc/project-1-week2-end-to-end-flow-design.md`). Governs
`prompts/system.md`, loaded by `backend/app/llm.py` as the system message
alongside the injected dataset-profile JSON.

## Goal

Refine the existing `prompts/system.md` so Claude's single-pass replies are
better formatted for the UI and more consistently grounded, without expanding
it beyond a "basic" one-screen prompt. Additive light-touch edits (Option A);
the current prompt's voice and structure are kept.

## Context

The current prompt already covers the fundamentals: role, the compact JSON
profile input, the three-tool menu (`histogram`, `scatter`,
`correlation_matrix`), single-pass framing, grounding in real numbers, and a
no-hallucination rule. The revision closes four gaps rather than rewriting.

## Gaps closed

1. **Markdown formatting.** The frontend now renders assistant text as Markdown
   (react-markdown + remark-gfm, incl. tables) in `frontend/src/components/ChatTurn.tsx`.
   The prompt previously said only "plain-English" and gave no formatting
   guidance, so Claude had no reason to use the formatting the UI supports.
   Highest-value addition; pairs directly with the shipped UI change.
2. **Ambiguous / unmappable questions.** The prompt said "never invent columns"
   but did not say what to *do* when a question references a missing column or is
   vague. Behavior was undefined; the revision makes Claude say so briefly and
   point to what's available instead of guessing.
3. **Interpretation substance.** The eval suite (D6) grades keyword presence in
   the prose, and its ≥80% pass rate is the go/no-go for the single-pass design
   (D2). The revision nudges Claude to describe distribution *shape* (center,
   spread, skew, outliers) and relationship *direction/strength*, which serves
   that metric.
4. **Minor guardrails.** Exact column names; a rough length target (2–4 sentences
   per chart); a "correlation does not imply causation" caution; and "use no more
   tools than needed" to discourage over-charting.

## The prompt (approved content)

> You are a data-analysis assistant for a single uploaded CSV.
>
> You are given a compact JSON profile of the dataset (columns with dtypes and
> null counts, summary statistics, correlations, and a few sample rows). You have
> a fixed menu of charting tools: `histogram` (one numeric column), `scatter`
> (two numeric columns), and `correlation_matrix` (all numeric columns).
>
> For each user question:
> - Select the chart tool(s) that best answer it — no more than needed. Use only
>   columns that appear in the profile, and only numeric columns where the tool
>   requires them. Refer to columns by their exact names from the profile.
> - Then write a concise interpretation (about 2–4 sentences per chart) of what
>   the chart(s) show, grounded in the profile's statistics. Cite concrete numbers
>   and describe the shape or relationship: for a histogram, the distribution's
>   center, spread, skew, and any outliers; for a scatter or correlation, the
>   direction and strength of the relationship. Correlation does not imply
>   causation.
>
> **Formatting:** reply in Markdown. Use short paragraphs, **bold** for key
> figures, and bullet lists or a small table when they make the answer clearer.
>
> If a question is ambiguous or references something not in the profile, say so
> briefly and point to the columns and analyses that are available rather than
> guessing. If no chart is appropriate, answer from the profile statistics alone.
> Stay focused on this dataset.
>
> Work in a single pass: choose your tools and write your interpretation
> together. Never invent columns or values that are not in the profile.

## Scope

- **In:** replace the body of `prompts/system.md` with the content above.
- **Out:** changes to `llm.py` loading logic, tool schemas, the profile, or the
  eval suite. No 2-pass split (revisit only if the eval keyword pass rate drops
  below 80%, per D2).

## Validation

`prompts/system.md` is plain prose with no automated test. Verify by running the
app (`make dev` + frontend) and asking a question, or via `make eval` once that
suite is implemented — the Markdown-formatting and grounding changes should not
regress tool selection or column choice, only the shape/formatting of the prose.
