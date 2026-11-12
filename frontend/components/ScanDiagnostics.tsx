import { FormEvent, useState } from 'react';
import axios from 'axios';
import type { ScanSummary, TickerDiagnostic } from '../lib/scan-results';

const labels: Record<string, string> = {
  passed: 'Matched',
  not_in_universe: 'Ticker was outside this scan’s stock list',
  wrong_market: 'Ticker belongs to a different market',
  no_data: 'Yahoo returned no usable price data',
  fetch_error: 'Price download failed',
  rate_limited: 'Price download may have been throttled',
  insufficient_history: 'Insufficient history for this lookback',
  anchor_age_excludes_window: 'Minimum anchor age excludes the entire lookback',
  no_post_anchor_data: 'No candle after the anchor',
  avwap_unavailable: 'AVWAP unavailable',
  calculation_error: 'Could not evaluate this lookback',
  no_sustained_breakout: 'No breakout met the sustain and tolerance rules',
  failed_attempts: 'Too many failed attempts',
  turnover: 'Turnover below minimum',
  outside_ceiling: 'Latest close outside the breakout range',
  crosses: 'Too many separate stretches below AVWAP',
  outside_proximity: 'Latest close outside the pullback band',
};
const fmt = (value?: number | null) => typeof value === 'number' ? value.toLocaleString('en-IN', { maximumFractionDigits: 4 }) : '—';
const button = { margin: '4px 8px 4px 0', padding: '6px 10px', cursor: 'pointer' };
const field = { margin: '4px 8px 4px 0', padding: '6px', maxWidth: '100%' };

export function Coverage({ summary }: { summary: ScanSummary }) {
  const { coverage, universe, settings } = summary;
  return (
    <div style={{ margin: '10px 0', lineHeight: 1.6 }}>
      <div>{coverage.evaluated} of {coverage.requested} tickers evaluated · {coverage.skipped} skipped</div>
      {(coverage.skipped > 0 || coverage.incomplete_checks > 0) &&
        <div>Partial coverage · {coverage.incomplete_checks} evaluated tickers had incomplete lookbacks.</div>}
      <details>
        <summary>Settings used and stock list changes</summary>
        <ul>
          {Object.entries(settings).map(([key, value]) => (
            <li key={key}>{key.replace(/_/g, ' ')}{' '}
              {Array.isArray(value) ? value.join(', ') :
                (key === 'ceiling' || key === 'tolerance_below_avwap') && typeof value === 'number'
                  ? `${fmt(value * 100)}%` : value}</li>
          ))}
        </ul>
        <div>{universe.refreshed_at ? `Exchange list refreshed ${universe.refreshed_at}` : 'Using the bundled stock list'}</div>
        <div style={{ overflowWrap: 'anywhere' }}>
          {(['added', 'removed', 'unmapped'] as const).map((key) => universe[key]?.length ? (
            <details key={key}><summary>{universe[key]?.length} {key}</summary>{universe[key]?.join(', ')}</details>
          ) : null)}
        </div>
      </details>
    </div>
  );
}

export default function ScanDiagnostics({ initialId, accessKey }: { initialId?: string; accessKey: string }) {
  const [id, setId] = useState(initialId ?? '');
  const [ticker, setTicker] = useState('');
  const [result, setResult] = useState<{ diagnostic: TickerDiagnostic; summary: ScanSummary }>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function lookup(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setResult(undefined);
    try {
      const response = await axios.get('/api/ticker-check', {
        params: { jobId: id.trim(), ticker: ticker.trim() }, headers: { 'x-argus-key': accessKey },
      });
      setResult(response.data);
    } catch (err) {
      setError(axios.isAxiosError(err) ? err.response?.data?.error ?? 'Could not load the report.' : 'Could not load the report.');
    } finally {
      setLoading(false);
    }
  }

  const diagnostic = result?.diagnostic;
  const settings = result?.summary.settings;
  const isPullback = settings && 'proximity_low_pct' in settings;
  const units = isPullback ? 'bars' : result?.summary.timeframe === 'daily' ? 'calendar days'
    : result?.summary.timeframe === 'weekly' ? 'calendar weeks' : 'calendar months';
  const currency = result && ['NYSE', 'NASDAQ'].includes(result.summary.market) ? 'USD' : 'INR';
  return (
    <section style={{ padding: '12px 0', lineHeight: 1.5 }}>
      <h2>Why did this stock miss?</h2>
      <form onSubmit={lookup}>
        <label>Scan ID <input required style={field} value={id} onChange={(e) => { setId(e.target.value); setResult(undefined); }} /></label>
        <label>Ticker <input required style={field} value={ticker} placeholder="NSE:SBIN" onChange={(e) => { setTicker(e.target.value); setResult(undefined); }} /></label>
        <button style={button} disabled={loading}>{loading ? 'Checking…' : 'Check ticker'}</button>
      </form>
      <p>Use the scan ID from your results or Telegram summary.</p>
      {error && <p role="alert">{error}</p>}
      {diagnostic && settings && result && (
        <div aria-live="polite">
          {diagnostic.status !== 'evaluated' ? <p>{labels[diagnostic.status] ?? diagnostic.status}</p> : (
            <>
              <p>{diagnostic.bars} candles available. Each row shows the first rule that blocked the match.</p>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ minWidth: '580px', width: '100%', textAlign: 'left' }}>
                  <thead><tr><th>Lookback</th><th>Outcome</th><th>Price / AVWAP</th><th>Turnover ({currency})</th><th>{isPullback ? 'Crosses' : 'Failed attempts'}</th></tr></thead>
                  <tbody>{Object.entries(diagnostic.periods ?? {}).map(([period, check]) => (
                    <tr key={period}>
                      <td>{period} {units}{check.history_short && ' (short history)'}</td>
                      <td>{labels[check.status] ?? check.status}{check.anchor && <div>Anchor {check.anchor}</div>}
                        {check.status === 'no_sustained_breakout' && typeof check.crossings === 'number' &&
                          <small>{check.crossings} crossings · {check.sustain_failures} failed sustain · {check.tolerance_failures} failed tolerance · {check.pending_crossings} too recent</small>}
                      </td>
                      <td>{fmt(check.close)} / {fmt(check.avwap)}
                        {typeof check.distance_pct === 'number' && <div>{fmt(check.distance_pct)}%</div>}</td>
                      <td>{fmt(check.turnover)} <small>min {fmt(Number(settings.min_turnover))}</small></td>
                      <td>{fmt(isPullback ? check.crosses : check.failed_attempts)} <small>max {fmt(Number(isPullback ? settings.max_brief_crosses : settings.max_failed_attempts))}</small></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <p>{isPullback
                ? `Range ${settings.proximity_low_pct}% to ${settings.proximity_high_pct}% · Minimum anchor age ${settings.min_periods_old} candles`
                : `Sustain ${settings.sustain_periods} candles · Tolerance ${fmt(Number(settings.tolerance_below_avwap) * 100)}% · Latest close above AVWAP and within ${fmt(Number(settings.ceiling) * 100)}%`}</p>
            </>
          )}
          <Coverage summary={result.summary} />
        </div>
      )}
    </section>
  );
}
