#!/usr/bin/env bash
# vds-release.sh — controlled archive deployment and rollback on the VDS.
set -euo pipefail

OPERATION="${OPERATION:-deploy}"
RELEASE_ID="${RELEASE_ID:-}"
ARCHIVE_PATH="${ARCHIVE_PATH:-}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/deploy/english-tutor-bot}"
SERVICE_NAME="${SERVICE_NAME:-english-tutor-bot}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
DRY_RUN="${DRY_RUN:-false}"

log() { printf '==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_safe_name() {
  local value="$1"
  [[ "$value" =~ ^[A-Za-z0-9._-]+$ ]] || fail "unsafe release id: ${value}"
}

run_service() {
  local action="$1"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user status "$SERVICE_NAME" >/dev/null 2>&1; then
    systemctl --user "$action" "$SERVICE_NAME"
  elif command -v sudo >/dev/null 2>&1; then
    sudo systemctl "$action" "$SERVICE_NAME"
  else
    systemctl "$action" "$SERVICE_NAME"
  fi
}

service_status() {
  if command -v systemctl >/dev/null 2>&1 && systemctl --user status "$SERVICE_NAME" >/dev/null 2>&1; then
    systemctl --user --no-pager status "$SERVICE_NAME"
  elif command -v sudo >/dev/null 2>&1; then
    sudo systemctl --no-pager status "$SERVICE_NAME"
  else
    systemctl --no-pager status "$SERVICE_NAME"
  fi
}

health_check() {
  local release_dir="$1"
  cd "$release_dir"
  if [ ! -x .venv/bin/python ]; then
    fail "missing virtualenv python in ${release_dir}"
  fi
  .venv/bin/python - <<'PY'
import importlib
for module in ("aiogram", "aiosqlite", "edge_tts", "bot.main"):
    importlib.import_module(module)
print("imports OK")
PY
}

prepare_common_dirs() {
  mkdir -p "$DEPLOY_DIR/releases" "$DEPLOY_DIR/shared" "$DEPLOY_DIR/incoming" "$DEPLOY_DIR/ops"
  if [ ! -f "$DEPLOY_DIR/shared/.env" ]; then
    fail "missing ${DEPLOY_DIR}/shared/.env; create it from .env.example before deploying"
  fi
  mkdir -p "$DEPLOY_DIR/shared/data"
}

install_dependencies() {
  local release_dir="$1"
  cd "$release_dir"
  if command -v uv >/dev/null 2>&1; then
    uv venv --seed
    uv pip install -r requirements.txt
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
  else
    fail "neither uv nor python3 is available on the VDS"
  fi
}

atomic_switch() {
  local target="$1"
  ln -sfn "$target" "$DEPLOY_DIR/current.next"
  mv -Tf "$DEPLOY_DIR/current.next" "$DEPLOY_DIR/current"
}

cleanup_old_releases() {
  find "$DEPLOY_DIR/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr \
    | awk -v keep="$KEEP_RELEASES" 'NR > keep {print $2}' \
    | xargs -r rm -rf
}

deploy_release() {
  [ -n "$RELEASE_ID" ] || fail "RELEASE_ID is required for deploy"
  require_safe_name "$RELEASE_ID"
  [ -n "$ARCHIVE_PATH" ] || fail "ARCHIVE_PATH is required for deploy"
  [ -f "$ARCHIVE_PATH" ] || fail "archive not found: ${ARCHIVE_PATH}"
  tar tzf "$ARCHIVE_PATH" >/dev/null

  prepare_common_dirs
  local release_dir="$DEPLOY_DIR/releases/$RELEASE_ID"
  [ ! -e "$release_dir" ] || fail "release already exists: ${release_dir}"

  if [ "$DRY_RUN" = "true" ]; then
    log "dry run: archive, shared env, and target paths are valid"
    return 0
  fi

  log "extracting ${ARCHIVE_PATH} to ${release_dir}"
  local extract_tmp
  extract_tmp="$(mktemp -d)"
  tar xzf "$ARCHIVE_PATH" -C "$extract_tmp"
  mkdir -p "$release_dir"
  if [ -d "$extract_tmp/english-tutor-bot" ]; then
    cp -a "$extract_tmp/english-tutor-bot/." "$release_dir/"
  else
    cp -a "$extract_tmp/." "$release_dir/"
  fi
  rm -rf "$extract_tmp"

  ln -sfn "$DEPLOY_DIR/shared/.env" "$release_dir/.env"
  rm -rf "$release_dir/data"
  ln -sfn "$DEPLOY_DIR/shared/data" "$release_dir/data"

  log "installing dependencies"
  install_dependencies "$release_dir"

  log "running health check"
  health_check "$release_dir"

  local previous=""
  if [ -L "$DEPLOY_DIR/current" ]; then
    previous="$(readlink -f "$DEPLOY_DIR/current")"
    printf '%s\n' "$previous" > "$DEPLOY_DIR/previous-release"
  fi

  log "switching current release"
  atomic_switch "$release_dir"

  log "restarting ${SERVICE_NAME}"
  run_service restart
  service_status || {
    if [ -n "$previous" ] && [ -d "$previous" ]; then
      log "restart failed; restoring previous release ${previous}"
      atomic_switch "$previous"
      run_service restart || true
    fi
    fail "service failed after deploy"
  }

  cleanup_old_releases
  rm -f "$ARCHIVE_PATH"
  log "deployed ${RELEASE_ID}"
}

rollback_release() {
  prepare_common_dirs
  [ -L "$DEPLOY_DIR/current" ] || fail "current release symlink is missing"
  [ -f "$DEPLOY_DIR/previous-release" ] || fail "previous-release marker is missing"
  local previous
  previous="$(cat "$DEPLOY_DIR/previous-release")"
  [ -d "$previous" ] || fail "previous release directory does not exist: ${previous}"

  if [ "$DRY_RUN" = "true" ]; then
    log "dry run: would roll back to ${previous}"
    return 0
  fi

  local current
  current="$(readlink -f "$DEPLOY_DIR/current")"
  printf '%s\n' "$current" > "$DEPLOY_DIR/rollback-from-release"

  log "rolling back to ${previous}"
  health_check "$previous"
  atomic_switch "$previous"
  run_service restart
  service_status || {
    log "rollback restart failed; restoring ${current}"
    atomic_switch "$current"
    run_service restart || true
    fail "service failed after rollback"
  }
  log "rollback complete"
}

case "$OPERATION" in
  deploy) deploy_release ;;
  rollback) rollback_release ;;
  *) fail "unsupported OPERATION: ${OPERATION}" ;;
esac
