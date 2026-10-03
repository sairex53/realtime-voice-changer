#!/bin/zsh
cd "$(dirname "$0")" || exit 1

PYTHON_BIN="${PYTHON_BIN:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 не найден."
  read -r "?Нажми Enter для закрытия..."
  exit 1
fi

"$PYTHON_BIN" voice_changer.py "$@"
code=$?

echo
echo "Готово. Можно закрыть окно."
read -r "?Нажми Enter для закрытия..."
exit "$code"
