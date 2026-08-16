# EC2 Deployment Instructions — Alpaca Trading System

Instructions only — nothing in this document has been executed. Every command is tagged `[LOCAL]`, `[EC2]`, or `[AWS CONSOLE]`.

---

## 1. Pre-Deployment Review

What the repository actually contains, relevant to deployment:

- **Not a daemon.** `trader-bot` is a Docker Compose service (`compose.yaml`, single `trader-bot` service, no `ibeam` sidecar anymore) built from `trader-bot/Dockerfile` (`python:3.11-slim`, `ENTRYPOINT ["python", "execute-trade.py"]`). `docker compose run --rm trader-bot` runs it **once and exits** — there is no long-running process to keep alive. This matters for the "startup on reboot" section: there's no container to restart, only the *scheduler* (cron) needs to survive a reboot.
- **Config surfaces:**
  - `trader-bot/.env` — Alpaca API key/secret pairs. Not tracked in git (`.gitignore` covers `.env`), loaded into the container via `env_file:` in `compose.yaml`. Must be created manually on EC2.
  - `trader-bot/accounts.yaml` — multi-account/ticker-allocation config, **is** tracked in git (contains no secrets, only env-var *names*). Currently defines one enabled account, `roth-ira`, `paper: true`, allocations `VTI 20 / VOO 20 / VUG 30 / VGT 15 / QQQ 15`. Two more accounts (`taxable-leveraged-etf`, `taxable-index-etf`) exist in the file but are commented out.
  - `trader-bot/algo_trader/utils/config.py` — non-account settings: AWS region (`us-east-1` throughout), S3 bucket base name, CloudWatch log group base name, SES `EMAIL_FROM`/`EMAIL_TO`, Telegram chat ID, Secrets Manager secret name (`SignalSingaravelanSecrets`, key `TelegramBotToken`), and retry tuning.
  - ⚠️ `MASSIVE_API_KEY` in `config.py` is a **plaintext secret checked into git**. Not part of the Alpaca migration's scope, but this is the natural moment to fix it — see the note in §2.
- **AWS resources the app touches** (all auto-created on first use if missing, via `boto3`):
  - S3: `signal-singaravelan-market-data` (shared QQQ price cache, used by `strategy.py`), and `signal-singaravelan-<account-name>` per **enabled** account in `accounts.yaml` (trade-history Excel log) — currently just `signal-singaravelan-roth-ira`.
  - CloudWatch Logs: log group `signal-singaravelan-<account-name>`.
  - SES: email notifications from `EMAIL_FROM` to `EMAIL_TO`.
  - Secrets Manager: `SignalSingaravelanSecrets` for the Telegram bot token.
- **Nothing to reuse for scheduling/startup** — no systemd units, cron files, or startup scripts exist in the repo. README only shows an *example* cron line for local reference. Sections 10–11 below build this from scratch.
- **No CI, no tests run automatically** — `trader-bot/tests/` exists and passes locally (per your testing), but nothing wires it into deployment; that's expected for a project this size.

---

## 2. GitHub Commit and Push

**[LOCAL]**
```bash
cd "signal-singaravelan"
git status
```
Confirm the output matches what you expect (modified/deleted IBKR files, new Alpaca files) and that no unexpected files appear — in particular, confirm `trader-bot/.env` does **not** show up (if it does, it means `.gitignore` isn't catching it — stop and fix that before committing).

Review `.gitignore` — it already covers `.env`, `.env.local/.production/.staging`, `*.pem`, `*.key`, `.aws/`. No additions are required for this deployment; `accounts.yaml` is intentionally *not* ignored since it holds no secrets.

Optional but recommended before committing: fix the plaintext `MASSIVE_API_KEY` in `trader-bot/algo_trader/utils/config.py` (move it to an env var or Secrets Manager, matching how the Telegram token is already handled) — you're about to make this code "production," which is the right time. Not required to proceed; flagging so it's a conscious choice, not an oversight. Let me know if you'd like me to make that change as a separate follow-up before you commit.

```bash
git add README.md compose.yaml trader-bot/ ibeam/
git status   # review staged files one more time before committing
git commit -m "Migrate trading system from Interactive Brokers to Alpaca"
git push origin main
```

Verify the push landed:
```bash
git log --oneline -1
git ls-remote origin main
```
The commit hash from `git log` should match the hash `git ls-remote` reports for `refs/heads/main`. **Record this commit hash** — it's what you'll `git checkout` on EC2 in §6, so the deployed code is exactly what you tested locally, not whatever `main` happens to be later.

**Do not push:** `trader-bot/.env` (never generated locally in a way git would see it, per `.gitignore`), any `.venv`/`__pycache__` directories, or the `.docs/` requirements docs if you'd rather keep deployment planning private — nothing sensitive lives in them, so it's your call.

---

## 3. Old IBKR EC2 Transition

If an existing EC2 instance is currently running the IBKR-based bot on a schedule, it must stop trading **before** the new instance's schedule goes live — otherwise you risk two systems trading the same accounts on the same day.

**[AWS CONSOLE]** EC2 → Instances → identify the old instance (by name tag or by which one has `ibeam`/the old repo checked out).

**[EC2 — OLD INSTANCE]**
```bash
crontab -l                 # confirm what's currently scheduled
crontab -e                 # comment out or delete the trading cron line
docker compose down        # stop the ibeam + trader-bot containers if running
```

Recommendation: **stop, don't terminate** the old instance once its cron job is disabled:

**[AWS CONSOLE]** EC2 → Instances → select the old instance → Instance state → **Stop**.

Keep it stopped for a week or two as a rollback option while you confirm the new Alpaca instance runs cleanly. A stopped instance costs nothing for compute (only its EBS volume, a few cents/month). Terminate it once you're confident:

**[AWS CONSOLE]** EC2 → Instances → select the old instance → Instance state → **Terminate** (only after the new instance has proven itself — see §16).

---

## 4. New EC2 Creation

### A. Recommended configuration

| Setting | Recommendation | Why |
|---|---|---|
| Region | `us-east-1` | Matches every hardcoded AWS region in `config.py` (S3, CloudWatch, SES, Secrets Manager) — avoids cross-region latency/egress. |
| AMI | Amazon Linux 2023 | Free, minimal, well-supported `dnf`/Docker/`cronie` packages, IMDSv2 by default. |
| Instance type | `t3.micro` (1 vCPU, 1 GiB) | The app runs once a day for seconds-to-low-minutes and is network-bound, not compute-bound. `t3.micro` is free-tier eligible (if your account still has free tier) and comfortably sized; `t3.small` is a safe fallback if you ever see memory pressure, but shouldn't be needed. |
| Storage | 10 GiB gp3 | Covers OS + Docker image + rotated logs with headroom. |
| Security group | Inbound: SSH (22) restricted to **your IP /32** only. Outbound: default (allow all). | The app makes outbound calls only (Alpaca, AWS, Massive.com, Telegram) — nothing needs to be reachable from the internet. |
| Key pair | Create or reuse an EC2 key pair | For SSH access. |
| IAM role | Dedicated instance role (§7) | Avoids storing AWS access keys on the instance entirely. |
| Public IP | Yes (default public subnet) | Needed for outbound internet + your SSH access. A private-subnet + NAT gateway setup is more "correct" but adds real monthly cost and complexity for one small instance — not worth it here given your "keep it simple/cheap" priority. |
| Elastic IP | Not needed | No inbound service depends on a stable address, and Alpaca's standard API doesn't require an allow-listed egress IP. Skip unless you specifically want a fixed address for your own SSH convenience. |

**⚠️ Critical, easy-to-miss setting:** under **Advanced details → Metadata version**, set **"Metadata hop limit" to 2** (default is 1). Boto3 inside the Docker container fetches IAM role credentials via the EC2 Instance Metadata Service (IMDSv2); the container adds one extra network hop beyond the host, and IMDSv2's default hop limit of 1 will silently make every AWS call from inside the container fail with a credentials error even though the role is correctly attached. This is the single most likely "it works on the host but not in the container" surprise — set the hop limit to 2 at launch.

### B. Launch and initial setup

**[AWS CONSOLE]** EC2 → Launch Instance, using the settings above. Under Advanced details, set Metadata version to "V2 (token required)" and Metadata hop limit to **2**. Attach the IAM role from §7 (or attach it after creation via Actions → Security → Modify IAM role).

**[LOCAL]**
```bash
chmod 400 /path/to/your-key.pem
ssh -i /path/to/your-key.pem ec2-user@<new-instance-public-ip>
```

**[EC2]**
```bash
sudo dnf update -y
sudo dnf install -y git docker cronie unzip
sudo systemctl enable --now docker
sudo systemctl enable --now crond
sudo usermod -aG docker ec2-user
```
Log out and back in (or run `newgrp docker`) so the `docker` group membership takes effect without needing `sudo` for every Docker command:
```bash
exit
```
**[LOCAL]** `ssh -i /path/to/your-key.pem ec2-user@<new-instance-public-ip>` (reconnect)

**[EC2]** Install the Docker Compose v2 plugin (the repo's `compose.yaml` — note: no hyphen — is the Compose v2 default filename; use `docker compose`, space-separated, not the older hyphenated `docker-compose`):
```bash
sudo dnf install -y docker-compose-plugin
docker compose version   # confirm it works
```
If that package isn't available in your AL2023 repo mirror, install the plugin binary directly instead:
```bash
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
docker compose version
```

---

## 5. EC2 Software Installation

Covered above in §4B (git, docker, cronie, docker-compose-plugin, unzip). Nothing else is required — all Python dependencies (`pandas`, `boto3`, `alpaca-py`, `matplotlib`, etc.) are installed **inside** the Docker image by `Dockerfile`'s `pip install -r requirements.txt`, not on the host. There's no need to install Python or any pip packages directly on the EC2 instance itself.

---

## 6. Repository Deployment

**[EC2]** Generate a dedicated, read-only deploy key for this instance rather than using a personal GitHub token:
```bash
ssh-keygen -t ed25519 -C "ec2-trader-bot-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```
**[AWS CONSOLE — actually GitHub]** GitHub repo → Settings → Deploy keys → Add deploy key → paste the public key → leave "Allow write access" **unchecked** (read-only is all this instance needs).

**[EC2]**
```bash
ssh -T git@github.com   # first-time host key confirmation
git clone git@github.com:signalsingaravelan/signal-singaravelan.git
cd signal-singaravelan
git checkout <exact-commit-hash-from-§2>
git log --oneline -1     # confirm it matches
```

---

## 7. AWS/S3 Configuration

**[AWS CONSOLE]** Pre-create the S3 buckets (region `us-east-1`, Block Public Access left **on**) so the IAM policy doesn't need account-wide bucket-creation rights beyond this app's naming prefix:
- `signal-singaravelan-market-data`
- `signal-singaravelan-roth-ira`

(Add more `signal-singaravelan-<account-name>` buckets later if you enable additional accounts in `accounts.yaml` — the app will also auto-create them at runtime if the IAM policy below permits it, so pre-creating is a convenience/predictability step, not strictly required.)

**[AWS CONSOLE]** IAM → Policies → Create policy (JSON), scoped to this app's resources only:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:CreateBucket", "s3:HeadBucket"],
      "Resource": [
        "arn:aws:s3:::signal-singaravelan*",
        "arn:aws:s3:::signal-singaravelan*/*"
      ]
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
      "Resource": "arn:aws:logs:us-east-1:<YOUR_AWS_ACCOUNT_ID>:log-group:signal-singaravelan*:*"
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManager",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:<YOUR_AWS_ACCOUNT_ID>:secret:SignalSingaravelanSecrets-*"
    }
  ]
}
```
Replace `<YOUR_AWS_ACCOUNT_ID>` with your actual account ID (SES doesn't support per-identity resource scoping cleanly for `SendEmail`, hence `Resource: "*"` there — the action itself is still limited to sending, nothing else).

**[AWS CONSOLE]** IAM → Roles → Create role → Trusted entity: **AWS service → EC2** → attach the policy above → name it (e.g. `signal-singaravelan-trader-bot-role`) → Create. Attach it to the EC2 instance (Actions → Security → Modify IAM role, if not done at launch).

**[AWS CONSOLE]** Confirm prerequisites that already exist from the IBKR-era deployment still work for the new instance:
- SES: `EMAIL_FROM` (`signalsingaravelan@gmail.com`) is a **verified identity** in SES, region `us-east-1`. If your SES account is still in the sandbox, `EMAIL_TO` must *also* be a verified address, or emails will silently fail — check SES → Account dashboard → "Sandbox" status.
- Secrets Manager: secret `SignalSingaravelanSecrets` exists in `us-east-1` with key `TelegramBotToken`.

---

## 8. Application Configuration

**[EC2]**
```bash
cd ~/signal-singaravelan/trader-bot
cp .env.example .env
nano .env   # or vim
```
Fill in **only** the pair matching the currently-enabled account in `accounts.yaml`:
```
ALPACA_API_KEY_ROTH_IRA=<your Alpaca paper API key>
ALPACA_API_SECRET_ROTH_IRA=<your Alpaca paper API secret>
```
Get these from the Alpaca dashboard (paper account, since `accounts.yaml` currently has `paper: true`). Leave the `ALPACA_API_KEY_TAXABLE` / `ALPACA_API_SECRET_TAXABLE` lines in `.env.example` blank or delete them — there's no enabled `taxable` account in `accounts.yaml` right now.

**Sensitive values, for reference:**
| Item | Sensitive? | Where it lives |
|---|---|---|
| `ALPACA_API_KEY_ROTH_IRA` / `ALPACA_API_SECRET_ROTH_IRA` | **Yes** | `.env` on EC2 only, never git |
| `accounts.yaml` contents | No (env-var *names* and allocation %s only) | Tracked in git |
| `MASSIVE_API_KEY` | Yes, but currently plaintext in git (flagged in §2) | `config.py` |
| Telegram bot token | Yes | AWS Secrets Manager (not on disk anywhere) |
| AWS credentials | N/A — no static keys used | IAM role via instance metadata |

```bash
chmod 600 .env
```
Review `accounts.yaml` (already correct via git checkout — just confirm it reflects what you want to trade). Review `algo_trader/utils/config.py` — `EMAIL_TO` is already your address; no changes needed unless you want to redirect notifications elsewhere.

Do **not** create `~/.aws/credentials` on this instance — the attached IAM role supplies credentials automatically via instance metadata (this is why `compose.yaml`'s `~/.aws:/root/.aws:ro` volume mount is harmless to leave as-is: it'll mount an empty/nonexistent directory, and boto3 falls through to the IMDS-based role credentials).

---

## 9. Application Startup (first manual run)

**[EC2]**
```bash
cd ~/signal-singaravelan
docker compose build trader-bot
docker compose run --rm trader-bot
```

Check the output for, in order:
- `[roth-ira] Alpaca client initialized (status=ACTIVE)` — Alpaca auth works.
- `Signal: BULLISH` / `BEARISH` / `CLOSED` — strategy ran and reached a decision.
- Loading/uploading QQQ price history from S3 — no `NoCredentialsError` or `AccessDenied` (this is the IAM-role/hop-limit check from §4A in action).
- No `ERROR` lines.

```bash
docker ps -a          # confirm the container exited with code 0
docker images         # confirm the image built
```

Verify S3 access directly:
**[AWS CONSOLE]** S3 → `signal-singaravelan-market-data` → confirm `trade-history/qqq-price-history.csv` (and `market-outlook.xlsx`) exist with a recent timestamp. If a trade was placed, check `signal-singaravelan-roth-ira` → `trade-history/roth-ira-order-history.xlsx`.

Verify the Alpaca connection independently of a full run (useful if the full run fails for an unrelated reason and you want to isolate where):
```bash
docker compose run --rm trader-bot python -c "
from algo_trader.config.account_config import get_enabled_accounts
from algo_trader.clients import AlpacaClient
acct = get_enabled_accounts()[0]
c = AlpacaClient(acct)
c.initialize()
print('cash:', c.get_cash())
"
```

---

## 10. Startup-on-Reboot Configuration

As noted in §1, `trader-bot` is a one-shot job, not a daemon — there's no container to restart after a reboot. What must survive a reboot is the **scheduler**, not the app itself:

**[EC2]**
```bash
sudo systemctl enable docker     # already done in §4B — confirm
sudo systemctl enable crond
systemctl is-enabled docker
systemctl is-enabled crond
```
Both should print `enabled`.

Test it:
```bash
sudo reboot
```
**[LOCAL]** wait ~30–60s, then reconnect:
```bash
ssh -i /path/to/your-key.pem ec2-user@<new-instance-public-ip>
```
**[EC2]**
```bash
systemctl is-active docker
systemctl is-active crond
```
Both should print `active` with no manual intervention. "Started successfully after reboot" for this app means the schedule is armed and Docker is ready for it — actual confirmation that a *trade* run works after reboot comes from letting the next scheduled cron fire (or triggering it manually once, per §9) and checking its log.

Preventing duplicate instances isn't a systemd/process-supervision concern here (nothing is "running" between invocations) — it's handled by the `flock` guard in the wrapper script in §11.

---

## 11. Scheduled Trading Configuration

**[EC2]** Create the wrapper script and log directory:
```bash
sudo mkdir -p /opt/trader-bot /var/log/trader-bot
sudo chown ec2-user:ec2-user /opt/trader-bot /var/log/trader-bot
```

```bash
cat > /opt/trader-bot/run-trading-job.sh << 'EOF'
#!/bin/bash
set -euo pipefail

REPO_DIR="/home/ec2-user/signal-singaravelan"
LOG_DIR="/var/log/trader-bot"
LOCK_FILE="/tmp/trader-bot.lock"
LOG_FILE="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"

exec flock -n "$LOCK_FILE" bash -c "
  cd '$REPO_DIR'
  docker compose run --rm trader-bot
" >> "$LOG_FILE" 2>&1
EOF
chmod +x /opt/trader-bot/run-trading-job.sh
```

`flock -n` (non-blocking) means if a previous run is somehow still in progress when the next scheduled time hits, the new invocation exits immediately instead of queueing or running concurrently — this is what prevents overlapping/duplicate runs.

**[EC2]** Edit the crontab for `ec2-user` (the user with Docker group membership):
```bash
crontab -e
```
Add:
```
CRON_TZ=America/New_York
0 8 * * 1-5 /opt/trader-bot/run-trading-job.sh
```

**How this handles EST/EDT:** `CRON_TZ=America/New_York` (supported by `cronie`, the cron implementation on Amazon Linux 2023) tells cron to interpret `0 8 * * 1-5` as 8:00 AM in the `America/New_York` zone, including the automatic spring-forward/fall-back transition — no manual UTC-offset math, and nothing to edit twice a year. The EC2 instance's own system clock stays in UTC (the AWS-recommended default, and consistent with CloudWatch/Console timestamps), only cron's *interpretation* of the schedule shifts with the zone.

Because `CRON_TZ` support is a cron-implementation detail rather than a POSIX guarantee, **verify it explicitly before trusting it** (see §15) rather than assuming it works.

Environment/working directory: the wrapper script `cd`s into the repo directory explicitly, and `docker compose` picks up `trader-bot/.env` via the `env_file:` directive already in `compose.yaml` — nothing needs to be exported in the crontab itself. Cron's default `PATH` includes `/usr/bin`, where `docker` is installed, so no `PATH` adjustment should be needed (confirmed in §15's manual cron test).

**[EC2]** Manually test the exact command cron will run, before enabling the schedule for real:
```bash
/opt/trader-bot/run-trading-job.sh
echo "exit code: $?"
tail -50 /var/log/trader-bot/run-*.log
```

---

## 12. Logging and Log Rotation

**Log sources:**
- `/var/log/trader-bot/run-*.log` — one file per cron invocation (stdout/stderr of `docker compose run`, i.e. the same INFO/WARNING/ERROR lines the app prints to console).
- CloudWatch Logs (`signal-singaravelan-roth-ira` log group) — the app's own durable, long-term log store; already implemented in `cloudwatch_logger.py`, survives regardless of what happens to the EC2 disk.
- Docker container logs are not a separate concern — `--rm` removes the container immediately after exit, and its stdout/stderr is already captured by the wrapper script's redirection above.

**[EC2]** Configure rotation:
```bash
sudo tee /etc/logrotate.d/trader-bot << 'EOF'
/var/log/trader-bot/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    maxsize 10M
}
EOF
```
14 days / 10MB cap is generous for a job that logs a few KB per run — CloudWatch already holds the full history, so local retention only needs to keep the EC2 disk from filling.

Verify:
```bash
sudo logrotate -d /etc/logrotate.d/trader-bot   # dry run, shows what it would do
sudo logrotate -f /etc/logrotate.d/trader-bot   # force a rotation now
ls -la /var/log/trader-bot/
```

---

## 13. Monitoring

A second, independent safety net for **infrastructure-level** failures — the app already notifies you via SES/Telegram for *application-level* problems (rejected orders, signal errors, etc., via `NotificationService`), but that can't help if Docker itself won't start, the disk is full, or cron never fired at all.

**[EC2]**
```bash
cat > /opt/trader-bot/check-trader-bot.sh << 'EOF'
#!/bin/bash
LOG_DIR="/var/log/trader-bot"
TODAY_LOG=$(ls -t "$LOG_DIR"/run-$(date +%Y%m%d)*.log 2>/dev/null | head -1)
PROBLEMS=""

if [ -z "$TODAY_LOG" ]; then
  PROBLEMS="${PROBLEMS}No trading run log found for today.\n"
elif ! grep -q "BEGIN" "$TODAY_LOG" || ! grep -q "END" "$TODAY_LOG"; then
  PROBLEMS="${PROBLEMS}Today's run log is incomplete (missing BEGIN/END).\n"
fi

if [ -n "$TODAY_LOG" ] && grep -q "ERROR" "$TODAY_LOG"; then
  PROBLEMS="${PROBLEMS}ERROR lines found in today's log.\n"
fi

if ! systemctl is-active --quiet docker; then
  PROBLEMS="${PROBLEMS}Docker daemon is not running.\n"
fi

DISK_PCT=$(df / --output=pcent | tail -1 | tr -dc '0-9')
if [ "$DISK_PCT" -gt 85 ]; then
  PROBLEMS="${PROBLEMS}Disk usage at ${DISK_PCT}%.\n"
fi

if [ -n "$PROBLEMS" ]; then
  aws ses send-email \
    --region us-east-1 \
    --from "signalsingaravelan@gmail.com" \
    --destination "ToAddresses=ac.vino@gmail.com" \
    --message "Subject={Data=trader-bot monitoring alert},Body={Text={Data=$PROBLEMS}}"
fi
EOF
chmod +x /opt/trader-bot/check-trader-bot.sh
```
This reuses the SES permission already granted to the instance role — no extra secret needed in the shell script (deliberately avoiding pulling the Telegram token into bash, keeping secret access confined to the already-tested Python code).

**[EC2]** Schedule it ~30 minutes after the trading job:
```bash
crontab -e
```
Add:
```
CRON_TZ=America/New_York
30 8 * * 1-5 /opt/trader-bot/check-trader-bot.sh
```

---

## 14. Security Configuration

- **IAM role**: scoped to exactly this app's S3 buckets, log group prefix, one Secrets Manager secret, and SES send — not `AdministratorAccess` or wildcard resources (§7).
- **S3**: buckets have Block Public Access on; no bucket policy grants public/cross-account access.
- **Security group**: only port 22 inbound, restricted to your IP `/32`. No inbound port needed for the app itself.
- **SSH**: key-based only (default for Amazon Linux 2023 — password auth is disabled by default); restrict the security group to your IP as above; consider re-checking/updating that IP rule if your home/office IP changes.
- **`.env` / `accounts.yaml` permissions**: `.env` → `chmod 600` (done in §8). `accounts.yaml` has no secrets, default permissions are fine.
- **Alpaca API keys**: live only in `.env` on EC2 and in your local `.env` (both gitignored) and in the Alpaca dashboard. Never logged — the app doesn't print `.env` contents anywhere.
- **GitHub credentials**: the EC2 instance uses a dedicated **read-only deploy key** (§6), not a personal access token or your own SSH key — if compromised, it can only read this one repo, not push or access anything else.
- **AWS credentials**: none stored on disk anywhere — IAM role via instance metadata only (§4A's hop-limit setting is what makes this work from inside the container).
- **Secrets in logs**: reviewed — `NotificationService`/`AlpacaClient`/`TradeLogger` log account names, symbols, dollar amounts, and error messages, but never API keys/secrets/tokens.
- **Docker**: the container currently runs as root inside itself (no `USER` directive in `Dockerfile`) — low priority for a single-purpose personal trading bot on a locked-down instance, but worth knowing; not required for this deployment.

---

## 15. Testing and Verification

### Infrastructure
```bash
# [EC2]
ping -c 3 8.8.8.8                  # internet connectivity
docker ps -a                       # docker status
df -h /                            # disk space
free -h                            # memory
docker compose run --rm trader-bot python -c "import boto3; print(boto3.client('sts').get_caller_identity())"   # confirms IAM role + hop-limit are correctly working from inside the container
```

### Application
- Configuration loading: a bad `accounts.yaml` (e.g. allocations not summing to 100) raises `ValueError` at startup — confirmed already by your local `pytest` run; on EC2, the manual run in §9 is the equivalent check.
- Alpaca authentication: `[roth-ira] Alpaca client initialized (status=ACTIVE)` in the log.
- Market-data connectivity: Massive.com fetch and Alpaca `get_price`/`get_portfolio_history` calls both succeed with no `ERROR` lines.
- Container health: `docker ps -a` shows exit code 0 for the last run.
- Logs: both `/var/log/trader-bot/run-*.log` and the CloudWatch log group show the expected entries.

### Scheduling
```bash
# [EC2]
crontab -l                                          # both trading and monitoring lines present
/opt/trader-bot/run-trading-job.sh; echo $?          # manual execution, exit code 0

# DST/CRON_TZ verification — temporarily add, watch it fire twice, then remove:
crontab -e
# add: * * * * * date >> /tmp/cron-tz-test.log
# wait 2-3 minutes, then:
cat /tmp/cron-tz-test.log
date                                                  # compare against system UTC time
TZ=America/New_York date                              # confirm the cron log timestamps match this, not the line above
crontab -e   # remove the test line
rm /tmp/cron-tz-test.log
```
- Duplicate execution prevention: with the job running, manually invoke `/opt/trader-bot/run-trading-job.sh` a second time in another terminal — it should exit immediately (flock held), not run a second `docker compose` invocation.

### Trading Safety — before enabling live trading

- **Correct Alpaca account**: log in to the Alpaca dashboard with the credentials you put in `.env`, confirm it's the intended paper account (or, later, the intended live account).
- **Correct account configuration**: `accounts.yaml` — `roth-ira` allocations sum to 100% (already validated at startup), tickers are what you intend (`VTI/VOO/VUG/VGT/QQQ`).
- **Correct symbols / strategy / position sizing / buy-sell logic**: unchanged from what you already tested locally in §9 of the previous conversation — this deployment doesn't touch application logic, only where it runs.
- **No IBKR connection remains**: `grep -ri ibkr trader-bot/` on EC2 should return nothing (the migration already removed `ibkr_client.py` and `ibeam/`).
- **No old IBKR process running**: confirmed by §3 (old instance's cron disabled/instance stopped).
- **No duplicate trading process**: confirmed by the `flock` guard (§11) and by making sure only *one* EC2 instance has the trading cron job enabled.
- **No unexpected orders**: run once manually (§9) with `paper: true` and check Alpaca's paper dashboard order history matches exactly what the logs/S3 trade log say.

**Paper trading for final verification**: `accounts.yaml`'s `roth-ira` account already has `paper: true`. Let it run on the real 8am ET schedule against the paper account for several trading days, comparing each day's Alpaca paper order history against the CloudWatch/S3 logs, before touching `paper: false`.

---

## 16. Final Production Checklist

Before flipping `paper: true` → `false` in `accounts.yaml` for any account:

- [ ] New EC2 instance has run successfully, unattended, via the real cron schedule (not just manual invocation) for **at least 3–5 consecutive trading days**.
- [ ] Old IBKR EC2 instance's trading cron is disabled (§3) — confirmed no double-trading occurred on any overlapping day.
- [ ] CloudWatch logs and S3 trade-history Excel for each of those days reviewed and match Alpaca's paper dashboard order history exactly.
- [ ] Monitoring script (§13) has fired at least once as a test (temporarily break something, e.g. stop Docker, confirm you get the SES alert) so you trust it before relying on it.
- [ ] Log rotation confirmed working (§12), disk usage stable across those days.
- [ ] Security group still restricted to your current IP.
- [ ] `MASSIVE_API_KEY` plaintext-in-git decision made (fixed or consciously deferred).
- [ ] SES sandbox status checked — if still sandboxed, both `EMAIL_FROM` and `EMAIL_TO` are verified identities.
- [ ] You've reviewed the exact dollar amounts/allocations one more time — going live means real orders at 8am ET tomorrow.
- [ ] Old EC2 instance terminated (or explicitly kept as a documented rollback, with its cron confirmed disabled) once you're confident.

Only after every box is checked: edit `accounts.yaml` on EC2, set `paper: false` for the account(s) going live, `git` isn't involved for this toggle (it's a local edit outside the checked-out commit — track this deliberately, e.g. in your own notes, since `accounts.yaml` is git-tracked and a future `git pull`/`checkout` on this instance could silently revert it back to `paper: true` unless you also commit the live-flip change).

---

## Things worth deciding that go beyond the original request

1. **IMDSv2 hop limit (§4A)** — the most likely single point of failure if skipped; called out prominently above, repeating here since it's easy to miss during instance launch.
2. **`MASSIVE_API_KEY` plaintext in git** — pre-existing, unrelated to the Alpaca migration itself, but this deployment is a natural point to fix it.
3. **`cloudwatch_logger.py`'s instance-ID lookup** uses an unauthenticated (IMDSv1-style) request; under AL2023's IMDSv2-enforced default it will fail and fall back to using the hostname for the CloudWatch log stream name instead of the EC2 instance ID. Harmless — logs still work — just don't be surprised by the naming.
4. **Billing safety net** — trading bots running unattended on real money are exactly the kind of thing worth a cheap tripwire: **[AWS CONSOLE]** Billing → Budgets → create a simple monthly budget alert (e.g. $20) so an unexpected AWS cost spike (runaway logging, accidental resource creation, etc.) reaches you by email quickly. Costs here should be a few dollars/month (t3.micro + minimal S3/CloudWatch/SES usage), so this is purely a safety net, not an expected trigger.
5. **`accounts.yaml`'s live-trading flip isn't git-tracked separately from the rest of the deploy** — noted in §16's checklist; worth a deliberate process (e.g. commit the `paper: false` change so it's visible in history, or keep a separate note) rather than a silent on-instance edit.
6. **Tag the EC2 instance** (`Name = signal-singaravelan-trader-bot`) so it's unambiguous which instance is which while both old and new exist side by side during the transition window.
