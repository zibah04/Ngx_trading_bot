# TradeAssist AI — one-stop resource directory

The **single-download ZIP** includes the full project source, tests, dashboard, starter launcher, dependency manifests, development setup, and Codex handoff. External market prices, proprietary feeds, and API keys are **not** bundled. Those require credentials and appropriate licences; data should not be mass-downloaded or re-distributed without permission.

## Install/run resources

| Resource | Link | What you need to do |
|---|---|---|
| Python (3.11 or 3.12 recommended) | https://www.python.org/downloads/ | Install once on Windows; tick add Python to PATH where appropriate |
| Git | https://git-scm.com/downloads | Optional if using Codex Cloud; helpful for local Git |
| VS Code | https://code.visualstudio.com/download | Optional editor |
| Codex Cloud | https://chatgpt.com/codex | Connect repository and create/publish an environment |
| GitHub | https://github.com/new | Create a distinct `tradeAssist-ai` repository; upload **contents** of ZIP |
| Streamlit docs | https://docs.streamlit.io/ | Dashboard framework; installed automatically by starter |

## Data and research sources

| Source | Link | Access and usage warning |
|---|---|---|
| Investo API | https://investo.ng/developers | Free personal/evaluation tier advertised; key is issued manually. EOD not live bid/ask; provider terms apply. Supported optional app route. |
| Investo API terms | https://investo.ng/api-terms | No automatic licence to redistribute or permanently mirror raw NGX data. |
| Kobo Terminal API | https://koboterminal.com/api | Free tier delayed quotes; historical data and disclosures have paid tier. Not currently implemented in app. |
| NGX X-DataPortal | https://ngxgroup.com/exchange/data/x-dataportal/ | Downloadable official paid and limited free data; rights and account conditions apply. |
| NGX historical data | https://ngxgroup.com/exchange/data/historical-data/ | Purchasable historical datasets; university-student discount advertised, check eligibility. |
| NGX company disclosures | https://ngxgroup.com/exchange/data/corporate-disclosures/ | First-party corporate news/earnings; validate publication timestamps and terms. |
| Central Bank of Nigeria | https://www.cbn.gov.ng/ | Monetary policy, rates, regulatory releases. |
| National Bureau of Statistics | https://www.nigerianstat.gov.ng/ | Economic indicators, CPI and official releases. |
| BusinessDay | https://businessday.ng/ | Secondary financial reporting; not a bulk republication feed. |
| Nairametrics | https://nairametrics.com/ | Secondary reporting; do not assume reusable article full text. |

## One-step setup from the ZIP

Extract the ZIP, install Python if needed, then double-click **`RUN_ON_WINDOWS.bat`**. It creates a local virtual environment, installs Python dependencies with pip, and launches Streamlit at `http://localhost:8501`. Internet is needed for the first install. API access is optional for the synthetic demo, but required for real Investo prices.

For Codex Cloud, connect a repository and use `python -m pip install -r requirements-dev.txt` as the environment setup command. Tests do not use real market data.

**Licensing and safety:** Market feeds may be delayed or paid. The current project makes research signals, not live orders. No guaranteed accuracy or profit.
