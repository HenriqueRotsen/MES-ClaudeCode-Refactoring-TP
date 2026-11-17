#!/usr/bin/env python3
"""Harness do experimento A/B: Claude Code refatorando Long Methods com/sem CLAUDE.md.

Garantias de isolamento por execução:
  1. checkout limpo do commit fixado (clone novo; HEAD e working tree verificados)
  2. sessão nova do Claude Code (CLAUDE_CONFIG_DIR vazio e exclusivo; `claude -p` único)
  3. prompt idêntico por tarefa (gerado do template; hash SHA-256 registrado)
  4. versões de ferramentas fixas (claude, java, mvn, lizard checadas a cada execução)
  5. nada herdado (diretório novo por execução, nunca reaproveitado; repo Maven local próprio
     do experimento, aquecido no baseline; ordem aleatória com semente fixa)

Uso:
  python3 runner.py plan                # gera runs/plan.json (48 execuções, ordem aleatória)
  python3 runner.py baseline            # valida testes + métricas no commit original
  python3 runner.py run [--limit N] [--only RUN_ID]
"""
import argparse, hashlib, json, os, random, re, shutil, subprocess, sys, time, csv, io
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiment"
REPOS = ROOT / "repos"
RUNS = ROOT / "runs"
TOOLS = ROOT / "tools"
SECRETS = ROOT / ".secrets" / "oauth_token"   # criado pelo usuário; nunca lido para log
CFG = json.loads((EXP / "tasks.json").read_text())
TASKS = {t["id"]: t for t in CFG["tasks"]}

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
EXPECTED = {"claude": "2.1.325"}
RUN_TIMEOUT_S = 60 * 60
TEST_TIMEOUT_S = 30 * 60
NEXT_RUN_MARGIN_USD = 0.30   # pior caso observado por execução (Sonnet no jsoup ~0,2-0,3)


def env_base():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    mvn_home = next(TOOLS.glob("apache-maven-*"))
    env["PATH"] = os.pathsep.join([str(mvn_home / "bin"), str(ROOT / ".venv" / "bin"), env["PATH"]])
    env["MAVEN_ARGS"] = f"-Dmaven.repo.local={TOOLS / 'm2'}"
    env["DISABLE_AUTOUPDATER"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def sh(cmd, cwd=None, env=None, timeout=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, shell=isinstance(cmd, str),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"falhou: {cmd}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return p


def tool_versions(env):
    v = {
        "claude": sh([CLAUDE_BIN, "--version"], env=env).stdout.strip().split()[0],
        "java": sh("java -version 2>&1 | head -1", env=env).stdout.strip(),
        "mvn": sh("mvn -v | head -1", env=env).stdout.strip(),
        "lizard": sh("lizard --version", env=env).stdout.strip(),
    }
    if v["claude"] != EXPECTED["claude"]:
        sys.exit(f"versão do claude mudou: {v['claude']} != {EXPECTED['claude']}")
    return v


def prompt_for(task):
    return (EXP / "prompts" / "template.txt").read_text().format(**task)


# ---------------------------------------------------------------- métricas
def lizard_funcs(path: Path):
    """Lista de funções {name, ccn, nloc, params, start, end} de um arquivo Java."""
    if not path.exists():
        return []
    out = sh(["lizard", "-l", "java", "--csv", str(path)], env=env_base(), check=False).stdout
    funcs = []
    for row in csv.reader(io.StringIO(out)):
        if len(row) < 11:
            continue
        nloc, ccn, tok, params, length, loc, fpath, name, longname, start, end = row[:11]
        funcs.append({"name": name, "ccn": int(ccn), "nloc": int(nloc), "params": int(params),
                      "start": int(start), "end": int(end)})
    return funcs


def method_metrics(funcs, task):
    m = [f for f in funcs if f["name"].split("::")[-1] == task["method"]]
    if not m:
        return None
    f = max(m, key=lambda x: x["ccn"])
    return {"ccn": f["ccn"], "nloc": f["nloc"]}


def file_summary(funcs):
    if not funcs:
        return {}
    cc = [f["ccn"] for f in funcs]
    return {"n_funcs": len(funcs), "max_ccn": max(cc), "sum_ccn": sum(cc),
            "avg_ccn": round(sum(cc) / len(cc), 2), "n_ccn_gt10": sum(c > 10 for c in cc),
            "nloc": sum(f["nloc"] for f in funcs)}


def surefire(ws: Path):
    tot = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for x in ws.glob("**/target/surefire-reports/TEST-*.xml"):
        try:
            r = ET.parse(x).getroot()
        except ET.ParseError:
            continue
        for k in tot:
            tot[k] += int(float(r.get(k, 0)))
    return tot


def transcript_stats(path: Path):
    res, tools, mvn_calls = None, {}, 0
    for line in path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            res = ev
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    tools[c["name"]] = tools.get(c["name"], 0) + 1
                    if c["name"] == "Bash" and re.search(r"\bmvn\b", c.get("input", {}).get("command", "")):
                        mvn_calls += 1
    out = {"tool_calls": tools, "mvn_calls": mvn_calls}
    if res:
        u = res.get("usage", {})
        out.update({k: res.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms",
                                              "duration_api_ms", "total_cost_usd", "session_id",
                                              "api_error_status", "terminal_reason")})
        out["tokens"] = {k: u.get(k) for k in ("input_tokens", "output_tokens",
                                                "cache_creation_input_tokens", "cache_read_input_tokens")}
        out["final_message"] = (res.get("result") or "")[-4000:]
    return out


# ---------------------------------------------------------------- workspace
def no_ancestor_context(ws: Path):
    """Claude Code sobe a árvore de diretórios procurando CLAUDE.md; nenhum ancestral pode ter um."""
    for d in [ws.parent, *ws.parent.parents]:
        for n in ("CLAUDE.md", "CLAUDE.local.md"):
            if (d / n).exists():
                sys.exit(f"contexto herdável encontrado: {d / n}")


def fresh_checkout(task, ws: Path, condition):
    if ws.exists():
        sys.exit(f"workspace já existe (proibido reaproveitar): {ws}")
    ws.parent.mkdir(parents=True, exist_ok=True)
    sh(["git", "clone", "-q", "--no-hardlinks", str(REPOS / task["repo"]), str(ws)])
    sh(["git", "checkout", "-q", "--detach", task["commit"]], cwd=ws)
    assert sh(["git", "rev-parse", "HEAD"], cwd=ws).stdout.strip() == task["commit"]
    assert sh(["git", "status", "--porcelain"], cwd=ws).stdout.strip() == ""
    sh(["git", "remote", "remove", "origin"], cwd=ws)
    for n in CFG["remove_files_before_run"]:
        p = ws / n
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    if condition.startswith("B"):
        shutil.copy(EXP / "CLAUDE.md", ws / "CLAUDE.md")
    g = ["git", "-c", "user.name=workspace", "-c", "user.email=workspace@localhost"]
    sh(g + ["add", "-A"], cwd=ws)
    sh(g + ["commit", "-q", "--allow-empty", "-m", "chore: workspace setup"], cwd=ws)
    return sh(["git", "rev-parse", "HEAD"], cwd=ws).stdout.strip()


def diff_metrics(ws: Path, prep, task):
    sh(["git", "add", "-A"], cwd=ws)
    names = sh(["git", "diff", "--cached", "--name-status", prep], cwd=ws).stdout.split("\n")
    numstat = sh(["git", "diff", "--cached", "--numstat", prep], cwd=ws).stdout
    patch = sh(["git", "diff", "--cached", prep], cwd=ws).stdout
    files = [l.split("\t")[-1] for l in names if l.strip()]
    ins = dele = 0
    for l in numstat.splitlines():
        a, d, _ = l.split("\t", 2)
        ins += int(a) if a.isdigit() else 0
        dele += int(d) if d.isdigit() else 0
    test_files = [f for f in files if "/src/test/" in "/" + f]
    build_files = [f for f in files if f.endswith(("pom.xml", ".gradle", ".properties"))]
    return patch, {
        "files_changed": files, "insertions": ins, "deletions": dele,
        "test_files_changed": test_files, "build_files_changed": build_files,
        "claude_md_changed": "CLAUDE.md" in files,
        "target_file_changed": task["file"] in files,
        "main_java_changed": [f for f in files if "/src/main/" in "/" + f and f.endswith(".java")],
    }


# ---------------------------------------------------------------- comandos
def cmd_plan(_):
    runs = []
    for t in CFG["tasks"]:
        for m in CFG["models"]:
            for c in CFG["conditions"]:
                for r in range(1, CFG["repetitions"] + 1):
                    short = m.split("-")[1]
                    runs.append({"run_id": f"{t['id']}__{short}__{c[0]}__r{r}",
                                 "task": t["id"], "model": m, "condition": c, "rep": r})
    # ordem por réplica (r1 de todas as células, depois r2, r3), sorteada dentro da réplica:
    # se o orçamento acabar no meio, o conjunto concluído continua balanceado
    rng = random.Random(CFG["seed"])
    by_rep = {}
    for x in runs:
        by_rep.setdefault(x["rep"], []).append(x)
    runs = []
    for rep in sorted(by_rep):
        rng.shuffle(by_rep[rep])
        runs += by_rep[rep]
    RUNS.mkdir(exist_ok=True)
    (RUNS / "plan.json").write_text(json.dumps(runs, indent=1))
    print(f"{len(runs)} execuções planejadas -> runs/plan.json")


def cmd_baseline(_):
    env = env_base()
    out = {"tool_versions": tool_versions(env), "tasks": {}}
    for t in CFG["tasks"]:
        ws = RUNS / "_baseline" / t["id"] / "repo"
        if ws.exists():
            shutil.rmtree(ws)
        prep = fresh_checkout(t, ws, "A")
        t0 = time.time()
        p = sh(t["test_cmd"], cwd=ws, env=env, timeout=TEST_TIMEOUT_S, check=False)
        funcs = lizard_funcs(ws / t["file"])
        out["tasks"][t["id"]] = {
            "test_exit": p.returncode, "test_seconds": round(time.time() - t0),
            "surefire": surefire(ws), "method": method_metrics(funcs, t), "file": file_summary(funcs),
            "funcs": funcs,
        }
        (ws.parent / "test.log").write_text(p.stdout[-20000:] + p.stderr[-5000:])
        print(t["id"], out["tasks"][t["id"]]["test_exit"], out["tasks"][t["id"]]["surefire"],
              out["tasks"][t["id"]]["method"])
    (RUNS / "baseline.json").write_text(json.dumps(out, indent=1))


def cmd_run(a):
    plan = json.loads((RUNS / "plan.json").read_text())
    base = json.loads((RUNS / "baseline.json").read_text())
    if not SECRETS.exists():
        sys.exit("falta .secrets/oauth_token (gere com `claude setup-token`)")
    env0 = env_base()
    versions = tool_versions(env0)
    done = 0
    for r in plan:
        rd = RUNS / r["run_id"]
        if a.only and r["run_id"] != a.only:
            continue
        if (rd / "result.json").exists() or rd.exists() and not a.only:
            continue
        if a.limit and done >= a.limit:
            break
        spent = CFG.get("budget_already_spent_usd_pilots", 0) + sum(
            (json.loads(f.read_text())["agent"].get("total_cost_usd") or 0) for f in RUNS.glob("*/result.json"))
        if spent + NEXT_RUN_MARGIN_USD > CFG.get("budget_usd_total", 1e9):
            print(f"orçamento: gasto ${spent:.2f} + margem ${NEXT_RUN_MARGIN_USD} > ${CFG['budget_usd_total']}. Parando.")
            break
        t = TASKS[r["task"]]
        ws = rd / "repo"
        no_ancestor_context(ws)
        prep = fresh_checkout(t, ws, r["condition"])
        cfg_dir = rd / "claude-config"
        cfg_dir.mkdir()
        prompt = prompt_for(t)
        (rd / "prompt.txt").write_text(prompt)
        env = dict(env0, CLAUDE_CONFIG_DIR=str(cfg_dir),
                   CLAUDE_CODE_OAUTH_TOKEN=SECRETS.read_text().strip())
        cmd = [CLAUDE_BIN, "-p", prompt, "--model", r["model"], "--output-format", "stream-json",
               "--verbose", "--permission-mode", "bypassPermissions",
               "--disallowedTools", "WebFetch", "WebSearch"]
        print(f"[{time.strftime('%H:%M:%S')}] {r['run_id']} ...", flush=True)
        t0 = time.time()
        with open(rd / "transcript.jsonl", "w") as fo:
            try:
                p = subprocess.run(cmd, cwd=ws, env=env, stdout=fo, stderr=subprocess.PIPE,
                                   text=True, timeout=RUN_TIMEOUT_S)
                exit_code, timed_out, stderr = p.returncode, False, p.stderr
            except subprocess.TimeoutExpired:
                exit_code, timed_out, stderr = None, True, ""
        wall = time.time() - t0
        (rd / "claude.stderr").write_text(stderr or "")
        res_ev = transcript_stats(rd / "transcript.jsonl")
        msg = (res_ev.get("final_message") or "").lower()
        if res_ev.get("api_error_status") in (429, 529) or (res_ev.get("is_error") and "limit" in msg):
            # limite do plano: a execução não conta; descarta para refazer depois do reset
            shutil.rmtree(rd)
            sys.exit(f"limite de uso atingido em {r['run_id']} (descartada). Rode de novo após o reset.")

        patch, dm = diff_metrics(ws, prep, t)
        (rd / "diff.patch").write_text(patch)
        tt0 = time.time()
        tp = sh(t["test_cmd"], cwd=ws, env=env0, timeout=TEST_TIMEOUT_S, check=False)
        (rd / "test.log").write_text(tp.stdout[-20000:] + tp.stderr[-5000:])
        sf = surefire(ws)
        funcs_after = lizard_funcs(ws / t["file"])
        b = base["tasks"][t["id"]]
        base_names = {f["name"] for f in b["funcs"]}
        new_funcs = [f for f in funcs_after if f["name"] not in base_names]
        build_ok = "BUILD SUCCESS" in tp.stdout
        result = {
            **r, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "base_commit": t["commit"], "tool_versions": versions,
            "claude_exit": exit_code, "timed_out": timed_out, "wall_seconds": round(wall),
            "agent": transcript_stats(rd / "transcript.jsonl"),
            "diff": dm,
            "tests": {"exit": tp.returncode, "build_success": build_ok, **sf,
                      "baseline_tests": b["surefire"]["tests"],
                      "seconds": round(time.time() - tt0)},
            "method_before": b["method"], "method_after": method_metrics(funcs_after, t),
            "file_before": b["file"], "file_after": file_summary(funcs_after),
            "new_funcs": new_funcs,
            "valid": build_ok and sf["failures"] == 0 and sf["errors"] == 0
                     and sf["tests"] >= b["surefire"]["tests"] and not dm["test_files_changed"],
        }
        (rd / "result.json").write_text(json.dumps(result, indent=1))
        shutil.rmtree(ws / "target", ignore_errors=True)
        print(f"   valid={result['valid']} tests={sf} cc {b['method']} -> {result['method_after']} "
              f"cost=${result['agent'].get('total_cost_usd')} {round(wall)}s", flush=True)
        done += 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("plan")
    sp.add_parser("baseline")
    rp = sp.add_parser("run")
    rp.add_argument("--limit", type=int)
    rp.add_argument("--only")
    a = ap.parse_args()
    {"plan": cmd_plan, "baseline": cmd_baseline, "run": cmd_run}[a.cmd](a)
