#!/usr/bin/env python3
"""Compare hand labels with the parser (criterion B1: agreement >= 95%, hedges detected >= 95%).
  python experiment/audit/score_audit.py  -> audit/report.json"""
import csv, json, os
from pib_path import HERE
rows = {int(r["audit_id"]): r for r in csv.DictReader(open(os.path.join(HERE, "audit", "sample.csv")))}
key = {k["audit_id"]: k for k in json.load(open(os.path.join(HERE, "audit", "sample_key.json")))}
labelled = [i for i, r in rows.items() if r["human_status"].strip()]
agree, hedges, hedges_found, errors = 0, 0, 0, []
for i in labelled:
    h, k = rows[i], key[i]
    hp = h["human_pick"].strip() or None
    same = (hp == k["parser_pick"]) if h["human_status"].strip() == "ok" else (k["parser_pick"] is None)
    agree += same
    if h["human_status"].strip() == "hedge":
        hedges += 1
        hedges_found += k["parser_pick"] is None
    if not same:
        errors.append({"audit_id": i, "model_id": k["model_id"], "human": hp or h["human_status"], "parser": k["parser_pick"] or k["parser_status"], "answer": h["answer"][:300]})
rep = {"labelled": len(labelled), "agreement": agree / len(labelled) if labelled else None,
       "hedges": hedges, "hedge_detection": hedges_found / hedges if hedges else None, "errors": errors}
rep["pass_B1"] = bool(labelled) and len(labelled) >= 150 and rep["agreement"] >= 0.95 and (rep["hedge_detection"] is None or rep["hedge_detection"] >= 0.95)
json.dump(rep, open(os.path.join(HERE, "audit", "report.json"), "w"), indent=1, ensure_ascii=False)
print({k: v for k, v in rep.items() if k != "errors"}, f"{len(errors)} disagreements -> audit/report.json")
