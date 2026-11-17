#!/usr/bin/env bash
# Salva o token do `claude setup-token` em .secrets/oauth_token sem exibi-lo.
# Aceita o token colado em 1 ou 2 linhas; termine com Enter e Ctrl-D.
cd "$(dirname "$0")/.." || exit 1
umask 077
mkdir -p .secrets
while true; do
  echo "Cole o token que COMEÇA com sk-ant-oat01- (as duas linhas), tecle Enter e depois Ctrl-D:"
  stty -echo
  T=$(tr -d '[:space:]')
  stty echo
  echo
  if [[ "$T" == sk-ant-oat01-* && ${#T} -ge 90 ]]; then
    printf '%s' "$T" > .secrets/oauth_token
    echo "Token salvo (${#T} caracteres)."
    break
  fi
  echo "Isso não parece o token (precisa começar com sk-ant-oat01-; recebi ${#T} caracteres). Tente de novo."
done
