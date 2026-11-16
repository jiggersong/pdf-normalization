# pdf-normalize —— 项目 Makefile
# 在项目目录直接执行 `make` 即可看到命令使用说明。

# 第一个目标即默认目标：make → help（兼容 BSD make）
SHELL := /usr/bin/env bash
PY ?= python3
BIN := ./pdf-normalize
DEMO_DIR := ./demo-output

.PHONY: help deps test unit smoke install uninstall demo clean docs

help:
	@echo ''
	@echo '  pdf-normalize 1.0.0  —— 把打印乱码的 PDF 规范化成任何打印机都能出的文件'
	@echo ''
	@echo '── 用法 ────────────────────────────────────────────────────────────────'
	@echo '  pdf-normalize <文件或目录> [选项]'
	@echo '  （未装命令时也可以直接跑本目录下的 ./pdf-normalize）'
	@echo ''
	@echo '── 常用示例 ────────────────────────────────────────────────────────────'
	@echo '  pdf-normalize 简历.pdf                         # 默认：矢量轮廓版（推荐）'
	@echo '  pdf-normalize --mode image --dpi 300 简历.pdf  # 图片版（保底）'
	@echo '  pdf-normalize --mode both 简历.pdf             # 两种都出'
	@echo '  pdf-normalize --mode fix 简历.pdf              # 只修字体声明（保留文字）'
	@echo '  pdf-normalize --mode check 简历.pdf            # 只诊断，不写文件'
	@echo '  pdf-normalize -r -o 打印版/ 简历目录/           # 批量递归'
	@echo '  pdf-normalize --doctor                         # 环境自检'
	@echo ''
	@echo '── 模式 ────────────────────────────────────────────────────────────────'
	@echo '  auto     轮廓化，校验不过自动降级成图片（默认）'
	@echo '  outline  文字转矢量轮廓，零字体（推荐）'
	@echo '  image    整页栅格化，零字体（保底）'
	@echo '  fix      只修字体声明，保留可选中文字（兼容性有限）'
	@echo '  both     同时输出 outline + image'
	@echo '  check    只诊断，不写文件'
	@echo ''
	@echo '── make 目标 ────────────────────────────────────────────────────────────'
	@echo '  make help       显示本说明（默认）'
	@echo '  make deps       安装/检查依赖（Ghostscript + poppler）'
	@echo '  make test       单元测试 + 冒烟测试'
	@echo '  make unit       只跑单元测试'
	@echo '  make smoke      只跑冒烟测试'
	@echo '  make demo       生成演示 PDF 并转换到 ./demo-output'
	@echo '  make install    把 pdf-normalize 软链到 PATH'
	@echo '  make uninstall  移除软链'
	@echo '  make clean      清理测试缓存与演示产物'
	@echo '  make docs       列出项目文档'
	@echo ''
	@echo '── 依赖状态 ─────────────────────────────────────────────────────────────'
	@-$(BIN) --doctor 2>/dev/null | tail -n +2 | grep -v '^$$' || true
	@echo ''
	@echo '── 文档 ────────────────────────────────────────────────────────────────'
	@echo '  README.md        项目介绍、安装、用法、FAQ'
	@echo '  docs/USAGE.md    完整使用手册（参数 / 模式 / 批量 / 退出码 / JSON）'
	@echo '  docs/DESIGN.md   方案设计文档（根因分析 / 方案选型 / 架构 / 校验）'
	@echo '  DEPENDENCIES.md  依赖清单与安装说明'
	@echo '  CHANGELOG.md     版本变更记录'
	@echo '  Brewfile         Homebrew 依赖'
	@echo ''

deps:
	@if command -v brew >/dev/null 2>&1; then \
		echo '用项目自带的 Brewfile 检查/安装依赖 ...'; \
		HOMEBREW_NO_AUTO_UPDATE=1 brew bundle --file="$(CURDIR)/Brewfile" || \
		echo 'brew bundle 未成功，请手动执行：brew install ghostscript poppler'; \
	else \
		echo '未找到 Homebrew，请手动安装依赖：'; \
		echo '  macOS : brew install ghostscript poppler'; \
		echo '  Ubuntu: sudo apt-get install -y ghostscript poppler-utils python3'; \
	fi
	@echo
	@$(BIN) --doctor || true

test: unit smoke

unit:
	@$(PY) tests/test_patch.py

smoke:
	@bash tests/smoke.sh

install:
	@bash install.sh

uninstall:
	@for d in /usr/local/bin "$$HOME/.local/bin" "$$HOME/bin"; do \
		if [ -L "$$d/pdf-normalize" ] && [ "$$(readlink "$$d/pdf-normalize")" = "$(CURDIR)/pdf-normalize" ]; then \
			rm -f "$$d/pdf-normalize"; echo "已移除 $$d/pdf-normalize"; \
		fi; \
	done

demo:
	@mkdir -p $(DEMO_DIR)
	@printf '%%!PS\n/Times-Roman findfont 24 scalefont setfont\n72 700 moveto (pdf-normalize demo) show\nshowpage\n' > $(DEMO_DIR)/demo.ps
	@if command -v gs >/dev/null 2>&1; then \
		gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 \
		   -sOutputFile=$(DEMO_DIR)/demo.pdf $(DEMO_DIR)/demo.ps; \
	else echo '缺少 gs，无法生成演示 PDF（先 make deps）'; exit 1; fi
	@$(BIN) -o $(DEMO_DIR) $(DEMO_DIR)/demo.pdf
	@echo; echo '演示产物：$(DEMO_DIR)/demo-print.pdf'

clean:
	@rm -rf $(DEMO_DIR) tests/__pycache__ __pycache__
	@echo '已清理测试缓存与演示产物'

docs:
	@echo 'README.md            项目介绍与用法'
	@echo 'docs/USAGE.md        完整使用手册（参数 / 模式 / 批量 / 退出码 / JSON / FAQ）'
	@echo 'docs/DESIGN.md       方案设计文档（根因分析 / 方案选型 / 架构 / 校验策略）'
	@echo 'DEPENDENCIES.md      依赖清单与安装说明'
	@echo 'CHANGELOG.md         版本变更记录'
	@echo 'LICENSE              MIT 许可证'
	@echo 'Brewfile             Homebrew 依赖（ghostscript + poppler）'
	@echo 'requirements.txt     Python 依赖（空，仅标准库）'
