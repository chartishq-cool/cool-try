import { useState, CSSProperties, useEffect, useRef } from 'react';
import axios from 'axios';
import ScanDiagnostics, { Coverage } from '../components/ScanDiagnostics';
import type { ScanSummary } from '../lib/scan-results';

interface ScanResults {
  jobId?: string;
  summary?: ScanSummary;
  total: number;
  pure?: number;
  retry?: number;
  symbols: string[];
  csvFile?: string;
  downloadUrl?: string;
}

// ─── Design tokens ────────────────────────────────────────────────────────────
const C = {
  bgVoid:       '#060A0D',
  bgBase:       '#0B1014',
  bgSurface:    '#0F161B',
  bgRaised:     '#141D23',
  bgElevated:   '#1A2530',
  borderDim:    '#1C2A33',
  borderStd:    '#213040',
  borderAccent: 'rgba(0, 255, 136, 0.35)',
  green:        '#00FF88',
  greenDim:     '#00CC6A',
  greenMuted:   'rgba(0, 255, 136, 0.12)',
  greenGlow:    'rgba(0, 255, 136, 0.18)',
  greenGlowLg:  'rgba(0, 255, 136, 0.08)',
  textPrimary:  '#D8EEE2',
  textSecondary:'#6B8F7A',
  textMuted:    '#334D3E',
  textLabel:    '#4A7060',
  red:          '#FF4466',
  redBg:        'rgba(255, 68, 102, 0.08)',
  redBorder:    'rgba(255, 68, 102, 0.25)',
  fontDisplay:  "'Syne', sans-serif",
  fontMono:     "'Space Mono', monospace",
};

// ─── Dynamic anchor defaults per timeframe ───────────────────────────────────
const DEFAULT_ANCHORS: Record<string, string> = {
  daily:   '180,365,550,730,900',
  weekly:  '52,104,156,208,260',
  monthly: '12,36,60,84,120',
};

const styles: Record<string, CSSProperties> = {

  // ── Root: full viewport, no outer scroll ───────────────────────────────────
  page: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    backgroundColor: C.bgVoid,
    color: C.textPrimary,
    fontFamily: C.fontMono,
  },

  // ── Top bar ────────────────────────────────────────────────────────────────
  topbar: {
    borderBottom: `1px solid ${C.borderDim}`,
    backgroundColor: C.bgBase,
    padding: '0 28px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    height: '48px',
    flexShrink: 0,
    zIndex: 100,
    backdropFilter: 'blur(12px)',
  },
  topbarLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  logoMark: {
    width: '24px',
    height: '24px',
    border: `1.5px solid ${C.green}`,
    borderRadius: '4px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: `0 0 10px ${C.greenGlow}`,
    flexShrink: 0,
  },
  logoText: {
    fontFamily: C.fontDisplay,
    fontWeight: 800,
    fontSize: '15px',
    letterSpacing: '-0.04em',
    color: C.textPrimary,
  },
  logoSub: {
    fontFamily: C.fontMono,
    fontSize: '9px',
    letterSpacing: '0.18em',
    color: C.textMuted,
    textTransform: 'uppercase' as const,
    marginTop: '1px',
  },
  topbarRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    fontSize: '10px',
    letterSpacing: '0.1em',
    color: C.textMuted,
    textTransform: 'uppercase' as const,
  },
  statusDot: {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    backgroundColor: C.green,
    boxShadow: `0 0 6px ${C.green}`,
    flexShrink: 0,
  },

  // ── Params bar: fixed, never scrolls ──────────────────────────────────────
  paramsBar: {
    flexShrink: 0,
    backgroundColor: C.bgBase,
    borderBottom: `1px solid ${C.borderDim}`,
    padding: '0 28px',
  },

  // Row 1: market / logic / timeframe / anchor / turnover / run
  paramsRow1: {
    display: 'flex',
    alignItems: 'center',
    height: '62px',
    width: '100%',
  },

  // Row 2: logic-specific params
  paramsRow2: {
    display: 'flex',
    alignItems: 'center',
    height: '46px',
    borderTop: `1px solid ${C.borderDim}`,
    gap: '0',
  },

  paramGroup: {
    display: 'flex',
    flexDirection: 'column' as const,
    justifyContent: 'center',
    gap: '4px',
    padding: '0 18px',
    flexShrink: 0,
  },

  paramDivider: {
    width: '1px',
    alignSelf: 'stretch',
    margin: '10px 0',
    backgroundColor: C.borderDim,
    flexShrink: 0,
  },

  paramLabel: {
    fontSize: '9px',
    fontWeight: 700,
    letterSpacing: '0.14em',
    color: C.textMuted,
    textTransform: 'uppercase' as const,
    fontFamily: C.fontMono,
    whiteSpace: 'nowrap' as const,
  },

  // ── Inline segment control ─────────────────────────────────────────────────
  segInline: {
    display: 'flex',
    alignItems: 'center',
    gap: '2px',
    backgroundColor: C.bgRaised,
    border: `1px solid ${C.borderDim}`,
    borderRadius: '5px',
    padding: '2px',
  },

  segBtn: {
    padding: '4px 10px',
    border: 'none',
    borderRadius: '3px',
    backgroundColor: 'transparent',
    color: C.textSecondary,
    fontSize: '11px',
    fontFamily: C.fontMono,
    fontWeight: 700,
    letterSpacing: '0.06em',
    cursor: 'pointer',
    transition: 'all 150ms ease',
    whiteSpace: 'nowrap' as const,
  },
  segBtnActive: {
    backgroundColor: C.bgElevated,
    color: C.green,
    boxShadow: `inset 0 0 0 1px ${C.borderAccent}`,
  },
  segBtnDisabled: {
    opacity: 0.28,
    cursor: 'not-allowed',
  },

  // ── Inline inputs ──────────────────────────────────────────────────────────
  inputInline: {
    padding: '4px 10px',
    backgroundColor: C.bgRaised,
    border: `1px solid ${C.borderStd}`,
    borderRadius: '5px',
    color: C.textPrimary,
    fontSize: '12px',
    fontFamily: C.fontMono,
    outline: 'none',
    width: '170px',
    transition: 'border-color 150ms ease, box-shadow 150ms ease',
    boxSizing: 'border-box' as const,
    height: '26px',
  },
  inputInlineNarrow: {
    width: '108px',
  },

  // ── Run button inside params bar ───────────────────────────────────────────
  runButtonBar: {
    padding: '7px 22px',
    backgroundColor: C.green,
    color: C.bgVoid,
    border: 'none',
    borderRadius: '5px',
    fontSize: '11px',
    fontFamily: C.fontMono,
    fontWeight: 700,
    letterSpacing: '0.12em',
    textTransform: 'uppercase' as const,
    cursor: 'pointer',
    boxShadow: `0 0 18px ${C.greenGlow}`,
    transition: 'all 150ms ease',
    whiteSpace: 'nowrap' as const,
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    gap: '7px',
    height: '30px',
  },
  runButtonBarLoading: {
    backgroundColor: C.bgElevated,
    color: C.green,
    boxShadow: `inset 0 0 0 1px ${C.borderAccent}`,
    cursor: 'default',
  },

  // ── Results pane: scrollable, takes remaining height ──────────────────────
  resultsPane: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '24px 28px',
  },
  resultsPaneInner: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '16px',
    maxWidth: '1100px',
  },

  // ── Panel (card style used in results) ────────────────────────────────────
  panel: {
    backgroundColor: C.bgSurface,
    border: `1px solid ${C.borderDim}`,
    borderRadius: '8px',
    overflow: 'hidden',
  },
  panelHeader: {
    padding: '12px 20px',
    borderBottom: `1px solid ${C.borderDim}`,
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    backgroundColor: C.bgRaised,
  },
  panelHeaderDot: {
    width: '7px',
    height: '7px',
    borderRadius: '50%',
    backgroundColor: C.green,
    boxShadow: `0 0 8px ${C.greenGlow}`,
    flexShrink: 0,
  },
  panelTitle: {
    fontFamily: C.fontDisplay,
    fontWeight: 700,
    fontSize: '12px',
    letterSpacing: '0.04em',
    color: C.textPrimary,
    textTransform: 'uppercase' as const,
  },

  // ── Idle ──────────────────────────────────────────────────────────────────
  idleCard: {
    backgroundColor: C.bgSurface,
    border: `1px solid ${C.borderDim}`,
    borderRadius: '8px',
    padding: '60px 36px',
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    gap: '14px',
    textAlign: 'center' as const,
  },
  idleIcon: {
    width: '42px',
    height: '42px',
    border: `1px solid ${C.borderStd}`,
    borderRadius: '8px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: C.textMuted,
    fontSize: '18px',
    marginBottom: '4px',
  },
  idleTitle: {
    fontFamily: C.fontDisplay,
    fontWeight: 700,
    fontSize: '14px',
    color: C.textSecondary,
  },
  idleSub: {
    fontSize: '11px',
    color: C.textMuted,
    letterSpacing: '0.04em',
    maxWidth: '300px',
    lineHeight: '1.7',
  },

  // ── Loading ───────────────────────────────────────────────────────────────
  loadingCard: {
    backgroundColor: C.bgSurface,
    border: `1px solid ${C.borderAccent}`,
    borderRadius: '8px',
    padding: '36px',
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    gap: '16px',
    boxShadow: `0 0 30px ${C.greenGlowLg}`,
  },
  loadingLabel: {
    fontFamily: C.fontMono,
    fontSize: '11px',
    letterSpacing: '0.14em',
    color: C.green,
    textTransform: 'uppercase' as const,
  },
  loadingBar: {
    width: '100%',
    height: '2px',
    backgroundColor: C.bgElevated,
    borderRadius: '2px',
    overflow: 'hidden',
    position: 'relative' as const,
  },
  loadingBarFill: {
    position: 'absolute' as const,
    top: 0,
    left: '-40%',
    width: '40%',
    height: '100%',
    background: `linear-gradient(90deg, transparent, ${C.green}, transparent)`,
    animation: 'scan 1.6s ease-in-out infinite',
    boxShadow: `0 0 8px ${C.green}`,
  },
  loadingTime: {
    fontFamily: C.fontMono,
    fontSize: '28px',
    fontWeight: 700,
    color: C.green,
    letterSpacing: '-0.02em',
    fontVariantNumeric: 'tabular-nums',
  },
  loadingTimeSub: {
    fontSize: '10px',
    color: C.textMuted,
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    marginTop: '-10px',
  },

  // ── Error ──────────────────────────────────────────────────────────────────
  errorCard: {
    backgroundColor: C.redBg,
    border: `1px solid ${C.redBorder}`,
    borderRadius: '8px',
    padding: '18px 20px',
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
  },
  errorIcon: {
    color: C.red,
    fontSize: '14px',
    flexShrink: 0,
    marginTop: '1px',
    letterSpacing: 0,
  },
  errorText: {
    fontSize: '12px',
    color: C.red,
    lineHeight: '1.6',
    fontFamily: C.fontMono,
  },

  // ── Results stats ──────────────────────────────────────────────────────────
  statsRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: '10px',
  },
  statCard: {
    backgroundColor: C.bgRaised,
    border: `1px solid ${C.borderDim}`,
    borderRadius: '6px',
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '4px',
  },
  statLabel: {
    fontSize: '10px',
    fontWeight: 700,
    letterSpacing: '0.1em',
    color: C.textMuted,
    textTransform: 'uppercase' as const,
  },
  statValue: {
    fontFamily: C.fontMono,
    fontSize: '26px',
    fontWeight: 700,
    color: C.green,
    letterSpacing: '-0.03em',
    fontVariantNumeric: 'tabular-nums',
    lineHeight: 1.1,
  },
  statValueNeutral: {
    color: C.textPrimary,
  },

  // ── Symbols panel ──────────────────────────────────────────────────────────
  symbolsHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 20px',
    borderBottom: `1px solid ${C.borderDim}`,
    backgroundColor: C.bgRaised,
  },
  symbolsHeaderLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  symbolsBadge: {
    backgroundColor: C.greenMuted,
    border: `1px solid ${C.borderAccent}`,
    borderRadius: '4px',
    padding: '2px 8px',
    fontSize: '11px',
    fontFamily: C.fontMono,
    fontWeight: 700,
    color: C.green,
    letterSpacing: '0.04em',
  },
  symbolsTextarea: {
    width: '100%',
    minHeight: '110px',
    padding: '14px 16px',
    backgroundColor: C.bgVoid,
    border: 'none',
    borderBottom: `1px solid ${C.borderDim}`,
    color: C.green,
    fontFamily: C.fontMono,
    fontSize: '12px',
    lineHeight: '1.8',
    resize: 'none' as const,
    outline: 'none',
    letterSpacing: '0.03em',
  },
  symbolsActions: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
  },
  actionButton: {
    padding: '11px 16px',
    backgroundColor: 'transparent',
    border: 'none',
    color: C.textSecondary,
    fontSize: '11px',
    fontFamily: C.fontMono,
    fontWeight: 700,
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    transition: 'all 150ms ease',
    borderTop: `1px solid ${C.borderDim}`,
  },
  actionButtonLeft: {
    borderRight: `1px solid ${C.borderDim}`,
  },
  noResults: {
    padding: '32px 20px',
    textAlign: 'center' as const,
    fontSize: '12px',
    color: C.textMuted,
    letterSpacing: '0.06em',
  },
};

// ─── Inline segment button ────────────────────────────────────────────────────
function SegBtn({
  label, value, current, onClick, disabled = false,
}: {
  label: string; value: string; current: string;
  onClick: (v: string) => void; disabled?: boolean;
}) {
  const isActive = value === current;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => !disabled && onClick(value)}
      style={{
        ...styles.segBtn,
        ...(isActive ? styles.segBtnActive : {}),
        ...(disabled ? styles.segBtnDisabled : {}),
      }}
      onMouseEnter={e => {
        if (!isActive && !disabled)
          (e.currentTarget as HTMLButtonElement).style.color = C.textPrimary;
      }}
      onMouseLeave={e => {
        if (!isActive && !disabled)
          (e.currentTarget as HTMLButtonElement).style.color = C.textSecondary;
      }}
    >
      {label}
    </button>
  );
}

// ─── Inline input with focus glow ─────────────────────────────────────────────
function ParamInput({
  label, value, onChange, type = 'text', step, placeholder, narrow,
}: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; step?: string; placeholder?: string; narrow?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div style={styles.paramGroup}>
      <span style={styles.paramLabel}>{label}</span>
      <input
        type={type}
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          ...styles.inputInline,
          ...(narrow ? styles.inputInlineNarrow : {}),
          borderColor: focused ? C.borderAccent : C.borderStd,
          boxShadow: focused ? `0 0 0 3px ${C.greenGlowLg}` : 'none',
        }}
      />
    </div>
  );
}

// ─── Persistence helpers ──────────────────────────────────────────────────────
const STORAGE_KEY = 'argus_last_scan';

function saveLastScan(scanResults: ScanResults, scanMarket: string, scanLogic: string, scanTimeframe: string): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ results: scanResults, market: scanMarket, logic: scanLogic, timeframe: scanTimeframe })
    );
  } catch (_) {}
}

function loadLastScan(): { results: ScanResults; market: string; logic: string; timeframe: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Home() {
  // ── Form state (unchanged) ─────────────────────────────────────────────────
  const [market, setMarket]                           = useState('NSE');
  const [logic, setLogic]                             = useState('breakout');
  const [timeframe, setTimeframe]                     = useState('daily');
  const [anchorPeriods, setAnchorPeriods]             = useState(DEFAULT_ANCHORS['daily']);
  const [toleranceBelowAvwap, setToleranceBelowAvwap] = useState('3');
  const [ceiling, setCeiling]                         = useState('7');
  const [sustainPeriods, setSustainPeriods]           = useState('3');
  const [maxFailedAttempts, setMaxFailedAttempts]     = useState('0');
  const [minTurnover, setMinTurnover]                 = useState('5000000');
  const [proximityLowPct, setProximityLowPct]         = useState('0.0');
  const [proximityHighPct, setProximityHighPct]       = useState('2.0');
  const [maxBriefCrosses, setMaxBriefCrosses]         = useState('3');
  const [minPeriodsOld, setMinPeriodsOld]             = useState('20');

  // ── UI state (unchanged) ───────────────────────────────────────────────────
  const [accessKey, setAccessKey] = useState('');
  const [presetDate, setPresetDate] = useState('');
  const [presetStatus, setPresetStatus] = useState('');
  const [presetBusy, setPresetBusy] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (pollTimer.current) clearTimeout(pollTimer.current); }, []);
  const [loading, setLoading]     = useState(false);
  const [results, setResults]     = useState<ScanResults | null>(null);
  const [error, setError]         = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const [copied, setCopied]       = useState(false);
  const [elapsed, setElapsed]     = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

useEffect(() => {
    const saved = loadLastScan();
    if (saved) {
      setResults(saved.results);
      setMarket(saved.market);
      setLogic(saved.logic);
      setTimeframe(saved.timeframe);
    }
  }, []);

  useEffect(() => {
    if (loading) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loading]);

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}:${sec.toString().padStart(2, '0')}` : `${sec}s`;
  };

  // ── Scan logic (unchanged) ─────────────────────────────────────────────────
  const number = (value: string) => value.trim() === '' ? NaN : Number(value);
  const scanParams = () => {
    const base = { min_turnover: number(minTurnover), anchor_periods: anchorPeriods.split(',').map(number) };
    return logic === 'breakout' ? {
      ...base, tolerance_below_avwap: number(toleranceBelowAvwap) / 100, ceiling: number(ceiling) / 100,
      sustain_periods: number(sustainPeriods), max_failed_attempts: number(maxFailedAttempts),
    } : {
      ...base, proximity_low_pct: number(proximityLowPct), proximity_high_pct: number(proximityHighPct),
      max_brief_crosses: number(maxBriefCrosses), min_periods_old: number(minPeriodsOld),
    };
  };

  const presetAction = async (mode: 'load' | 'load-override' | 'default' | 'override' | 'clear') => {
    setPresetBusy(true);
    setPresetStatus('');
    const headers = { 'x-argus-key': accessKey };
    try {
      const url = '/api/schedule-presets';
      const reading = mode === 'load' || mode === 'load-override';
      const { data } = reading
        ? await axios.get(url, { params: { logic, timeframe }, headers })
        : await axios.put(url, { logic, timeframe, mode, date: presetDate, params: scanParams() }, { headers });
      if (reading) {
        if (mode === 'load-override' && !data.override) {
          setPresetStatus('No dated override is saved for this preset.');
          return;
        }
        const config = mode === 'load-override' ? { ...data.defaults, ...data.override.params } : data.defaults;
        setMinTurnover(String(config.min_turnover));
        setAnchorPeriods(config.anchor_periods.join(', '));
        if (logic === 'breakout') {
          setToleranceBelowAvwap(String(Number((config.tolerance_below_avwap * 100).toFixed(8))));
          setCeiling(String(Number((config.ceiling * 100).toFixed(8))));
          setSustainPeriods(String(config.sustain_periods));
          setMaxFailedAttempts(String(config.max_failed_attempts));
        } else {
          setProximityLowPct(String(config.proximity_low_pct));
          setProximityHighPct(String(config.proximity_high_pct));
          setMaxBriefCrosses(String(config.max_brief_crosses));
          setMinPeriodsOld(String(config.min_periods_old));
        }
        setPresetDate(data.override?.date ?? '');
      }
      const message = reading ? 'Preset loaded into the scan form.' :
        mode === 'clear' ? 'Dated override cleared.' : 'Scheduled settings saved.';
      setPresetStatus(message + (data.override ? ` Override date: ${data.override.date} IST.` : ''));
    } catch (err) {
      setPresetStatus(axios.isAxiosError(err) ? err.response?.data?.error ?? 'Could not update preset.' : 'Could not update preset.');
    } finally {
      setPresetBusy(false);
    }
  };

  const handleRunScan = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResults(null);
    setPollCount(0);

    try {
      const response = await axios.post('/api/trigger-scan', { market, logic, timeframe, params: scanParams() }, { headers: { 'x-argus-key': accessKey } });
      pollForResults(response.data.jobId);
    } catch (err: unknown) {
      setError(
        axios.isAxiosError(err)
          ? err.response?.data?.error || err.message
          : 'Error triggering scan'
      );
      setLoading(false);
    }
  };

  const pollForResults = (id: string) => {
    let count = 0;
    const deadline = Date.now() + 30 * 60 * 1000;
    const poll = async () => {
      setPollCount(++count);
      try {
        const { data } = await axios.get('/api/scan-status', {
          params: { jobId: id }, headers: { 'x-argus-key': accessKey },
        });
        if (data.status === 'completed') {
          const completed = { ...data.results, jobId: id, summary: data.summary, csvFile: data.csvFile, downloadUrl: data.downloadUrl };
          setResults(completed);
          saveLastScan(completed, market, logic, timeframe);
          setLoading(false);
          return;
        }
        if (data.status === 'failed') {
          setError(data.error || 'Scan failed');
          setLoading(false);
          return;
        }
      } catch (err) {
        if (axios.isAxiosError(err) && [400, 401, 404, 503].includes(err.response?.status ?? 0)) {
          setError(err.response?.data?.error ?? 'Could not check scan status.');
          setLoading(false);
          return;
        }
      }
      if (Date.now() >= deadline) {
        setError(`Stopped waiting for scan ${id}. Check the run in GitHub Actions.`);
        setLoading(false);
        return;
      }
      pollTimer.current = setTimeout(poll, 5000);
    };
    pollTimer.current = setTimeout(poll, 5000);
  };

  const copySymbols = (symbols: string[]) => {
    navigator.clipboard.writeText(symbols.join(', '));
    setCopied(true);
    setTimeout(() => setCopied(false), 2200);
  };

const downloadCsv = async (downloadUrl?: string, filename?: string) => {
    if (!downloadUrl) {
      alert('CSV not available yet. Check GitHub results folder.');
      return;
    }
    try {
      const res = await axios.get<string>(downloadUrl, {
        responseType: 'text',
        headers: downloadUrl.startsWith('/api/') ? { 'x-argus-key': accessKey } : undefined,
      });
      const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'scan_results.csv';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      alert('Download failed. Try opening the CSV link directly.');
    }
  };

  const availableTimeframes = ['daily', 'weekly', 'monthly'];

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={styles.page}>

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <header style={styles.topbar}>
        <div style={styles.topbarLeft}>
          <div style={styles.logoMark}>
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
              <path d="M2 7 L7 2 L12 7 L7 12 Z" stroke="#00FF88" strokeWidth="1.5" fill="none"/>
              <path d="M7 4.5 L9.5 7 L7 9.5 L4.5 7 Z" fill="#00FF88"/>
            </svg>
          </div>
          <div>
            <div style={styles.logoText}>ARGUS</div>
            <div style={styles.logoSub}>AVWAP Screener</div>
          </div>
        </div>
        <div style={styles.topbarRight}>
          <div style={styles.statusDot} />
          <span>System Online</span>
          <span style={{ color: C.borderStd, margin: '0 6px' }}>·</span>
          <span style={{ color: C.textMuted }}>
            {market} / {logic} / {timeframe}
          </span>
        </div>
      </header>

      {/* ── Params bar: fixed, no scroll ────────────────────────────────────── */}
      <div style={styles.paramsBar}>
        <form onSubmit={handleRunScan}>

          {/* Row 1: core selectors + shared params + run button */}
          <div style={styles.paramsRow1}>

            {/* Market */}
            <div style={{ ...styles.paramGroup, paddingLeft: 0 }}>
              <span style={styles.paramLabel}>Market</span>
              <div style={styles.segInline}>
                {['NSE', 'BSE', 'NASDAQ', 'NYSE'].map(m => (
                  <SegBtn key={m} label={m} value={m} current={market} onClick={v => {
                    setMarket(v);
                  }} />
                ))}
              </div>
            </div>

            <div style={styles.paramDivider} />

            {/* Logic */}
            <div style={styles.paramGroup}>
              <span style={styles.paramLabel}>Logic</span>
              <div style={styles.segInline}>
                <SegBtn label="Breakout" value="breakout" current={logic} onClick={setLogic} />
                <SegBtn label="Pullback" value="pullback" current={logic} onClick={setLogic} />
              </div>
            </div>

            <div style={styles.paramDivider} />

            {/* Timeframe */}
            <div style={styles.paramGroup}>
              <span style={styles.paramLabel}>Timeframe</span>
              <div style={styles.segInline}>
                {['daily', 'weekly', 'monthly'].map(tf => (
                  <SegBtn
                    key={tf}
                    label={tf.charAt(0).toUpperCase() + tf.slice(1)}
                    value={tf}
                    current={timeframe}
                    disabled={!availableTimeframes.includes(tf)}
                    onClick={v => {
                      setTimeframe(v);
                      if (DEFAULT_ANCHORS[v]) setAnchorPeriods(DEFAULT_ANCHORS[v]);
                    }}
                  />
                ))}
              </div>
            </div>

            <div style={styles.paramDivider} />

            {/* Anchor Periods */}
            <ParamInput
              label="Anchor Lookbacks (candles)"
              value={anchorPeriods}
              onChange={setAnchorPeriods}
              placeholder="e.g. 52,156,260"
            />

            <div style={styles.paramDivider} />

            {/* Min Turnover */}
            <ParamInput
              label={market === 'NSE' || market === 'BSE' ? 'Min Turnover (₹)' : 'Min Turnover (USD)'}
              value={minTurnover}
              onChange={setMinTurnover}
              type="number"
              narrow
            />

            {/* Run button — pushed to right edge */}
            <div style={{ marginLeft: 'auto', paddingLeft: '20px' }}>
              <button
                type="submit"
                disabled={loading || presetBusy}
                style={{
                  ...styles.runButtonBar,
                  ...(loading ? styles.runButtonBarLoading : {}),
                }}
                onMouseEnter={e => {
                  if (!loading) {
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 0 28px rgba(0,255,136,0.40)`;
                    (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)';
                  }
                }}
                onMouseLeave={e => {
                  if (!loading) {
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 0 18px ${C.greenGlow}`;
                    (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
                  }
                }}
              >
                {loading ? (
                  <>
                    <span style={{
                      display: 'inline-block', width: '7px', height: '7px',
                      borderRadius: '50%', backgroundColor: C.green,
                      animation: 'blink 1s ease infinite',
                    }} />
                    Scanning…
                  </>
                ) : (
                  <>▶ Run Scan</>
                )}
              </button>
            </div>
          </div>

          {/* Row 2: logic-specific params */}
          <div style={styles.paramsRow2}>
            {logic === 'breakout' ? (
              <>
                <ParamInput label="Tolerance Below AVWAP (%)" value={toleranceBelowAvwap} onChange={setToleranceBelowAvwap} type="number" step="0.01" narrow />
                <div style={styles.paramDivider} />
                <ParamInput label="Ceiling Above AVWAP (%)" value={ceiling} onChange={setCeiling} type="number" step="0.01" narrow />
                <div style={styles.paramDivider} />
                <ParamInput label="Sustain (candles)" value={sustainPeriods} onChange={setSustainPeriods} type="number" narrow />
                <div style={styles.paramDivider} />
                <ParamInput label="Max Failed Attempts" value={maxFailedAttempts} onChange={setMaxFailedAttempts} type="number" narrow />
              </>
            ) : (
              <>
                <ParamInput label="Proximity Low (%)" value={proximityLowPct} onChange={setProximityLowPct} type="number" step="0.1" narrow />
                <div style={styles.paramDivider} />
                <ParamInput label="Proximity High (%)" value={proximityHighPct} onChange={setProximityHighPct} type="number" step="0.1" narrow />
                <div style={styles.paramDivider} />
                <ParamInput label="Max Brief Crosses" value={maxBriefCrosses} onChange={setMaxBriefCrosses} type="number" narrow />
                <div style={styles.paramDivider} />
                <ParamInput label="Minimum Anchor Age (candles)" value={minPeriodsOld} onChange={setMinPeriodsOld} type="number" narrow />
              </>
            )}
          </div>

          <div style={styles.paramsRow2}>
            <label>ARGUS access key <input type="password" autoComplete="current-password" value={accessKey}
              onChange={(e) => setAccessKey(e.target.value)} disabled={loading || presetBusy} /></label>
            <small>{logic === 'breakout'
              ? 'Uses the latest N candles at the selected timeframe. Tolerance applies after the sustain candles.'
              : 'Uses the latest N candles at the selected timeframe. A cross counts one stretch below AVWAP.'} Turnover uses the latest candle.</small>
          </div>
        </form>
      </div>

      {/* ── Results pane: scrolls independently ─────────────────────────────── */}
      <main style={styles.resultsPane}>
        <div style={styles.resultsPaneInner}>
          {market === 'NSE' && timeframe !== 'monthly' && (
            <details style={{ margin: '12px 0' }}>
              <summary>Scheduled NSE settings · {timeframe} {logic}</summary>
              <p>Load the saved settings into the scan form, then edit the fields above. Save them as the recurring default or choose one weekday for an override.</p>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                <button type="button" disabled={loading || presetBusy} onClick={() => presetAction('load')}>Load default</button>
                <button type="button" disabled={loading || presetBusy} onClick={() => presetAction('default')}>Save as default</button>
                <label>Override date (IST) <input type="date" value={presetDate} onChange={(e) => setPresetDate(e.target.value)} /></label>
                <button type="button" disabled={loading || presetBusy || !presetDate} onClick={() => presetAction('override')}>Save dated override</button>
                <button type="button" disabled={loading || presetBusy} onClick={() => presetAction('load-override')}>Load override</button>
                <button type="button" disabled={loading || presetBusy} onClick={() => presetAction('clear')}>Clear override</button>
              </div>
              {presetStatus && <p role="status">{presetStatus}</p>}
            </details>
          )}
          {results?.jobId && <div>Scan ID <code>{results.jobId}</code></div>}
          {results?.summary && <Coverage summary={results.summary} />}
          <details style={{ margin: '12px 0' }}>
            <summary>Why did this stock miss?</summary>
            <ScanDiagnostics key={results?.jobId ?? 'lookup'} initialId={results?.jobId} accessKey={accessKey} />
          </details>

          {/* Error */}
          {error && (
            <div style={{ ...styles.errorCard, animation: 'fadeIn 0.3s ease' }}>
              <span style={styles.errorIcon}>✕</span>
              <div>
                <div style={{ ...styles.errorText, fontWeight: 700, marginBottom: '4px' }}>Scan Error</div>
                <div style={styles.errorText}>{error}</div>
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div style={{ ...styles.loadingCard, animation: 'fadeIn 0.3s ease' }}>
              <div style={styles.loadingLabel}>Scanning {market} · {logic} · {timeframe}</div>
              <div style={styles.loadingBar}>
                <div style={styles.loadingBarFill} />
              </div>
              <div style={styles.loadingTime}>{formatElapsed(elapsed)}</div>
              <div style={styles.loadingTimeSub}>elapsed — polling every 5s</div>
            </div>
          )}

          {/* Results */}
          {results && !loading && (
            <div style={{ animation: 'fadeIn 0.4s ease' }}>

              {/* Stats row */}
              <div style={{ ...styles.panel, marginBottom: '14px' }}>
                <div style={styles.panelHeader}>
                  <div style={styles.panelHeaderDot} />
                  <span style={styles.panelTitle}>Scan Complete</span>
                  <span style={{
                    marginLeft: 'auto',
                    fontSize: '10px',
                    color: C.textMuted,
                    fontFamily: C.fontMono,
                    letterSpacing: '0.08em',
                  }}>
                    {market} · {logic.toUpperCase()} · {timeframe.toUpperCase()}
                  </span>
                </div>
                <div style={{ ...styles.statsRow, padding: '14px' }}>
                  <div style={styles.statCard}>
                    <div style={styles.statLabel}>Total Matches</div>
                    <div style={styles.statValue}>{results.total}</div>
                  </div>
                  {results.pure !== undefined && (
                    <div style={styles.statCard}>
                      <div style={styles.statLabel}>Pure Breaks</div>
                      <div style={{ ...styles.statValue, ...styles.statValueNeutral }}>{results.pure}</div>
                    </div>
                  )}
                  {results.retry !== undefined && (
                    <div style={styles.statCard}>
                      <div style={styles.statLabel}>Retry Breaks</div>
                      <div style={{ ...styles.statValue, ...styles.statValueNeutral }}>{results.retry}</div>
                    </div>
                  )}
                  {results.pure === undefined && results.retry === undefined && (
                    <>
                      <div style={styles.statCard}>
                        <div style={styles.statLabel}>Symbols</div>
                        <div style={{ ...styles.statValue, ...styles.statValueNeutral }}>{results.symbols?.length ?? 0}</div>
                      </div>
                      <div style={styles.statCard}>
                        <div style={styles.statLabel}>Status</div>
                        <div style={{ ...styles.statValue, fontSize: '13px', paddingTop: '6px', color: C.green }}>DONE</div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Symbols panel */}
              {results.symbols && results.symbols.length > 0 ? (
                <div style={styles.panel}>
                  <div style={styles.symbolsHeader}>
                    <div style={styles.symbolsHeaderLeft}>
                      <div style={styles.panelHeaderDot} />
                      <span style={styles.panelTitle}>Symbols</span>
                    </div>
                    <div style={styles.symbolsBadge}>{results.symbols.length} stocks</div>
                  </div>
                  <textarea
                    value={results.symbols.join(', ')}
                    readOnly
                    style={styles.symbolsTextarea}
                  />
                  <div style={styles.symbolsActions}>
                    <button
                      onClick={() => copySymbols(results.symbols)}
                      style={{ ...styles.actionButton, ...styles.actionButtonLeft }}
                      onMouseEnter={e => {
                        (e.currentTarget as HTMLButtonElement).style.color = C.green;
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor = C.greenMuted;
                      }}
                      onMouseLeave={e => {
                        (e.currentTarget as HTMLButtonElement).style.color = C.textSecondary;
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
                      }}
                    >
                      <span>{copied ? '✓' : '⧉'}</span>
                      {copied ? 'Copied!' : 'Copy for TradingView'}
                    </button>
                    <button
                      onClick={() => downloadCsv(results.downloadUrl, results.csvFile)}
                      style={styles.actionButton}
                      onMouseEnter={e => {
                        (e.currentTarget as HTMLButtonElement).style.color = C.green;
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor = C.greenMuted;
                      }}
                      onMouseLeave={e => {
                        (e.currentTarget as HTMLButtonElement).style.color = C.textSecondary;
                        (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
                      }}
                    >
                      <span>↓</span>
                      Download CSV
                    </button>
                  </div>
                </div>
              ) : (
                <div style={styles.panel}>
                  <div style={styles.noResults}>
                    {results.summary?.coverage.evaluated === 0
                      ? 'No tickers could be evaluated. Check scan coverage above.'
                      : results.summary && (results.summary.coverage.skipped > 0 || results.summary.coverage.incomplete_checks > 0)
                        ? 'No matches among the tickers and lookbacks that could be checked.'
                        : 'No symbols matched the selected parameters.'}
                  </div>
                  {results.downloadUrl && <button style={styles.actionButton} onClick={() => downloadCsv(results.downloadUrl, results.csvFile)}>Download CSV</button>}
                </div>
              )}
            </div>
          )}

          {/* Idle */}
          {!loading && !results && !error && (
            <div style={styles.idleCard}>
              <div style={styles.idleIcon}>◈</div>
              <div style={styles.idleTitle}>Ready to Scan</div>
              <div style={styles.idleSub}>
                Configure parameters above and click Run Scan to begin scanning {market} for AVWAP {logic} setups.
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
