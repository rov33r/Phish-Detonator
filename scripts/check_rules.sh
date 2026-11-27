#!/usr/bin/env bash
# Enforces the CLAUDE.md rules that a grep can check. Run locally before opening a PR.
set -u
fail=0
code_dirs=$(ls -d app sandbox fixtures deploy 2>/dev/null)

check() { # check <description> <matches>
  if [ -n "$2" ]; then echo "FAIL: $1"; echo "$2" | sed 's/^/  /'; fail=1; else echo "ok:   $1"; fi
}

if [ -n "$code_dirs" ]; then
  check "only Vultr Serverless Inference as LLM endpoint (rule 3)" \
    "$(grep -rnIiE 'api\.openai\.com|api\.anthropic\.com|generativelanguage|api\.groq\.com|api\.mistral\.ai|api\.together|openrouter\.ai|api\.cohere' $code_dirs)"
  check "no shell=True (rule 4)" "$(grep -rnI 'shell=True' $code_dirs)"
  check "no os.system / os.popen (rule 4)" "$(grep -rnIE 'os\.(system|popen)\(' $code_dirs)"
fi
check "no .env files committed (rule 6)" "$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$')"
check "no em dashes in docs (rule 8)" "$(grep -rnI '—' README.md CLAUDE.md docs 2>/dev/null)"

exit $fail
