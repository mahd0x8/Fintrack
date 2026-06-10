# FinTrack — Personal Finance Manager

A full-stack personal finance web application built with Flask and SQLite. Track income, expenses, budgets, and savings goals — accessible from any device, secured with a PIN lock, and deployed to Azure with automated CI/CD.

**Live app:** Privately hosted on Azure Container Apps

---

## Screenshots

### Desktop
![App on Laptop](Screenshots/App%20on%20Laptop.png)

### Mobile
![App on Mobile](Screenshots/APP%20on%20Mobile.png)

---

## Features

- **PIN lock** — 4-digit PIN required on every visit, with a password fallback if PIN is forgotten
- **User registration** — single-user account with username, name, password, and PIN
- **Dashboard overview** — total income, total expenses, after-full-budget projection, and net savings
- **Transaction management** — add, edit, delete income and expense transactions with categories, dates, and notes
- **Budget tracker** — set monthly limits per category with visual progress bars and overspend alerts
- **Savings goals** — create goals with target amounts and dates, link transactions directly to goals
- **Goal-linked transactions** — expense transactions can contribute to a savings goal automatically
- **Custom categories** — add, edit, and delete transaction categories with custom icons and colors
- **6-month cash flow chart** — bar chart showing income vs expenses over the last 6 months
- **Spending breakdown** — doughnut chart showing expenses by category
- **Savings trend** — line chart tracking net savings over 6 months
- **Currency selector** — supports USD, PKR, EUR, GBP, AED, INR, and 14 other currencies
- **Dark / Light / Auto theme** — manual override or follows system preference
- **CSV export** — download all transactions for the selected month
- **Danger zone** — selectively clear transactions, budgets, goals, or reset all data
- **Mobile responsive** — works on phones and tablets, accessible over local network

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask 3.1 |
| Database | SQLite (persisted via Azure Files) |
| Frontend | Vanilla JS, Chart.js, HTML/CSS |
| Auth | Werkzeug password hashing, Flask sessions |
| Server | Gunicorn |
| Container | Docker |
| Registry | GitHub Container Registry (ghcr.io) |
| Hosting | Azure Container Apps (consumption tier) |
| Storage | Azure Files (SMB) for SQLite persistence |
| CI/CD | GitHub Actions |

---

## Project Structure

```
Financing/
├── app.py                  # Flask backend — all routes and DB logic
├── templates/
│   └── index.html          # Single-page frontend (HTML + CSS + JS)
├── assets/
│   └── money-management.png
├── Screenshots/
│   ├── App on Laptop.png
│   └── APP on Mobile.png
├── Dockerfile
├── docker-compose.yml      # Local development with named volume
├── requirements.txt
├── azure-setup.sh          # One-time Azure infrastructure setup script
├── containerapp-update.yaml
└── .github/
    └── workflows/
        └── deploy.yml      # CI/CD pipeline
```

---

## Running Locally

### With Python directly

```bash
git clone https://github.com/mahd0x8/Fintrack.git
cd Fintrack
pip install -r requirements.txt
python3 app.py
```

Open `http://localhost:5000` — first visit shows the registration screen.

### With Docker Compose

```bash
docker compose up --build
```

Open `http://localhost:5000`. SQLite data is persisted in a named Docker volume (`finance_data`).

### Access from mobile (same Wi-Fi)

Find your machine's local IP:
```bash
ip addr show | grep "inet " | grep -v 127
```
Then open `http://<your-ip>:5000` on your phone.

---

## Deployment (Azure Container Apps)

### One-time setup

1. Install the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) and log in:
   ```bash
   az login
   ```

2. Create a GitHub Personal Access Token with `write:packages` scope at
   `https://github.com/settings/tokens`

3. Log in to GitHub Container Registry:
   ```bash
   export GITHUB_PAT=ghp_your_token_here
   echo $GITHUB_PAT | docker login ghcr.io -u YOUR_USERNAME --password-stdin
   ```

4. Run the setup script (creates all Azure resources and deploys):
   ```bash
   bash azure-setup.sh
   ```

5. Copy the JSON printed at the end and add it to GitHub repository secrets:

   | Secret | Value |
   |--------|-------|
   | `AZURE_CREDENTIALS` | JSON output from the script |
   | `APP_NAME` | `my-finance-app` |
   | `RESOURCE_GROUP` | `finance-rg` |

### CI/CD

Every push to `main` or `develop` automatically:
1. Builds a new Docker image
2. Pushes it to `ghcr.io`
3. Deploys a new revision to Azure Container Apps

The pipeline uses `--revision-suffix` with the GitHub run number to force Azure to pull the latest image on every deploy.

---

## Authentication Flow

```
First visit
    └── No account registered → Registration screen
            └── Enter name, username, password, PIN → App unlocked

Every subsequent visit
    └── PIN screen (4-digit numpad)
            ├── Correct PIN → App unlocked
            └── Forgot PIN → Password login screen
                    └── Correct credentials → App unlocked

Settings → Sign out → PIN screen
```

All API routes require an active session. Passwords and PINs are hashed with Werkzeug's `pbkdf2:sha256` algorithm and never stored in plain text.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `./finance.db` | Path to the SQLite database file |
| `SECRET_KEY` | `finance-secret-key-change-in-prod` | Flask session signing key — **change this in production** |

Set `SECRET_KEY` as an environment variable on Azure for proper security:
```bash
az containerapp update \
  --name my-finance-app \
  --resource-group finance-rg \
  --set-env-vars SECRET_KEY=your-random-secret-here
```

---

## License

MIT
