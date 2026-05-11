# ✦ Prism

> **See exactly how much your AI agents are costing you — by model, platform, time, and tool. Zero config, no API keys, runs 100% locally.**

Prism reads your existing [Hermes Agent](https://github.com/NousResearch/hermes-agent) session databases and serves a beautiful, interactive dashboard with real-time cost analytics. No accounts, no cloud, no API connections — just data you already have, visualized.

---

## Quick Start

```bash
git clone https://github.com/SlothDev007/prism.git
cd prism
pip install fastapi uvicorn
python server.py
```

Open [http://localhost:8081](http://localhost:8081) — your dashboard is live.

---

## Features

- **Auto-discovery** — Finds all `.hermes/state.db` files (main + all profiles) automatically.
- **Zero config** — No API keys, no setup, no accounts. Just run it.
- **Multi-profile** — Aggregates data across all your Hermes profiles (CEO, Lead Dev, etc.).
- **Dark mode** — White/clean by default, dark on toggle. Preference saved.
- **Responsive** — Works on desktop and mobile.
- **Privacy-first** — All data stays on your machine. Nothing is sent anywhere.
- **Always current** — Refresh the page to see the latest data. No caching.

## Dashboard Sections

| Section | What it shows |
|---------|---------------|
| **Hero Cards** | Total spend, sessions, tokens, avg cost per session + period-over-period delta |
| **Daily Spend** | Bar chart of daily costs (7d / 30d / 90d toggle) |
| **Spend by Model** | Doughnut chart of cost split across models |
| **Spend by Platform** | Donut showing Cron vs Discord vs CLI vs other |
| **Token Breakdown** | Stacked horizontal bar of input vs output tokens per model |
| **Recent Sessions** | Table with model, platform, title, tokens, duration, cost |
| **Most Expensive** | Ranked table of your costliest sessions |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/overview?days=30` | Totals, models, sources, active days, cost delta |
| `GET /api/daily?days=30` | Daily cost breakdown (fills gaps with $0) |
| `GET /api/models` | Per-model cost, sessions, tokens, cache reads/writes |
| `GET /api/sources` | Per-platform cost and session counts |
| `GET /api/sessions?limit=50` | Paginated recent sessions |
| `GET /api/expensive?limit=20` | Most expensive sessions by cost |
| `GET /api/databases` | Discovered databases with counts |

## How It Works

1. Prism scans `~/.hermes/state.db` + `~/.hermes/profiles/*/state.db`.
2. Queries the `sessions` table: tokens, costs, models, timestamps, tools.
3. Computes aggregations (daily totals, per-model breakdowns, per-platform split).
4. Serves a single-page dashboard with Chart.js visualizations.
5. Every read is read-only — your Hermes database is never modified.

## Tech Stack

- **Backend**: FastAPI + uvicorn
- **Database**: Python sqlite3 (read-only against existing Hermes `state.db`)
- **Frontend**: Single HTML page, Chart.js via CDN, vanilla JS + CSS
- **No build tools**, no npm, no bundlers — just Python

## Requirements

- Python 3.10+
- Hermes Agent (with sessions in `~/.hermes/state.db`)
- That's it.

## Customizing the DB Path

Set `HERMES_HOME` to point Prism at a different Hermes installation:

```bash
HERMES_HOME=/path/to/hermes python server.py
```

## Screenshots

> Coming soon — open the dashboard and take a screenshot for the README!

## License

MIT — use it, modify it, share it.

## Author

Built by [Caido](https://github.com/caido)
