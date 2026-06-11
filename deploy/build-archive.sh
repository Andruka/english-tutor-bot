#!/bin/bash
# build-archive.sh — собрать чистый архив для деплоя
set -euo pipefail

VERSION="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"
ARCHIVE_NAME="english-tutor-bot-${VERSION}.tar.gz"
ARCHIVE_PATH="/tmp/export/${ARCHIVE_NAME}"

echo "📦 Building ${ARCHIVE_NAME}..."

mkdir -p /tmp/export

cd "$(dirname "$0")/.."

# Упаковываем только нужные для деплоя файлы
tar czf "${ARCHIVE_PATH}" \
  --exclude='.git' \
  --exclude='.github' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='.env' \
  --exclude='data' \
  --exclude='htmlcov' \
  --exclude='.coverage' \
  --exclude='coverage.xml' \
  --exclude='*.egg-info' \
  --exclude='.DS_Store' \
  --exclude='Thumbs.db' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='_tmp_db_inspect.py' \
  --exclude='english_tutor.db' \
  --exclude='plans' \
  --exclude='research' \
  --exclude='tests' \
  --exclude='pytest.ini' \
  .

echo "✅ ${ARCHIVE_PATH} ($(du -h "${ARCHIVE_PATH}" | cut -f1))"

# Проверка
echo "🔍 Verifying..."
TMP_DIR=$(mktemp -d)
tar xzf "${ARCHIVE_PATH}" -C "${TMP_DIR}"

echo "=== Key files ==="
test -f "${TMP_DIR}/requirements.txt" && echo "  ✅ requirements.txt"
test -d "${TMP_DIR}/bot" && echo "  ✅ bot/"
test -d "${TMP_DIR}/deploy" && echo "  ✅ deploy/"
test -f "${TMP_DIR}/bot/main.py" && echo "  ✅ bot/main.py"
test -f "${TMP_DIR}/deploy/vds-release.sh" && echo "  ✅ vds-release.sh"
test -f "${TMP_DIR}/deploy/english-tutor-bot.service" && grep -q '/current' "${TMP_DIR}/deploy/english-tutor-bot.service" && echo "  ✅ service uses current symlink"

echo "=== No dev artifacts ==="
! test -f "${TMP_DIR}/_tmp_db_inspect.py" && echo "  ✅ _tmp_db_inspect.py excluded"
! test -f "${TMP_DIR}/english_tutor.db" && echo "  ✅ english_tutor.db excluded"
! test -d "${TMP_DIR}/plans" && echo "  ✅ plans/ excluded"
! test -d "${TMP_DIR}/tests" && echo "  ✅ tests/ excluded"

rm -rf "${TMP_DIR}"
echo "✅ Archive verified"