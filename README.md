# Screener-cloud
Cloud-based NSE screener with Vercel + GitHub Actions

## Running ARGUS

Set a strong, randomly generated `ARGUS_ACCESS_KEY` in the frontend deployment environment alongside the existing `GITHUB_TOKEN` and repository setting, then redeploy. Enter the key in the dashboard to run scans, edit scheduled presets, and view scan reports. Keep the key in the server environment. The GitHub token needs contents read/write and Actions read for this repository. Saving presets writes to `main`, so the deployment token must be allowed to update the preset file.

### Scan rules and scheduled settings

- Both strategies count the latest N candles at the selected timeframe. Breakout anchors at the highest high in that window, and pullback anchors at the lowest eligible low after applying the minimum anchor age. Breakout tolerance and ceiling are entered as percentages in the dashboard and converted to the existing decimal representation.
- Daily scans request extra calendar history to obtain enough trading candles. Each strategy skips a lookback when the stock has fewer candles than requested and reports insufficient history.
- The two weekday NSE jobs start at 5:00 a.m. IST (daily) and 5:15 a.m. IST (weekly). Each downloads history once and evaluates both strategies, with separate CSVs and Telegram messages. Pullbacks move earlier from their previous 5:45 and 6:00 starts. GitHub may queue a job after its scheduled time.
- In the dashboard, choose NSE and daily or weekly, then open **Scheduled NSE settings**. Load the default or the dated override into the form, edit the fields, and save as the recurring default or for a particular weekday (IST). A dated override applies only on that date. Saving after that morning’s scan has started won’t rerun it.
- Telegram uses the original breakout and pullback summaries and includes the scan ID for ticker lookup.

### Stock lists and scan reports

The **Refresh stock lists** workflow runs at 1:30 a.m. IST on weekdays and can also be started in Actions. It uses NSE's equity segment, BSE's active equity directory and Nasdaq Trader's NASDAQ/NYSE directories. The NSE SME and ETF lists are separate and currently excluded. The US directories retain supported listed instrument types, including ETFs. The workflow records additions, removals and unsupported symbol formats. A failed refresh keeps that market's previous snapshot or the bundled list if no snapshot has succeeded.

Manual and scheduled reports are saved under `backend/results/runs/<scan ID>/`. The original dated CSV location is also maintained. The dashboard shows coverage and lets you look up a ticker against any new scan ID, including those printed in scheduled Telegram summaries. A pass in multiple periods stays visible in diagnostics even when identical anchors collapse to a single CSV row.

Scan reports, settings and ticker snapshots inherit the repository’s visibility. GitHub API access keys and bot credentials are environment secrets. Per-scan reports increase repository storage over time.
