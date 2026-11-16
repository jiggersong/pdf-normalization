#!/usr/bin/env bash
# 把 pdf-normalize 安装成全局命令（软链，不复制）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/pdf-normalize"

if [ ! -f "$BIN" ]; then
  echo "找不到 $BIN" >&2
  exit 1
fi
chmod +x "$BIN"

# 依次尝试：/usr/local/bin -> ~/.local/bin -> ~/bin
for DIR in /usr/local/bin "$HOME/.local/bin" "$HOME/bin"; do
  if mkdir -p "$DIR" 2>/dev/null && [ -w "$DIR" ]; then
    LINK="$DIR/pdf-normalize"
    if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
      ln -sfn "$BIN" "$LINK"
      echo "已安装: $LINK -> $BIN"
      case ":$PATH:" in
        *":$DIR:"*) ;;
        *) echo "提示: $DIR 不在 PATH 中，请把下面一行加到 ~/.zshrc："
           echo "      export PATH=\"$DIR:\$PATH\"" ;;
      esac
      echo
      echo "自检： pdf-normalize --doctor"
      exit 0
    else
      echo "跳过 $LINK（已存在且不是软链，不覆盖）" >&2
    fi
  fi
done

echo "没有可写的 PATH 目录，直接使用仓库内的：$BIN" >&2
exit 1
