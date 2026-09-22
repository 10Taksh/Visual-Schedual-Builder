# Deploying on Oracle Cloud Always Free

One Always Free VM runs the whole app: gunicorn serves Flask, Caddy sits in front on
port 80/443, and SQLite lives on the VM's persistent boot volume. Nothing here costs money.

**What you get:** an Ampere A1 VM with up to 4 OCPUs and 24 GB RAM (or, if A1 capacity is
unavailable, an AMD `VM.Standard.E2.1.Micro` with 1 GB — still plenty for this app), a public
IPv4 address, and a disk that survives restarts.

## 1. Create the account and pick a region

Sign up at <https://www.oracle.com/cloud/free/>. **The home region cannot be changed later**,
and Always Free resources only exist in the home region — pick the one closest to your users.

> **Recommended:** once the account is active, upgrade it to **Pay As You Go** (Account →
> Upgrade). You are still not charged while inside the Always Free limits, but two things
> improve: Ampere A1 capacity is prioritised for paid accounts (free-tier accounts frequently
> see *Out of host capacity*), and Oracle no longer reclaims your VM for being idle. Free-tier
> accounts can have instances stopped after 7 days of low CPU/network use — a small
> scheduling app *is* idle most of the time.

## 2. Create the VM

Console → **Compute → Instances → Create instance**.

| Setting | Value |
|---|---|
| Image | **Canonical Ubuntu 24.04** (Ubuntu 24.04 Minimal also works) |
| Shape | **Ampere → VM.Standard.A1.Flex**, 1 OCPU / 6 GB is more than enough (or AMD → `VM.Standard.E2.1.Micro`) |
| Networking | *Create new virtual cloud network* (default settings), **Assign a public IPv4 address: Yes** |
| SSH keys | Upload your public key, or generate a pair and download the private key |
| Boot volume | default 47 GB |

Click **Create**. When the state is *Running*, note the **Public IP address**.

If you see *Out of host capacity* for A1: try another availability domain in the same region,
try again later (capacity frees up regularly), or use the E2.1.Micro shape for now — you can
recreate the instance on A1 later; the setup script rebuilds everything from git.

## 3. Open ports 80 and 443 in the cloud firewall

Console → **Networking → Virtual cloud networks → your VCN → Subnets → your subnet →
Security Lists → Default Security List → Add Ingress Rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

Port 22 is already open. The VM's own firewall (iptables inside Ubuntu) also blocks 80/443 by
default on Oracle's images; `setup.sh` opens those for you.

## 4. Run the setup script

```bash
ssh -i ~/.ssh/your-key ubuntu@<PUBLIC-IP>
```

```bash
curl -fsSL https://raw.githubusercontent.com/10Taksh/Visual-Schedual-Builder/main/deploy/setup.sh -o setup.sh
```

```bash
sudo REPO_URL=https://github.com/10Taksh/Visual-Schedual-Builder.git BRANCH=main bash setup.sh
```

The script installs Python, Caddy and sqlite3; opens the VM firewall; creates a `schedule`
service user; clones the repo to `/opt/schedule-builder`; builds a virtualenv; writes
`/etc/schedule-builder.env` with a generated `SECRET_KEY`; installs and starts the
`schedule-builder` systemd service and Caddy; and schedules a nightly database backup.
It finishes by printing the health-check result and the URL to open.

Open `http://<PUBLIC-IP>/` — the employee directory loads and the database is created at
`/var/lib/schedule-builder/schedule.db`.

## 5. Optional: a domain and HTTPS

Point an `A` record at the public IP (any registrar, or a free subdomain from DuckDNS /
FreeDNS), then re-run the script with the hostname:

```bash
sudo DOMAIN=schedule.example.com bash /opt/schedule-builder/deploy/setup.sh
```

Caddy obtains a Let's Encrypt certificate automatically and redirects HTTP to HTTPS.

## Day-to-day

| Task | Command |
|---|---|
| Deploy a new version | `sudo bash /opt/schedule-builder/deploy/setup.sh` (pulls, reinstalls, restarts) |
| Deploy a branch | `sudo BRANCH=my-branch bash /opt/schedule-builder/deploy/setup.sh` |
| App logs | `journalctl -u schedule-builder -f` |
| Web server logs | `tail -f /var/log/caddy/schedule-builder.log` |
| Restart the app | `sudo systemctl restart schedule-builder` |
| Change settings | `sudo nano /etc/schedule-builder.env` then restart |
| Backups | `/var/lib/schedule-builder/backups/` — nightly at 03:15, last 14 kept |
| Restore a backup | `sudo systemctl stop schedule-builder && zcat backups/schedule-….db.gz \| sudo -u schedule tee schedule.db >/dev/null && sudo systemctl start schedule-builder` |

## Switching to Postgres later

SQLite is the right call for one VM and a team-sized schedule. If you ever run more than
one instance or want managed backups:

```bash
sudo apt install -y postgresql
sudo -u postgres psql -c "CREATE USER schedule WITH PASSWORD 'choose-a-password';" -c "CREATE DATABASE schedule OWNER schedule;"
```

Then in `/etc/schedule-builder.env` comment out `DATABASE_PATH` and set
`DATABASE_URL=postgresql://schedule:choose-a-password@localhost/schedule`, restart the
service, and re-enter your data (or use `/export/shifts.csv` from the old instance as a
reference). Note that Oracle's free **Autonomous Database** is Oracle Database, not
Postgres — this app does not target it.

## Troubleshooting

- **Page never loads but `curl http://127.0.0.1:8000/health` works on the VM** → the cloud
  security list (step 3) or the VM iptables rules aren't open. Re-run `setup.sh`, and check
  `sudo iptables -L INPUT -n --line-numbers` shows ACCEPT rules for 80/443 *above* the REJECT.
- **`Out of host capacity`** → see step 2.
- **Instance stopped by itself** → idle reclamation on a free-tier account; upgrade to Pay As
  You Go (step 1) and start the instance again.
- **`database is locked` in the logs** → only happens under heavy concurrent writes;
  `app/db.py` already waits up to 15 s. Lower `--workers` to 1 in the service file if it persists.
