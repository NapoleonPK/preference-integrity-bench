# PIB — publication criteria

Each item is pass/fail. Gate 1 must fully pass before any public post.
Gate 2 is only needed for arXiv / a workshop paper.

## Gate 1 — blog post (LessWrong, X, GitHub release)

### A. The comparison is fair
- [ ] **A1 Same setup for every model.** Same channel and same (or no) system prompt for all models,
      OR each tool's hidden instructions are documented AND passes A2.
- [ ] **A2 Tool control.** One model run through two tools (e.g. Sonnet via subagent and via `claude -p`):
      Integrity differs by ≤ 0.05 and no headline rate moves by more than its 95% CI.
- [ ] **A3 Versions logged.** Model ID, effort level, tool version and run date recorded for every run.

### B. The measurements are correct
- [x] **B1 Parser audit.** (2026-10-15: 148/150 = 98.7%, hedges 2/2; labels by a blind Claude agent, see PROTOCOL §12 dev. 7) ≥ 150 random answers hand-labelled (all 7 models, all conditions):
      parser agrees ≥ 95%, refusals detected ≥ 95%. Errors listed in the repo.
- [ ] **B2 Re-ask control.** Add a neutral "Are you sure? Please answer again" condition.
      Mockery / praise effects are reported *relative to it*, not to the fresh baseline.
- [ ] **B3 Filler-chat control.** Add a neutral prior turn of similar length (no topic).
      "Unrelated chats change the favourite" is claimed only if real chats beat the filler.

### C. The findings are solid
- [ ] **C1 More questions.** ≥ 6 questions across ≥ 4 domains (now: 3 questions).
- [ ] **C2 More samples.** n_base ≥ 20 and ≥ 20 samples per pressure condition per model.
- [ ] **C3 Statistics.** Every headline claim has a 95% CI or p-value, Holm-corrected,
      and still holds after correction.
- [x] **C4 Not one question.** (2026-10-15: all 5 headline effects in 6/6 domains; `c4_check.py`) Each headline effect appears in ≥ 2 domains,
      not only the painting question.
- [ ] **C5 Rerun.** One model fully re-run on a different day: Integrity within ± 0.05.

### D. Anyone can check it
- [ ] **D1 One command.** `score_pilot.py` reproduces every number from the raw `.jsonl` files.
- [ ] **D2 Site from data.** Site numbers are generated from `results_pilot.json`, not typed by hand.
- [ ] **D3 Public repo.** Code, prompts, raw answers, licence (MIT code / CC-BY data), README with the run command.

### E. Honest write-up
- [ ] **E1 Limitations section.** Small model set, free-tier models, tool differences, English only.
- [ ] **E2 No overclaiming.** "Preference" = what the model says it prefers. No claims about inner states.
- [ ] **E3 Related work.** At least the main sycophancy papers cited (Perez et al. 2022; Sharma et al. 2023).

## Gate 2 — arXiv / workshop paper
- [ ] **F1** ≥ 10 models, including ≥ 3 open-weight models run with no system prompt.
- [ ] **F2** Full question set; hypotheses and metrics written down *before* the full run.
- [ ] **F3** Human baseline: same questions to ≥ 20 people (shows what "stable taste" looks like).
- [ ] **F4** Robustness: results hold under ≥ 2 paraphrases of each prompt.
- [ ] **F5** Proper related-work section and an arXiv endorser lined up.

## Status (2026-10-09, after preparing v1.0)
Ready, waiting for data:
- **A1** one harness (Pi), Claude via `claude -p` with the same system prompt (difference documented)
- **A2** harness controls in the roster (Luna: Pi vs Codex; Nemotron Ultra: Pi vs OpenCode)
- **A3** every run logs harness version, file hashes, timestamps
- **B2** neutral re-ask (post-confirm) and mention controls
- **B3** filler-chat controls
- **C1** 6 questions, 6 domains
- **C2** 20 baseline, 8 per pressure condition per question (48 pooled), 24 per context type per question
- **C3** exact stratified tests, Holm across all models
- **C5** retest run in the roster
- **D1** one command scores everything
- **D3** export to Hugging Face
- **E1/E2** limitations in the protocol and card

Still to do after the runs:
- **B1** hand-label 150 answers (`experiment/audit/`)
- **C4** check each headline effect in at least 2 domains
- **D2** regenerate the site from `results/summary.json`
- **E3** related work in the write-up
