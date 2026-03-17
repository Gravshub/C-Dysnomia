# |>JOYSTICK<| VPS Deployment Guide

> *"We're in."*

This guide walks you through getting the JOYSTICK bot running 24/7 on your VPS.
Written for someone doing this for the first time — every step explained.

---

## What You Need Before Starting

- **Your VPS**: A Linux server (Ubuntu 22.04 or 24.04 recommended). The $15/mo one works great.
- **SSH access**: The ability to connect to your VPS from your terminal.
- **Your private key**: The hex string for Joey's wallet (`0x17367...`). You'll type it once, into one file, and never again.

---

## The Big Picture

Here's what we're building:

```
Your VPS ($15/mo)
├── /opt/joystick/
│   ├── .env.pulse          ← Your private key lives here (locked down)
│   ├── venv/               ← Python packages (isolated from system)
│   ├── repo/               ← The GitHub repo (git pull to update)
│   │   └── scripts/Joystick/
│   │       ├── bot.py      ← The bot (runs as a service, 24/7)
│   │       └── dashboard/  ← The API (serves data to the web dashboard)
│   ├── data/               ← Bot writes state files here
│   └── logs/               ← Log files
│
├── joystick-bot.service    ← systemd keeps the bot alive
└── joystick-api.service    ← systemd keeps the API alive
```

---

## Step 1: Connect to Your VPS

Open your terminal (Mac: Terminal app, Windows: PowerShell or PuTTY).

```bash
ssh root@YOUR_VPS_IP_ADDRESS
```

You'll see a command prompt. You're now on your VPS.
Everything from here happens on the VPS, not your laptop.

---

## Step 2: Run the Setup Script

Two options:

**Option A: Download and run directly (easiest)**
```bash
apt-get update && apt-get install -y curl git
curl -O https://raw.githubusercontent.com/Gravshub/C-Dysnomia/claude/joystick-V2-FanxJ/scripts/Joystick/deploy/setup_vps.sh
chmod +x setup_vps.sh
bash setup_vps.sh
```

**Option B: Clone first, then run**
```bash
apt-get update && apt-get install -y git python3 python3-venv python3-pip
git clone --branch claude/claude/joystick-V2-FanxJ https://github.com/Gravshub/C-Dysnomia.git /opt/joystick/repo
bash /opt/joystick/repo/scripts/Joystick/deploy/setup_vps.sh
```

The script takes about 2-3 minutes. It will:
- Create a dedicated `joystick` user (security)
- Set up the Python environment
- Install all dependencies
- Copy the systemd service files
- Print the next steps

---

## Step 3: Add Your Private Key

This is the most important step. The setup script created a template file.
You need to edit it and replace the placeholder with your real key.

```bash
nano /opt/joystick/.env.pulse
```

**What you'll see:**
```
PRIVATE_KEY=YOUR_PRIVATE_KEY_HERE
```

**What you need to change it to:**
```
PRIVATE_KEY=abc123def456...your64characterhexkey...
```

(No `0x` prefix. Just the 64 hex characters.)

**Save and exit nano:**
- Press `Ctrl+O` (the letter O) → press `Enter` to confirm
- Press `Ctrl+X` to exit

**Verify the file is locked down:**
```bash
ls -la /opt/joystick/.env.pulse
```
You should see `-rw-------` at the start. That means only the owner can read it.
If you see anything else:
```bash
chmod 600 /opt/joystick/.env.pulse
```

---

## Step 4: Test the Connection

Before starting the bot, verify it can talk to PulseChain:

```bash
sudo -u joystick bash -c '
  set -a && source /opt/joystick/.env.pulse && set +a
  /opt/joystick/venv/bin/python -c "
from web3 import Web3
w = Web3(Web3.HTTPProvider(\"https://rpc-pulsechain.g4mm4.io\"))
block = w.eth.block_number
bal = w.eth.get_balance(Web3.to_checksum_address(\"0x17367877aF5A8D0Eb33ba5689A880f696386E24D\"))
print(f\"Chain connected!\")
print(f\"Block: {block:,}\")
print(f\"Joey PLS: {bal / 1e18:,.2f}\")
"'
```

You should see something like:
```
Chain connected!
Block: 26,044,833
Joey PLS: 1,979,624.60
```

If you see an error, check:
- Is the VPS connected to the internet? (`ping 8.8.8.8`)
- Did you install the Python packages? (`/opt/joystick/venv/bin/pip list`)

---

## Step 5: Dry Run (Simulate Without Sending)

```bash
cd /opt/joystick/repo/scripts/Joystick
sudo -u joystick bash -c '
  set -a && source /opt/joystick/.env.pulse && set +a
  /opt/joystick/venv/bin/python bot.py --dry-run
'
```

This runs one cycle of the bot without sending any transactions.
You'll see which engines are ready, what they'd do, and what the expected profit is.

If this looks good, you're ready to go live.

---

## Step 6: Start the Bot (Goes Live!)

```bash
sudo systemctl start joystick-bot
```

That's it. The bot is now running. It will:
- Run engine cycles every 30 seconds
- Skip cycles when gas is above the ceiling
- Execute the highest-ROI engine each cycle
- Auto-restart if it crashes
- Start again if the VPS reboots

**Watch it work:**
```bash
journalctl -u joystick-bot -f
```
(Press `Ctrl+C` to stop watching. The bot keeps running.)

---

## Step 7: (Optional) Start the Dashboard API

```bash
sudo systemctl start joystick-api
```

This serves the dashboard data on port 8369. You can test it:
```bash
curl http://localhost:8369/health
```

For the web dashboard to reach this from the internet,
you'll need to open port 8369 in your VPS firewall:
```bash
ufw allow 8369/tcp
```

---

## Daily Operations

### Check if the bot is running
```bash
sudo systemctl status joystick-bot
```

### View recent logs
```bash
# Last 50 lines
journalctl -u joystick-bot -n 50

# Everything from the last hour
journalctl -u joystick-bot --since "1 hour ago"

# Live stream (watch in real-time)
journalctl -u joystick-bot -f
```

### Stop the bot
```bash
sudo systemctl stop joystick-bot
```

### Update to latest code
After pushing changes to GitHub:
```bash
sudo bash /opt/joystick/repo/scripts/Joystick/deploy/update.sh
```
This pulls the latest code and restarts the services.

### Run the health check
```bash
bash /opt/joystick/repo/scripts/Joystick/deploy/health_check.sh
```
Shows: service status, RPC connection, wallet balance, gas price, disk space.

---

## Troubleshooting

### "Bot keeps restarting"
```bash
journalctl -u joystick-bot --since "10 minutes ago"
```
Look for error messages. Common causes:
- Wrong private key in `.env.pulse`
- RPC endpoint down (try switching to `rpc.pulsechain.com`)
- Python import error (run `update.sh` to reinstall deps)

### "Can't connect to RPC"
```bash
curl -s https://rpc-pulsechain.g4mm4.io -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
```
If this fails, the RPC might be down. Switch `RPC_URL_READ` in `.env.pulse` to
`https://rpc.pulsechain.com` temporarily.

### "Permission denied"
Always run bot commands as the `joystick` user:
```bash
sudo -u joystick COMMAND
```
Service commands need `sudo`:
```bash
sudo systemctl restart joystick-bot
```

### "Service not found"
The service files need to be in `/etc/systemd/system/`. Re-run:
```bash
sudo cp /opt/joystick/repo/scripts/Joystick/deploy/joystick-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable joystick-bot
```

---

## Security Checklist

- [ ] Private key is in `.env.pulse` with `chmod 600` permissions
- [ ] Bot runs as `joystick` user, NOT root
- [ ] `.env.pulse` is NOT in the git repo (check `.gitignore`)
- [ ] VPS has a firewall (`ufw enable`)
- [ ] SSH key authentication (disable password login if possible)
- [ ] Only port 22 (SSH) and optionally 8369 (API) are open

---

## File Locations Quick Reference

| What | Where |
|------|-------|
| Private key / config | `/opt/joystick/.env.pulse` |
| Bot code | `/opt/joystick/repo/scripts/Joystick/` |
| Dashboard API | `/opt/joystick/repo/scripts/Joystick/dashboard/` |
| Bot state files | `/opt/joystick/data/` |
| Log files | `/opt/joystick/logs/` |
| Python packages | `/opt/joystick/venv/` |
| Service files | `/etc/systemd/system/joystick-*.service` |
| Setup script | `.../deploy/setup_vps.sh` |
| Update script | `.../deploy/update.sh` |
| Health check | `.../deploy/health_check.sh` |

---

*|>JOYSTICK<| — the machine is deployed. now it earns.*
