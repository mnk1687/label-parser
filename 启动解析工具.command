#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  runner=.venv/bin/python
elif [[ -x ../../.venv/bin/python ]]; then
  runner=../../.venv/bin/python
else
  echo '首次启动：准备本地 Python 环境…'
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
  runner=.venv/bin/python
fi
"$runner" -m label_parser --gui
