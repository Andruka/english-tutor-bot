#!/bin/bash
# english-tutor-bot — деплой на VDS (tar | ssh pipe)
set -euo pipefail

VDS_HOST="45.134.13.27"
VDS_USER="deploy"
REMOTE_DIR="english-tutor-bot"
SSH_KEY="/opt/data/.ssh/id_ed25519_deploy"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "🚀 Deploy english-tutor-bot → ${VDS_USER}@${VDS_HOST}"

cd "$LOCAL_DIR"

# --- 0. Backup .env на VDS ---
echo "💾 Backing up .env..."
ssh -i "$SSH_KEY" "${VDS_USER}@${VDS_HOST}" "
  if [ -f ${REMOTE_DIR}/.env ]; then
    cp ${REMOTE_DIR}/.env /tmp/${REMOTE_DIR}_env_backup
    echo '✅ .env saved'
  else
    echo '⚠️  No .env to backup'
  fi
"

# --- 1. Transfer files (tar | ssh pipe) ---
echo "📦 Transferring files..."
tar cz \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='data' \
  --exclude='.git' \
  --exclude='*.pyc' \
  -f - . | \
ssh -i "$SSH_KEY" "${VDS_USER}@${VDS_HOST}" "rm -rf ${REMOTE_DIR} && mkdir -p ${REMOTE_DIR} && tar xz -C ${REMOTE_DIR}"

echo "✅ Files transferred."

# --- 1b. Restore .env из backup ---
echo "♻️ Restoring .env..."
ssh -i "$SSH_KEY" "${VDS_USER}@${VDS_HOST}" "
  if [ -f /tmp/${REMOTE_DIR}_env_backup ]; then
    cp /tmp/${REMOTE_DIR}_env_backup ${REMOTE_DIR}/.env
    rm -f /tmp/${REMOTE_DIR}_env_backup
    echo '✅ .env restored'
  else
    echo '⚠️  No backup to restore — create .env from .env.example'
  fi
"

# --- 2. Install dependencies ---
echo "📦 Installing dependencies..."
ssh -i "$SSH_KEY" "${VDS_USER}@${VDS_HOST}" "
  cd ${REMOTE_DIR}
  ~/.local/bin/uv venv --seed 2>/dev/null || true
  source .venv/bin/activate 2>/dev/null || true
  ~/.local/bin/uv pip install -r requirements.txt
"

echo "✅ Dependencies installed."

# --- 3. Env check ---
echo "🔐 Checking .env..."
ENV_LINES=$(ssh -i "$SSH_KEY" "${VDS_USER}@${VDS_HOST}" "wc -l < ${REMOTE_DIR}/.env 2>/dev/null || echo 0")
if [ "$ENV_LINES" -lt 2 ]; then
  echo "⚠️  .env не найден или пуст. Создай из .env.example:"
  echo "   ssh ${VDS_USER}@${VDS_HOST} 'cp ${REMOTE_DIR}/.env.example ${REMOTE_DIR}/.env && nano ${REMOTE_DIR}/.env'"
  exit 1
fi

echo "✅ .env: ${ENV_LINES} строк."

# --- 4. Verify imports ---
echo "🔍 Verifying imports..."
ssh -i "$SSH_KEY" "${VDS_USER}@${VDS_HOST}" "
  cd ${REMOTE_DIR}
  source .venv/bin/activate 2>/dev/null || true
  python -c 'import aiogram; import aiosqlite; import edge_tts; print(\"All imports OK\")'
"

echo "✅ Imports verified."

# --- 5. Restart ---
echo ""
echo "🎉 Deploy complete! Restart the bot:"
echo "   systemctl --user restart english-tutor-bot"
echo ""
echo "Or check logs:"
echo "   journalctl --user -u english-tutor-bot -n 30 --no-pager"
