import axios from 'axios';
import { requireScanAccess } from '../../lib/scan-access';
import type { NextApiRequest, NextApiResponse } from 'next';
import { getGitHubConfig } from '../../lib/github';
import { ScanSummary, scanFile, TickerDiagnostic, validScanId } from '../../lib/scan-results';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') return res.status(405).end();
  if (!requireScanAccess(req, res)) return;
  const { jobId, ticker } = req.query;
  if (!validScanId(jobId) || typeof ticker !== 'string' || !/^[a-z0-9.\-&:_]{1,40}$/i.test(ticker)) {
    return res.status(400).json({ error: 'Enter a scan ID and a ticker such as NSE:SBIN.' });
  }
  const { token, repo, error } = getGitHubConfig();
  if (!token || !repo || error) return res.status(503).json({ error });
  try {
    const meta = await scanFile(repo, token, jobId, 'summary.json');
    const summary: ScanSummary = JSON.parse(meta.data);
    const parts = ticker.toUpperCase().split(':');
    if (parts.length > 2 || (parts.length === 2 && parts[0] !== summary.market)) {
      return res.json({ diagnostic: { status: 'wrong_market' }, summary });
    }
    const bare = parts[parts.length - 1];
    if (!bare) return res.status(400).json({ error: 'Enter a ticker after the exchange prefix.' });
    const suffix = summary.market === 'NSE' ? '.NS' : summary.market === 'BSE' ? '.BO' : '';
    const symbol = bare.endsWith(suffix) ? bare : bare + suffix;
    let diagnostic: TickerDiagnostic | undefined;
    try {
      const bucket = await scanFile(repo, token, jobId, `tickers-${symbol.charCodeAt(0)}.json`);
      const symbols = JSON.parse(bucket.data) as Record<string, TickerDiagnostic>;
      diagnostic = symbols[symbol] ?? symbols[symbol.replace('.', '-')];
    } catch (err) {
      if (!axios.isAxiosError(err) || err.response?.status !== 404) throw err;
    }
    return res.json({ diagnostic: diagnostic ?? { status: 'not_in_universe' }, summary });
  } catch (err) {
    const missing = axios.isAxiosError(err) && err.response?.status === 404;
    return res.status(missing ? 404 : 502).json({
      error: missing ? 'Scan report is unavailable for that ID.' : 'Could not load the scan report. Try again.',
    });
  }
}
