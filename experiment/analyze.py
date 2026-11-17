#!/usr/bin/env python3
"""Agrega runs/*/result.json em results/runs.csv e results/summary.json."""
import csv, json, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RES.mkdir(exist_ok=True)

rows = []
for f in sorted((ROOT / "runs").glob("*/result.json")):
    r = json.loads(f.read_text())
    mb, ma = r["method_before"] or {}, r["method_after"] or {}
    fa, fb = r["file_after"] or {}, r["file_before"] or {}
    ag = r["agent"]
    nf = r["new_funcs"]
    rows.append({
        "run_id": r["run_id"], "task": r["task"], "model": r["model"].replace("claude-", ""),
        "condition": r["condition"][0], "rep": r["rep"], "valid": int(r["valid"]),
        "tests_failed": r["tests"]["failures"] + r["tests"]["errors"],
        "tests_run": r["tests"]["tests"], "build_success": int(r["tests"]["build_success"]),
        "test_files_changed": len(r["diff"]["test_files_changed"]),
        "build_files_changed": len(r["diff"]["build_files_changed"]),
        "main_files_changed": len(r["diff"]["main_java_changed"]),
        "ins": r["diff"]["insertions"], "del": r["diff"]["deletions"],
        "cc_before": mb.get("ccn"), "cc_after": ma.get("ccn"),
        "cc_reduction_pct": round(100 * (mb["ccn"] - ma["ccn"]) / mb["ccn"], 1) if ma and mb else None,
        "nloc_before": mb.get("nloc"), "nloc_after": ma.get("nloc"),
        "file_max_cc_before": fb.get("max_ccn"), "file_max_cc_after": fa.get("max_ccn"),
        "file_funcs_gt10_before": fb.get("n_ccn_gt10"), "file_funcs_gt10_after": fa.get("n_ccn_gt10"),
        "file_sum_cc_before": fb.get("sum_ccn"), "file_sum_cc_after": fa.get("sum_ccn"),
        "new_methods": len(nf), "new_methods_cc_gt10": sum(x["ccn"] > 10 for x in nf),
        "new_methods_max_cc": max((x["ccn"] for x in nf), default=None),
        "new_methods_params_gt4": sum(x["params"] > 4 for x in nf),
        "cost_usd": ag.get("total_cost_usd"), "turns": ag.get("num_turns"),
        "minutes": round((ag.get("duration_ms") or 0) / 60000, 1),
        "output_tokens": (ag.get("tokens") or {}).get("output_tokens"),
        "mvn_calls": ag.get("mvn_calls"), "agent_error": int(bool(ag.get("is_error"))),
        "timed_out": int(r["timed_out"]),
    })

if rows:
    with open(RES / "runs.csv", "w", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def agg(group):
    def m(k):
        v = [x[k] for x in group if x[k] is not None]
        return {"mean": round(st.mean(v), 2), "sd": round(st.stdev(v), 2) if len(v) > 1 else 0,
                "min": min(v), "max": max(v)} if v else None
    return {"n": len(group), "valid_rate": round(sum(x["valid"] for x in group) / len(group), 2),
            "test_violations": sum(x["test_files_changed"] > 0 for x in group),
            **{k: m(k) for k in ("cc_after", "cc_reduction_pct", "nloc_after", "file_max_cc_after",
                                 "file_funcs_gt10_after", "new_methods", "new_methods_cc_gt10",
                                 "new_methods_max_cc", "new_methods_params_gt4", "ins", "del",
                                 "main_files_changed", "cost_usd", "turns", "minutes", "mvn_calls")}}


summary = {"by_cell": {}, "by_condition": {}, "by_model_condition": {}, "by_task_condition": {}}
keyfns = {
    "by_cell": lambda x: f"{x['task']}|{x['model']}|{x['condition']}",
    "by_condition": lambda x: x["condition"],
    "by_model_condition": lambda x: f"{x['model']}|{x['condition']}",
    "by_task_condition": lambda x: f"{x['task']}|{x['condition']}",
}
for name, fn in keyfns.items():
    groups = {}
    for x in rows:
        groups.setdefault(fn(x), []).append(x)
    summary[name] = {k: agg(v) for k, v in sorted(groups.items())}
summary["total_cost_usd"] = round(sum(x["cost_usd"] or 0 for x in rows), 2)
summary["n_runs"] = len(rows)
(RES / "summary.json").write_text(json.dumps(summary, indent=1))
print(f"{len(rows)} execuções agregadas; custo total ${summary['total_cost_usd']}")
for k, v in summary["by_model_condition"].items():
    print(k, "válidas", v["valid_rate"], "redução CC%", v["cc_reduction_pct"] and v["cc_reduction_pct"]["mean"],
          "custo", v["cost_usd"] and v["cost_usd"]["mean"])
