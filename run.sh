#!/usr/bin/env bash
# 一键启动：首次运行会自动创建 .venv 并安装依赖
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "首次运行，正在创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python -m streamlit run app.py "$@"
