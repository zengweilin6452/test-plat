#!/usr/bin/env bash
# vendor 两个能力包的回归测试（unit + contract）。
#
# 两种模式：
#   installed （默认，宿主/CI）: vendor 已 pip install -e，pytest 走正常入口
#   pathonly  （DSH 沙箱兜底）: 不安装，PYTHONPATH 指向 vendor/*/src
#
# 为什么要 pathonly：DSH 沙箱禁止 pip 的临时文件（mode 0600/0700，WinError 13/5），
# 且 pytest mkdir(mode=0o700) 建的 tmp 目录在沙箱内不可访问。
# 宿主/CI 无此问题，因此 P0 验收必须在宿主或 CI 执行（development-plan.md §12.1）。
#
# 用法:
#   bash scripts/run_vendor_tests.sh              # installed 模式，两个包
#   bash scripts/run_vendor_tests.sh pathonly     # PYTHONPATH 模式，两个包
#   MOBILE_PKG=auto bash scripts/run_vendor_tests.sh   # 只跑一个
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"
MODE="${1:-installed}"
SCOPE="${MOBILE_PKG:-all}"

# PYTHONPATH 分隔符必须跟解释器的 os.pathsep 走：Windows 原生 Python（含 Git
# Bash 下调用的 python.exe）按 ';' 切分，':' 会把两段路径并成一个失效条目
# （2026-11-14 实测：sys.path 里出现整串合并路径，tests 包解析失败）。
PY_SEP="$("$PYTHON" -c "import os; print(os.pathsep)")"

# MSYS/Git Bash 只自动转换命令行参数（如 --basetemp），不转换 PYTHONPATH 这类
# 自定义环境变量；pwd 产出的 /d/... 形式 Windows Python 无法解析（同样是
# 2026-11-14 实测的 'No module named tests' 来源），须显式转成 Windows 形式。
if command -v cygpath >/dev/null 2>&1; then
  PY_ROOT="$(cygpath -m "$REPO_ROOT")"
else
  PY_ROOT="$REPO_ROOT"
fi

if [ "$MODE" = "pathonly" ]; then
  export PYTHONPATH="$PY_ROOT/vendor/mobile_auto/src${PY_SEP}$PY_ROOT/vendor/mobile_perf/src${PYTHONPATH:+${PY_SEP}${PYTHONPATH}}"
fi

# 包根也进 PYTHONPATH：mobile_perf 新测试跨模块导入 tests.unit.test_kit，
# 需要能以 tests 包解析 vendor/<pkg>/tests（与源仓库在其根目录跑 pytest 同构）。
export PYTHONPATH="$PY_ROOT/vendor/mobile_auto${PY_SEP}$PY_ROOT/vendor/mobile_perf${PYTHONPATH:+${PY_SEP}${PYTHONPATH}}"

# 临时目录收进仓库内（F17）；宿主上也可安全使用
RUNTIME="$REPO_ROOT/.runtime"
export TMP="$RUNTIME/tmp"
export TEMP="$TMP"
export TMPDIR="$TMP"
mkdir -p "$TMP"

echo "== vendor 只读校验 =="
"$PYTHON" scripts/vendor_sync.py check

run_pkg() {
  local pkg="$1"
  local dir="$REPO_ROOT/vendor/$pkg"
  echo
  echo "== $pkg: unit + contract  (mode=$MODE) =="
  "$PYTHON" -m pytest "$dir/tests/unit" "$dir/tests/contract" \
    -q -p no:cacheprovider --basetemp="$RUNTIME/pytest-$pkg"
}

if [ "$SCOPE" = "auto" ] || [ "$SCOPE" = "all" ]; then
  run_pkg mobile_auto
fi
if [ "$SCOPE" = "perf" ] || [ "$SCOPE" = "all" ]; then
  run_pkg mobile_perf
fi

echo
echo "== 完成: $SCOPE ($MODE) =="
