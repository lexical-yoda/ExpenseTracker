# kharcha — Personal Expense Tracker

Flask-based expense tracker with mobile-friendly frontend.
Runs on **redfive** (`10.0.1.10:5000`), WireGuard-only.
Stores data in an `.xlsx` file on TrueNAS.

---

## Setup on redfive

### 1. Mount TrueNAS share

Add to `/etc/fstab` (adjust path to your TrueNAS SMB share):

```
//192.168.1.20/lexishare/expenses  /mnt/expenses  cifs  credentials=/etc/smb-credentials,uid=1000,gid=1000,iocharset=utf8  0  0
```

Create credentials file at `/etc/smb-credentials`:
```
username=lexishare
password=YOUR_PASSWORD
```

Then: `sudo chmod 600 /etc/smb-credentials && sudo mount -a`

### 2. Clone / copy this project

```bash
mkdir -p ~/apps/kharcha
# copy all files here
```

### 3. Install dependencies

```bash
cd ~/apps/kharcha
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Set the spreadsheet path

```bash
export EXPENSES_XLSX=/mnt/expenses/expenses.xlsx
```

Or set it permanently in the systemd service (see below).

### 5. Run (dev test)

```bash
source venv/bin/activate
EXPENSES_XLSX=/mnt/expenses/expenses.xlsx python app.py
```

Open `http://10.0.1.10:5000` on any WireGuard device.

---

## Run as systemd service

Create `/etc/systemd/system/kharcha.service`:

```ini
[Unit]
Description=Kharcha Expense Tracker
After=network.target

[Service]
User=red_leader
WorkingDirectory=/home/red_leader/apps/kharcha
Environment=EXPENSES_XLSX=/mnt/expenses/expenses.xlsx
ExecStart=/home/red_leader/apps/kharcha/venv/bin/python app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kharcha
sudo systemctl status kharcha
```

---

## First-time spreadsheet setup

On first launch, the app auto-creates `expenses.xlsx` at `EXPENSES_XLSX` path.
Open it in LibreOffice Calc and set:
- **B1** — your Credit Card limit (e.g. `150000` for ₹1,50,000)
- **B2** — your Opening Savings Balance for the month

---

## Project structure

```
kharcha/
├── app.py              # Flask routes
├── spreadsheet.py      # openpyxl read/write logic
├── categories.json     # Category/sub-category definitions
├── requirements.txt
└── templates/
    ├── add.html        # /add  — expense entry form
    ├── expenses.html   # /expenses — transaction list
    └── dashboard.html  # /dashboard — Plotly charts
```

---

## URLs

| URL | Purpose |
|-----|---------|
| `http://10.0.1.10:5000/` | Redirects to /add |
| `http://10.0.1.10:5000/add` | Add new expense |
| `http://10.0.1.10:5000/add/sub/<id>` | Add sub-expense to transaction |
| `http://10.0.1.10:5000/expenses` | Transaction list |
| `http://10.0.1.10:5000/dashboard` | Charts & summary |

---

## Notes

- Only parent transactions count toward balance calculations — sub-items don't double-count
- Transaction IDs are global integers across all months — safe to use as Parent IDs even if rows are inserted
- The `.xlsx` is the single source of truth — you can still edit it manually in LibreOffice Calc
- `categories.json` is updated live from the frontend — no restart needed
