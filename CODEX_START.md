# Run this project in Codex Cloud

1. Create a separate `tradeAssist-ai` GitHub repository and upload this directory to its root, or use an isolated `tradeassist-ai` branch on your existing GitHub account as an interim staging location. **Do not overwrite the old `Ngx_trading_bot` main branch.**
2. Open Codex (via ChatGPT's Codex view or https://chatgpt.com/codex) on the web or desktop.
3. Create and publish a Codex Cloud environment connected to the new repository. Set up Python 3.11 or 3.12 and a setup command:

       python -m pip install -r requirements-dev.txt

4. Once the environment exists, start a Codex task using the prompt below. Cloud task setup may depend on your ChatGPT plan/workspace permissions.
5. Alternatively, use Codex in VS Code with this project folder open. Tests run there with the same command.

## Suggested first task for Codex

Inspect this TradeAssist AI Python/Streamlit prototype and follow AGENTS.md. Install dependencies, run `python -m pytest -q`, and run `python -m compileall -q app.py ngxintel tests`. Fix any failures without introducing network-dependent tests. Add tests for source data validation, prediction evaluation edge cases, and backtest lookahead/session boundaries. Check that the app can at least start headlessly using Streamlit and report that separately from a full UI test. Do not place broker orders or claim synthetic data reflects actual NGX performance. Summarize code changes, exact test results, remaining risks, and next work items in a pull request.

## Test commands

    python -m pip install -r requirements-dev.txt
    python -m pytest -q
    python -m compileall -q app.py ngxintel tests

A GitHub Actions configuration in `.github/workflows/tests.yml` runs tests for pull requests and pushes to `main` automatically once uploaded to GitHub.

No API keys are required for the unit tests or the synthetic demo. Live provider integration needs a real API key and separate verification; it is not proven by mocked tests.
