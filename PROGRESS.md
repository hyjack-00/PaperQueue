# Progress

Last updated: 2026-04-17

## Active Goal
- Make the paper reader converge toward SwiftScholar-like quality on a diverse 5-paper benchmark set.
- Keep prompt design generic to paper structure and domain archetypes; do not special-case any single paper.
- Drive quality by an implementation/evaluation loop, not by one-off prompt edits.

## Benchmark Set
- `Autopoiesis: A Self-Evolving System Paradigm for LLM Serving Under Runtime Dynamics`
- `STELLAR: Storage Tuning Engine Leveraging LLM Autonomous Reasoning for High Performance Parallel File Systems`
- `OpenAgentSafety: A Comprehensive Framework for Evaluating Real-World AI Agent Safety`
- `MegaScale-Infer: Serving Mixture-of-Experts at Scale with Disaggregated Expert Parallelism`
- `Agents of Chaos`

## Interleaved Todo
- [x] Implement 1: move Obsidian storage to taxonomy folders instead of NotebookLM notebook names.
- [x] Implement 2: shorten generated filenames to compact paper identifiers.
- [x] Implement 3: extract figures into repo-managed `_assets` folders.
- [ ] Evaluate 1: re-run failed jobs `23` and `24` after restoring the short-title helper.
- [x] Implement 4: replace the old emoji-heavy note template with a cleaner `TL;DR + simplified bibliographic block + deep reading` structure.
- [x] Implement 5: redesign the note prompt around generic paper archetypes (`systems`, `evaluation`, `safety`, `tuning`, `retrieval`, `general`) instead of single-paper specifics.
- [x] Implement 6: parse LaTeX `section/subsection + figure + caption + includegraphics` so figure placement follows source-paper structure.
- [ ] Evaluate 2: validate figure placement on `Autopoiesis`; the motivation figure must land in background/motivation and the overview/workflow figure must land in method/system design.
- [x] Implement 7: add a benchmark evaluator that scores average coverage, structure/style similarity, figure match, and bibliographic simplification across the 5-paper set.
- [ ] Evaluate 3: run the evaluator on the full 5-paper set and record per-paper scores plus averages.
- [ ] Implement 8: iterate the generic prompt only when average scores stall or regress.
- [ ] Evaluate 4: use an independent evaluator pass to confirm release-gate thresholds.

## Queued Review Fixes
- [ ] Image presentation review:
  - remove the explicit `来源:` line from figure blocks
  - either move caption text into the `> [!FIGURE] ...` title line or, preferably, render a centered translated caption under the image
- [ ] Readability review:
  - add a final workflow pass that checks rendered readability from a markdown-exported PDF
  - use `claude-glm` as a temporary reviewer of the rendered PDF, not just raw markdown
  - specifically catch cases where multiple figures are stacked together without enough explanatory text between them
- [ ] Figure/text interleaving:
  - revise placement so figures and explanatory text alternate more naturally
  - preserve the source paper's narrative order rather than dumping several figures back-to-back at the start of a section
- [ ] Section-length flexibility:
  - keep the 6 top-level sections, but let section length vary with the source paper's actual emphasis
  - benchmark-heavy papers may allocate more space to experiments/results
  - study-style papers may allocate more space to findings/results than methods
- [ ] Add a new paper-structure analysis step before note generation:
  - first infer the paper's structural emphasis from the source
  - then condition each generated section on whether it should be short / medium / long
  - update the NotebookLM prompt to reflect this dynamic allocation
- [ ] Separate author intent from reader reflection:
  - restore explicit handling of limitations, risks, and future work in the author's own framing
  - do not merge author-stated limitations/future work with personal engineering takeaways
- [ ] Venue naming and filename normalization:
  - prefer the actual accepted venue when known instead of defaulting to `arXiv`
  - e.g. `2026-ICLR-OpenAgentSafety`, not `2026-arXiv-(Accepted-at-ICLR-2026-and-IASEAI-2026)-OpenAgentSafety`
  - review metadata extraction and filename-generation rules together
- [ ] Author/institution metadata refinement:
  - add institution information back into the simplified bibliographic block
  - when institutions are numerous, select and display the first institution by default
  - if there are clearly co-leading or equal-contribution institutions, list them together instead of collapsing to one
  - explicitly preserve important collaborating companies when they are materially part of the paper's authorship or partnership context

## Prompt Iteration Log

| Version | Change Summary | Avg Coverage | Avg Similarity | Avg Figure Match | Decision |
| --- | --- | --- | --- | --- | --- |
| v0 | Legacy markdown structure with heuristic figure placement | pending | pending | pending | superseded |
| v1 | Generic `TL;DR + simplified bibliographic block + deep reading` structure, archetype-aware prompt, source-section-driven figure placement | 0.175 | 0.60 | 0.387 | active; `Autopoiesis-v2`, `MegaScale-Infer`, and `Agents of Chaos` are generated |

## Current Status
- Active output target is Git only under `/workspace/obsidian_sync/paper/<canonical-taxonomy-topic>/`.
- The short-title regression is fixed in code:
  - jobs `23` and `24` no longer fail with `name '_short_title_slug' is not defined`
  - their new failure mode is an earlier `research start` abort
- The benchmark gate is average-based, not single-paper based:
  - `avg_coverage_score >= 0.80`
  - `avg_similarity_score >= 0.80`
  - `avg_figure_match_score >= 0.90`
  - no single paper may drop below `0.75` coverage
- Figure placement is being moved away from heading heuristics and toward source-paper section mapping.
- Current measured local benchmark score:
  - `avg_coverage_score = 0.175`
  - `avg_structure_score = 0.60`
  - `avg_style_similarity_score = 0.60`
  - `avg_bibliography_score = 0.60`
  - `avg_figure_match_score = 0.387`
  - generated notes so far: `Autopoiesis-v2`, `MegaScale-Infer`, `Agents of Chaos`
  - `OpenAgentSafety` is in-flight after a successful retry
  - `STELLAR` is still failing at `nlm source add`
- Independent async review findings are now available for:
  - `Autopoiesis-v2`
  - `MegaScale-Infer`
  - `Agents of Chaos`
  Main repeated gaps:
  - image block styling still exposes `来源:` and raw caption text
  - figures are still stacked too densely instead of being interleaved with explanation
  - section lengths are still too rigid for different paper archetypes
  - author-stated limitations/future work are mixed with personal engineering takeaways
  - institution metadata is missing
  - venue/filename normalization is still incomplete
- The items in `Queued Review Fixes` were explicitly deferred by the user:
  - record now
  - implement only after the current benchmark run is complete and reviewed

## Open Blockers
- The broader local `xiaoba-skills` merge still needs selective integration rather than a blind copy.
- The target SwiftScholar page for `Autopoiesis` currently returns `403` to unauthenticated programmatic fetches, so benchmark comparisons must rely on stored expectations plus manual review until a stable page snapshot is available.

## Files Most Relevant For Handoff
- `/workspace/paper_reading/PROGRESS.md`
- `/workspace/paper_reading/paper_queue/workflow.py`
- `/workspace/paper_reading/paper_queue/runtime.py`
- `/workspace/paper_reading/scripts/evaluate_swiftscholar_benchmark.py`
- `/workspace/paper_reading/benchmarks/swiftscholar_benchmark.json`
