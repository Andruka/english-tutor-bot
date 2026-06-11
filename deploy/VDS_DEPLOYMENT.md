# Controlled VDS deployment

This project deploys a previously built archive with the `Deploy archive to VDS` GitHub Actions workflow.

## Required GitHub environment configuration

Create GitHub environments named `staging` and `production`. Add these environment secrets to each environment:

- `VDS_HOST` — server hostname or IP.
- `VDS_USER` — SSH user, usually `deploy`.
- `VDS_SSH_KEY` — private SSH key allowed to SSH to the VDS.

Optional environment variables:

- `VDS_PORT` — SSH port, defaults to `22`.
- `DEPLOY_DIR` — base deploy directory, defaults to `/home/deploy/english-tutor-bot`.
- `SERVICE_NAME` — systemd service name, defaults to `english-tutor-bot`.
- `KEEP_RELEASES` — number of release directories to keep, defaults to `5`.

## One-time VDS preparation

```bash
sudo useradd -m -s /bin/bash deploy || true
sudo mkdir -p /home/deploy/english-tutor-bot/shared/data
sudo chown -R deploy:deploy /home/deploy/english-tutor-bot
sudo -u deploy cp /path/to/.env.example /home/deploy/english-tutor-bot/shared/.env
sudo -u deploy nano /home/deploy/english-tutor-bot/shared/.env
sudo cp deploy/english-tutor-bot.service /etc/systemd/system/english-tutor-bot.service
sudo systemctl daemon-reload
sudo systemctl enable english-tutor-bot
```

The service intentionally points to `/home/deploy/english-tutor-bot/current`. The deployment script atomically moves that symlink during deploy and rollback.

## Deploy

1. Run `Build deployable archive` for the commit/tag to deploy.
2. Copy the workflow run ID from that build.
3. Run `Deploy archive to VDS` manually:
   - `environment`: `staging` or `production`.
   - `operation`: `deploy`.
   - `archive_run_id`: the build workflow run ID.
   - `archive_name`: optional; leave empty when the build run produced exactly one `.tar.gz` archive.
   - `dry_run`: `true` first to verify SSH and server layout without changing `current`; then `false`.

The workflow downloads the archive artifact, validates it, copies it to `${DEPLOY_DIR}/incoming`, uploads `deploy/vds-release.sh`, installs dependencies in a new release directory, runs import health checks, switches `current`, restarts the service, and shows systemd status.

## Rollback

Run `Deploy archive to VDS` manually with:

- `environment`: the environment to roll back.
- `operation`: `rollback`.
- `dry_run`: `true` to preview, then `false`.

Rollback reads `${DEPLOY_DIR}/previous-release`, verifies imports in that release, switches `current` back atomically, and restarts the service. If rollback restart fails, the script restores the release that was current before the rollback attempt.

## Server layout

```text
/home/deploy/english-tutor-bot/
  current -> releases/<active-release-id>
  previous-release
  incoming/
  ops/vds-release.sh
  releases/
    <release-id>/
  shared/
    .env
    data/
```

Secrets and mutable data live under `shared/`; release directories are immutable and disposable.
