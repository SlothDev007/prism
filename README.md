# ✦ Prism

> **See exactly how much your AI agents are costing you — and identify inefficiencies, context bottlenecks, and wasted spend.** Zero config, no API keys, runs 100% locally.

Prism reads your existing [Hermes Agent](https://github.com/NousResearch/hermes-agent) session databases and serves a beautiful, interactive dashboard with real-time cost analytics, bottleneck detection, and context tracking. No accounts, no cloud, no API connections — just data you already have, visualized.

---

## ✨ What's New

| Feature | Description |
|---------|-------------|
| **Efficiency Analysis** | Detect stuck sessions, high cost-per-message ratios, and cache inefficiency. New `Efficiency` tab with actionable insights. |
| **Context Tracking** | Monitor compression events, session resets, and context pressure across models. New `Context` tab with lifecycle analytics. |
| **Bottleneck Detection** | Aggregate waste metrics showing which models and sessions are burning the most money inefficiently. |
| **In-Memory Caching** | 15-second TTL cache on all API endpoints — no more repeated database reads. |
| **Days=9999 Support** | Query your entire session history without validation errors. |
| **CORS on Validation Errors** | 422 responses now include proper CORS headers for remote dashboard access. |

---

## Quick Start

```bash
git clone https://github.com/SlothDev007/prism.git
cd prism
pip install fastapi uvicorn
python server.py
```

Open [http://localhost:8081](http://localhost:8081) — your dashboard is live.

**Custom port:** `python server.py --port 3000` or set `PRISM_PORT=3000` for permanent config.

---

## Features

- **Auto-discovery** — Finds all `.hermes/state.db` files (main + all profiles) automatically.
- **Zero config** — No API keys, no setup, no accounts. Just run it.
- **Multi-profile** — Aggregates data across all your Hermes profiles (CEO, Lead Dev, etc.).
- **Three tab views** — Dashboard (costs) · Efficiency (waste detection) · Context (pressure analytics).
- **Dark mode** — White/clean by default, dark on toggle. Preference saved in localStorage.
- **Responsive** — Works on desktop and mobile.
- **Privacy-first** — All data stays on your machine. Nothing is sent anywhere.
- **Always current** — Refresh the page to see the latest data. API responses cached for 15s.
- **Lazy loading** — Efficiency and Context tabs fetch data only on first visit.

## Dashboard Sections

| Tab | Section | What it shows |
|-----|---------|---------------|
| **Dashboard** | Hero Cards | Total spend, sessions, tokens, avg cost per session + period-over-period delta |
| | Daily Spend | Bar chart of daily costs (7d / 30d / 90d toggle) |
| | Spend by Model | Doughnut chart of cost split across models |
| | Spend by Platform | Donut showing Discord vs CLI vs Cron vs other |
| | Token Breakdown | Stacked horizontal bar of input vs output tokens per model |
| | Recent Sessions | Table with model, platform, title, tokens, duration, cost |
| | Most Expensive | Ranked table of your costliest sessions |
| **Efficiency** | Summary Cards | Avg cost/message, inefficient sessions count, stuck sessions, cache hit rate |
| | Cache Utilization | Bar chart of cache read vs write tokens per model |
| | Inefficient Sessions | Top 20 sessions by cost-per-message ratio |
| | Stuck Sessions | Sessions with high tool calls but low output (tool_count > 10, output < 1000) |
| **Context** | Summary Cards | Compression events, resets, sessions under pressure, highest avg-msg model |
| | Message Distribution | Histogram of session message count buckets |
| | Pressure by Model | Bar chart of avg messages per session + compression/reset rate |
| | End Reasons | Doughnut chart of session lifecycle endings |
| | Longest Sessions | Top 10 sessions by message count |

## API Endpoints

### Cost Analytics
| Endpoint | Description |
|----------|-------------|
| `GET /api/overview?days=30` | Totals, models, sources, active days, cost delta |
| `GET /api/daily?days=30` | Daily cost breakdown (fills gaps with $0) |
| `GET /api/models` | Per-model cost, sessions, tokens, cache reads/writes |
| `GET /api/sources` | Per-platform cost and session counts |
| `GET /api/sessions?limit=50&offset=0` | Paginated recent sessions |
| `GET /api/expensive?limit=20` | Most expensive sessions by cost |
| `GET /api/databases` | Discovered databases with counts |

### Efficiency & Bottlenecks
| Endpoint | Description |
|----------|-------------|
| `GET /api/efficiency` | Cost-per-session analysis, stuck sessions, cache efficiency metrics |
| `GET /api/bottlenecks` | Aggregate waste metrics, top waste models, stuck session count |

### Context Tracking
| Endpoint | Description |
|----------|-------------|
| `GET /api/context` | Compression events, message distribution, pressure by model, end reasons |

## How It Works

1. Prism scans `~/.hermes/state.db` + `~/.hermes/profiles/*/state.db`.
2. Queries the `sessions` table: tokens, costs, models, timestamps, tool usage, end reasons.
3. Computes aggregations (daily totals, per-model breakdowns, efficiency scores, context pressure).
4. Serves a multi-tab dashboard with Chart.js visualizations.
5. Every read is read-only — your Hermes database is never modified.
6. API responses are cached for 15 seconds to minimize disk I/O.

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

## Customizing Port & Host

```bash
# Custom port (default: 8081)
python server.py --port 3000

# Bind to specific host (default: 0.0.0.0)
python server.py --host 127.0.0.1

# Persistent port via environment variable
export PRISM_PORT=3000
python server.py
```

## Running on a Network

Prism binds to `0.0.0.0` by default, so any device on your local network can access it:

```
http://<your-ip>:8081
```

Useful for running on a server and accessing from phones or other computers.

## Contributing

PRs welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and development guidelines.

## Screenshots

> Coming soon — open the dashboard and take screenshots to showcase the three tab views!

## Changelog

### Unreleased
- Added `/api/efficiency` endpoint with cost-per-message and stuck session analysis
- Added `/api/bottlenecks` endpoint with aggregate waste metrics
- Added `/api/context` endpoint with compression/reset tracking and message distribution
- Added **Efficiency** tab with cache utilization charts and inefficient session tables
- Added **Context** tab with pressure analytics and session lifecycle charts
- Added tabbed navigation with lazy-loaded data
- Added 15-second in-memory caching on all API endpoints
- Fixed CORS headers on FastAPI validation error responses (422)
- Fixed `?days=9999` validation error
- Added `end_reason` to session data queries
- Added LICENSE (MIT), CONTRIBUTING.md

### 1.0.0
- Initial release: cost dashboard with 4 charts and 2 data tables
- Multi-profile database discovery
- Dark mode, responsive design
- `--port` and `--host` CLI arguments
- XSS-safe HTML escaping

## License

MIT — use it, modify it, share it.

## Author

Built by [Caido](https://github.com/caido)
