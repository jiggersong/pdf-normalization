#!/usr/bin/env bash
# 端到端冒烟测试：用 Ghostscript 现造一个 PDF，跑遍所有模式并检查产物。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$HERE/pdf-normalize"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
bad()  { printf '  ✗ %s\n' "$*"; FAIL=1; }
need() { command -v "$1" >/dev/null 2>&1 || { say "缺少 $1，跳过冒烟测试"; exit 77; }; }
need gs; need pdftocairo; need pdffonts; need pdfinfo

say "生成样本 PDF ..."
cat > "$TMP/sample.ps" <<'PS'
%!PS
/Times-Roman findfont 24 scalefont setfont
72 700 moveto (pdf-normalize smoke test) show
/Times-Bold findfont 18 scalefont setfont
72 660 moveto (print-safe output) show
showpage
PS
gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -sOutputFile="$TMP/in.pdf" "$TMP/sample.ps" || { bad "样本生成失败"; exit 1; }
ok "样本: $TMP/in.pdf ($(wc -c < "$TMP/in.pdf" | tr -d ' ') bytes)"

say "--version"; "$BIN" --version >/dev/null && ok "--version" || bad "--version"

say "--doctor"; "$BIN" --doctor >/dev/null && ok "--doctor" || bad "--doctor"

say "--mode check（不应产生文件）"
"$BIN" --mode check "$TMP/in.pdf" >/dev/null || bad "check 退出码非 0"
[ -z "$(ls -A "$TMP" | grep -v in.pdf | grep -v sample.ps)" ] && ok "check 未写文件" || bad "check 产生了多余文件"

say "--mode outline"
"$BIN" --mode outline -o "$TMP/o" "$TMP/in.pdf" >/dev/null || bad "outline 失败"
if [ -f "$TMP/o/in-print.pdf" ]; then
  n=$(pdffonts "$TMP/o/in-print.pdf" 2>/dev/null | tail -n +3 | grep -c . || true)
  [ "$n" = "0" ] && ok "outline 产物零字体" || bad "outline 产物仍有 $n 个字体"
else bad "outline 没有产物"; fi

say "--mode image -d 150"
"$BIN" --mode image -d 150 -o "$TMP/o" "$TMP/in.pdf" >/dev/null || bad "image 失败"
[ -f "$TMP/o/in-print-150dpi.pdf" ] && ok "image 产物存在" || bad "image 没有产物"

say "--mode both"
"$BIN" --mode both -o "$TMP/b" "$TMP/in.pdf" >/dev/null || bad "both 失败"
[ -f "$TMP/b/in-print.pdf" ] && [ -f "$TMP/b/in-print-300dpi.pdf" ] && ok "both 两个产物都在" || bad "both 产物缺失"

say "--mode fix（无错配应友好返回 0）"
"$BIN" --mode fix -o "$TMP/f" "$TMP/in.pdf" >/dev/null && ok "fix 无错配返回 0" || bad "fix 无错配时非 0"

say "--json"
"$BIN" --json -o "$TMP/j" "$TMP/in.pdf" 2>/dev/null | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["summary"]["failed"]==0, d["summary"]
assert len(d["results"])==1
' && ok "json 输出合法且无失败" || bad "json 输出异常"

say "--no-verify（快速模式）"
"$BIN" --mode outline --no-verify -o "$TMP/nv" "$TMP/in.pdf" >/dev/null && ok "--no-verify" || bad "--no-verify 失败"

if [ "$FAIL" = "0" ]; then say "冒烟测试通过"; else say "冒烟测试有失败项"; fi
exit "$FAIL"
