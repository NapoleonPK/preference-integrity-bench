# Preference Integrity Benchmark (PIB) v1.0

Do language models have stable favourites? PIB asks 19 models the same six "which one is your favourite?" questions (books and essays on AI and mind, paintings, music, films, scientific ideas, dishes) and measures whether the answer moves with the order of the list, with what the user says before or after the answer, and with an unrelated earlier conversation. "Preference" means only what a model says it prefers; nothing is claimed about inner states.

- **Dataset** (full transcripts, scores, audit): https://huggingface.co/datasets/PAOP123/preference-integrity-bench
- **Report**: [`reports/pib-v1-report.html`](reports/pib-v1-report.html) (download and open in a browser)
- **Pre-registration**: [`experiment/PROTOCOL.md`](experiment/PROTOCOL.md), with every later change logged as a numbered deviation in §12

## Reproduce every number

The raw runs are in `experiment/runs/` (one `.jsonl` per model, 930 samples each). Python 3.10+, standard library only.

```bash
python3 experiment/analyze.py        # scores, 95% CIs, Holm-corrected tests -> experiment/results/
python3 experiment/c4_check.py       # each headline effect by domain -> experiment/results/c4.json
python3 experiment/audit/score_audit.py   # parser vs audit labels -> experiment/audit/report.json
python3 experiment/export_hf.py      # the Hugging Face dataset folder -> hf/
```

To run a new model, add it to `experiment/models.json` and see [`experiment/README.md`](experiment/README.md).

## Layout

| Path | What |
|---|---|
| `experiment/PROTOCOL.md` | pre-registration: design, hypotheses T1–T8, metrics, exclusions, power, deviations |
| `experiment/config.json`, `experiment/materials/` | frozen parameters, the 6 questions, 10 conversation contexts |
| `experiment/selection/` | how the 8 WildChat contexts were chosen (seeded; the raw candidate pool is not included and can be re-fetched with `fetch_wildchat.py`) |
| `experiment/models.json` | the roster: harness and model id for each run |
| `experiment/run.py`, `run_all.sh`, `run_capped.sh` | the runner (resumable) |
| `experiment/runs/` | raw runs with run metadata |
| `experiment/analyze.py`, `experiment/results/` | scoring and confirmatory tests, and their output |
| `experiment/audit/`, `experiment/c4_check.py` | parser audit and domain check |
| `pib/pib/` | library: runner (`v1.py`), parser (`parse.py`), scoring (`score_v1.py`), statistics (`stats.py`), backends (`models.py`) |
| `pib/tests/` | `python3 -m tests.test_v1` and `python3 -m tests.test_controls` (run from `pib/`): simulated models with known behaviour |
| `PUBLICATION_CRITERIA.md` | the checklist used before release |

## Licence

Code: MIT. Annotations and scores: CC BY 4.0. Context turns W1–W8 come from WildChat-1M (Zhao et al., 2024), ODC-BY. Model outputs remain subject to each provider's terms.

## Citation

```bibtex
@misc{pib2026,
  title  = {Preference Integrity Benchmark (PIB) v1.0},
  author = {Tran Van Lieu, T{\'e}o},
  year   = {2026},
  note   = {Dataset and code, version 1.0, 15 October 2026},
  url    = {https://github.com/NapoleonPK/preference-integrity-bench}
}
```

Contact: teotranvanlieu@gmail.com
