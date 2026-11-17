#!/usr/bin/env bash
# Gera um token de assinatura com `claude setup-token` e grava direto em .secrets/oauth_token.
# O token é capturado da saída do terminal; o log temporário é apagado em seguida.
cd "$(dirname "$0")/.." || exit 1
umask 077
mkdir -p .secrets
CLAUDE_BIN=claude
LOG=$(mktemp)
trap 'shred -u "$LOG" 2>/dev/null || rm -f "$LOG"' EXIT
script -q -c "$CLAUDE_BIN setup-token" "$LOG"
python3 - "$LOG" <<'PY'
import re, sys
raw = open(sys.argv[1], "rb").read().decode("utf-8", "replace")
text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Z0-9]|\r", "", raw)
i = text.rfind("sk-ant-oat01-")
if i < 0:
    sys.exit("\nNão encontrei o token na saída. Rode de novo: bash experiment/new_token.sh")
lines = text[i:].split("\n")
tok = re.match(r"[A-Za-z0-9_-]+", lines[0]).group(0)
for ln in lines[1:]:
    ln = ln.strip()
    if not ln or not re.fullmatch(r"[A-Za-z0-9_-]+", ln):
        break
    tok += ln
if len(tok) < 90:
    sys.exit(f"\nToken capturado parece incompleto ({len(tok)} caracteres). Rode de novo.")
open(".secrets/oauth_token", "w").write(tok)
print(f"\nToken salvo em .secrets/oauth_token ({len(tok)} caracteres). Pode fechar esta aba.")
PY
