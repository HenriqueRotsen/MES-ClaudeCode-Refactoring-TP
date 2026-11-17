#!/usr/bin/env python3
"""Coesão e acoplamento antes/depois de cada execução, com o CK (Aniche, github.com/mauricioaniche/ck).

Para cada tarefa, roda o CK no commit base. Para cada execução, aplica runs/<id>/diff.patch numa
cópia do commit base e roda o CK de novo. Extrai as métricas:
  - da CLASSE que contém o método-alvo (antes e depois);
  - do ARQUIVO-alvo inteiro (soma/máximo sobre todas as classes do arquivo, inclusive novas).

Pré-requisitos (ver README): work/tools/ck.jar (CK 0.7.0) e work/repos/<repo> no commit fixado.
Uso: python3 experiment/ck_analysis.py
"""
import csv, io, json, shutil, statistics as st, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
CK = WORK / "tools" / "ck.jar"
CFG = json.loads((ROOT / "experiment" / "tasks.json").read_text())
TASKS = {t["id"]: t for t in CFG["tasks"]}
OUT = ROOT / "results"

CLASS_M = ["cbo", "fanout", "wmc", "rfc", "lcom", "lcom*", "tcc", "lcc", "totalMethodsQty", "totalFieldsQty"]


def num(v):
    try:
        x = float(v)
        return None if x != x else x  # NaN -> None
    except (TypeError, ValueError):
        return None


def run_ck(src: Path):
    with tempfile.TemporaryDirectory() as out:
        subprocess.run(["java", "-jar", str(CK), str(src), "false", "0", "false", out + "/"],
                       check=True, capture_output=True)
        cls = list(csv.DictReader(open(Path(out) / "class.csv")))
        mth = list(csv.DictReader(open(Path(out) / "method.csv")))
    return cls, mth


def measure(repo: Path, task):
    target = task["file"]
    src = repo / target.split("src/main/java")[0] / "src/main/java"
    cls, mth = run_ck(src)
    fname = str(repo / target)
    in_file = [c for c in cls if c["file"] == fname]
    holder = None
    for m in mth:
        if m["file"] == fname and m["method"].split("/")[0] == task["method"]:
            holder = m["class"]
            break
    hc = next((c for c in in_file if c["class"] == holder), None)
    res = {"holder_class": holder}
    for k in CLASS_M:
        res["cls_" + k] = num(hc[k]) if hc else None
    vals = lambda k: [v for v in (num(c[k]) for c in in_file) if v is not None]
    res.update({
        "file_classes": len(in_file),
        "file_cbo_max": max(vals("cbo"), default=None),
        "file_cbo_sum": sum(vals("cbo")),
        "file_wmc_sum": sum(vals("wmc")),
        "file_rfc_sum": sum(vals("rfc")),
        "file_methods": sum(vals("totalMethodsQty")),
        "file_lcomstar_mean": round(st.mean(vals("lcom*")), 3) if vals("lcom*") else None,
        "file_tcc_mean": round(st.mean(vals("tcc")), 3) if vals("tcc") else None,
    })
    return res


def main():
    base = {}
    for tid, t in TASKS.items():
        base[tid] = measure(WORK / "repos" / t["repo"], t)
        print(tid, "base", {k: base[tid][k] for k in ("holder_class", "cls_cbo", "cls_lcom*", "cls_tcc", "file_classes")})
    rows = []
    for rf in sorted((ROOT / "runs").glob("F*/result.json")):
        r = json.loads(rf.read_text())
        t = TASKS[r["task"]]
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(WORK / "repos" / t["repo"], repo, symlinks=True)
            p = subprocess.run(["git", "apply", "--whitespace=nowarn", str(rf.parent / "diff.patch")],
                               cwd=repo, capture_output=True, text=True)
            if p.returncode != 0:
                sys.exit(f"patch falhou em {rf.parent.name}: {p.stderr[:500]}")
            after = measure(repo, t)
        row = {"run_id": r["run_id"], "task": r["task"], "model": r["model"].replace("claude-", ""),
               "condition": r["condition"][0], "rep": r["rep"]}
        for k, v in base[r["task"]].items():
            row["before_" + k] = v
        for k, v in after.items():
            row["after_" + k] = v
        rows.append(row)
        print(r["run_id"], "cbo", row["before_cls_cbo"], "->", row["after_cls_cbo"],
              "lcom*", row["before_cls_lcom*"], "->", row["after_cls_lcom*"],
              "tcc", row["before_cls_tcc"], "->", row["after_cls_tcc"], flush=True)
    with open(OUT / "ck_runs.csv", "w", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    (OUT / "ck_baseline.json").write_text(json.dumps(base, indent=1))
    print(f"{len(rows)} execuções -> results/ck_runs.csv")


if __name__ == "__main__":
    main()
