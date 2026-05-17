# Contributing to Prism

Thank you for your interest in contributing! Prism is an open-source AI cost dashboard for Hermes Agent. Here's how to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/SlothDev007/prism.git
cd prism

# Install dependencies
pip install fastapi uvicorn

# Run the server
python server.py
```

The dashboard will be available at `http://localhost:8081`.

## Architecture

Prism is intentionally minimal:

- **`server.py`** — FastAPI backend with SQLite reads from Hermes `state.db`
- **`static/index.html`** — Single-page frontend with Chart.js, vanilla JS, and CSS
- **`requirements.txt`** — Pinned dependencies
- **`.gitignore`** — Standard Python exclusions

No build tools, no bundlers, no npm. Just Python and a browser.

## Adding Features

### New API Endpoint

Add a new function in `server.py` with the `@app.get()` decorator:

```python
@app.get("/api/my-feature")
def my_feature():
    def _compute():
        sessions = _fetch_all_sessions()
        # ... your logic
        return {"data": ...}
    return _get_cached_or_fetch("my-feature-key", _compute)
```

**Important:** Wrap your computation in `_get_cached_or_fetch(key, _compute)` to benefit from the 15-second TTL cache.

### Frontend Changes

Modify `static/index.html`. No build step needed — changes are served immediately on refresh.

If adding a new tab, follow this pattern:
1. Add a tab button in the `<nav>` section
2. Add a `<div class="tab-content" id="tabName">` section
3. Add JavaScript to fetch API data and render charts/tables on tab click
4. Use lazy loading: only fetch data when the tab is first visited
5. Call `redrawAllCharts()` when theme toggles to update your charts

### Charts

All charts use Chart.js v4 (loaded via CDN). Use the existing `safeDestroy(key)` helper to clean up charts before redrawing (required for theme toggle to work properly).

## Code Style

- Python: Follow PEP 8, type hints where practical
- JavaScript: Vanilla JS (ES5-compatible), no frameworks
- HTML/CSS: Self-contained in `index.html`, CSS variables for theming

## Testing

Since there are no automated tests, verify manually:

1. Run `python server.py`
2. Open `http://localhost:8081`
3. Verify each tab renders and loads data
4. Toggle dark mode — all charts should update
5. Test with `--port` to confirm CLI args work
6. Verify `days` and `limit` query params work correctly

## Pull Requests

- One feature per PR
- Update the Changelog section in README.md
- Include `?days=9999` validation (FastAPI constraint allows up to 9999)
- No new dependencies without justification

## License

By contributing, you agree your contributions are under the MIT License.
