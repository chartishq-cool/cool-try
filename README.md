# Screener-cloud
Cloud-based NSE screener with Vercel + GitHub Actions

## Running ARGUS

Set a strong, randomly generated `ARGUS_ACCESS_KEY` in the frontend deployment environment alongside the existing `GITHUB_TOKEN` and repository setting, then redeploy. Enter the key in the dashboard to run scans, edit scheduled presets, and view scan reports. Keep the key in the server environment. The GitHub token needs contents read/write and Actions read for this repository. Saving presets writes to `main`, so the deployment token must be allowed to update the preset file.

### Scan rules and scheduled settings

- Breakout lookbacks use calendar days, weeks, or months. Pullback lookbacks count candles. Breakout tolerance and ceiling are entered as percentages in the dashboard and converted to the existing decimal representation.
- Daily pullbacks request more history to cover long candle lookbacks. Newly listed or thinly traded stocks can still have fewer candles. Their reports show when a lookback used shorter history. The existing pullback eligibility calculation still runs on the available candles.
- The two weekday NSE jobs start at 5:00 a.m. IST (daily) and 5:15 a.m. IST (weekly). Each downloads history once and evaluates both strategies, with separate CSVs and Telegram messages. Pullbacks move earlier from their previous 5:45 and 6:00 starts. GitHub may queue a job after its scheduled time.
- In the dashboard, choose NSE and daily or weekly, then open **Scheduled NSE settings**. Load the default or the dated override into the form, edit the fields, and save as the recurring default or for a particular weekday (IST). A dated override applies only on that date. Saving after that morning’s scan has started won’t rerun it.
- The Telegram summary has the scan ID and all matching anchor periods. The following plain-text messages contain just comma-separated TradingView tickers. Paste each message as a separate batch if the list spans multiple messages.

### Stock lists and scan reports

The **Refresh stock lists** workflow runs at 1:30 a.m. IST on weekdays and can also be started in Actions. It uses NSE's equity segment, BSE's active equity directory and Nasdaq Trader's NASDAQ/NYSE directories. The NSE SME and ETF lists are separate and currently excluded. The US directories retain supported listed instrument types, including ETFs. The workflow records additions, removals and unsupported symbol formats. A failed refresh keeps that market's previous snapshot or the bundled list if no snapshot has succeeded.

Manual and scheduled reports are saved under `backend/results/runs/<scan ID>/`. The original dated CSV location is also maintained. The dashboard shows coverage and lets you look up a ticker against any new scan ID, including those printed in scheduled Telegram summaries. A pass in multiple periods stays visible in diagnostics and Telegram even when identical anchors collapse to a single row in the existing CSV format.

Scan reports, settings and ticker snapshots inherit the repository’s visibility. GitHub API access keys and bot credentials are environment secrets. Per-scan reports increase repository storage over time.
