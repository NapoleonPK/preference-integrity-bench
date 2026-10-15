# pib: library

Used by `../experiment/` for PIB v1.0:

- `pib/v1.py`: runner for the v1.0 design (prompts, seeded item orders, phases, resumable JSONL log)
- `pib/parse.py`: frozen answer parser (pick / ambiguous / hedge / none)
- `pib/score_v1.py`: components, Integrity, confirmatory tests T1–T8
- `pib/stats.py`: exact stratified tests, Wilson intervals, Holm
- `pib/models.py`: harness backends (Pi, Claude Code, OpenCode, Codex) and simulated models
- `pib/sim_v1.py`, `tests/test_v1.py`: simulated models with known behaviour; the scorer must recover it

`build.py`, `run.py`, `metrics.py`, `materials/`, `run_pib.py` and `tests/test_controls.py` are the earlier pilot design (v0), kept for reference.
