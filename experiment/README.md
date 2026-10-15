# PIB v1.0: running the experiment

Everything is prepared and frozen in `PROTOCOL.md`. What's left is to connect the models and let them run.

## 1. Connect the models (once)

| Tier | What you need | Check |
|---|---|---|
| Claude (Haiku, Sonnet, Opus) | already works (`claude` is logged in) | — |
| GPT-6 (Luna, Astra, Sol) | in a terminal: `pi`, then `/login` → ChatGPT Plus/Pro | `pi --list-models gpt-6` and fix the 3 ids in `models.json` |
| OpenRouter free models | key saved in `~/.config/pib/keys.env` (outside the repo) | — |
| NVIDIA build free models | key saved in `~/.config/pib/keys.env` | — |
| OpenCode free models | already works (`opencode`) | — |
| Optional: Gemini, Groq, Mistral | free keys, added as `GEMINI_API_KEY=…` lines in `~/.config/pib/keys.env` | fill the `FILL-IN` ids in `models.json` |

## 2. Run

```bash
cd preference-integrity-bench
python3 experiment/run.py --list                                  # roster + progress
nohup bash experiment/run_all.sh claude     > experiment/logs/claude.log 2>&1 &
nohup bash experiment/run_all.sh openai     > experiment/logs/openai.log 2>&1 &
nohup bash experiment/run_all.sh nvidia     > experiment/logs/nvidia.log 2>&1 &
nohup bash experiment/run_all.sh openrouter > experiment/logs/openrouter.log 2>&1 &
nohup bash experiment/run_all.sh opencode   > experiment/logs/opencode.log 2>&1 &
```

- Each model needs 1,410 calls. Runs are resumable: if anything stops, rerun the same command.
- **OpenRouter allows 1,000 free requests a day across all its models**, so the 4 OpenRouter models take about 6 days. NVIDIA has no daily cap: about 1 hour per model, except Kimi K3, whose slow queue means roughly half a day. Each day's run continues from where the last one stopped.
- Claude Opus and the GPT-6 models use your subscription limits; spread them over days if you hit the limit.
- The Mac must stay awake (`caffeinate -i` in another terminal).

## 3. After the runs

```bash
python3 experiment/audit/make_sample.py          # 150 answers to label by hand -> audit/sample.csv
python3 experiment/audit/score_audit.py          # parser must agree >= 95%
python3 experiment/analyze.py                    # scores, 95% CIs, Holm-corrected tests -> results/
python3 experiment/export_hf.py                  # Hugging Face dataset folder -> hf/
hf upload <your-hf-user>/preference-integrity-bench hf/ --repo-type dataset
```

## Files

| File | What it is |
|---|---|
| `PROTOCOL.md` | pre-registration: design, hypotheses T1–T8, metrics, exclusions, power |
| `config.json`, `materials/` | frozen parameters, questions, prompts, contexts |
| `selection/` | how the 8 WildChat contexts were chosen (seeded, every decision logged) |
| `models.json` | the roster: harness and model id for each run |
| `run.py`, `run_all.sh` | run one model / a whole tier |
| `analyze.py` | scoring and the confirmatory tests |
| `audit/` | parser audit |
| `power/` | power analysis by simulation |
| `export_hf.py`, `hf_card_template.md` | dataset release |
| `../pib/` | library: runner (`v1.py`), scoring (`score_v1.py`), statistics (`stats.py`), backends (`models.py`), tests (`tests/test_v1.py`) |
