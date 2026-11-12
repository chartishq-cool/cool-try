import axios from 'axios';
import { getGitHubAuthHeaders } from './github';

export type ScanSummary = {
  market: string;
  timeframe: string;
  csv_file: string;
  coverage: { requested: number; evaluated: number; skipped: number; incomplete_checks: number };
  settings: Record<string, number | number[] | string>;
  universe: { source: string; refreshed_at?: string; added?: string[]; removed?: string[]; unmapped?: string[] };
};

export type TickerDiagnostic = {
  status: string;
  bars?: number;
  periods?: Record<string, {
    status: string; anchor?: string; close?: number; avwap?: number; turnover?: number;
    distance_pct?: number; failed_attempts?: number; crosses?: number; longest_below?: number;
    history_short?: boolean; crossings?: number; pending_crossings?: number;
    sustain_failures?: number; tolerance_failures?: number;
  }>;
};

export const validScanId = (value: unknown): value is string =>
  typeof value === 'string' && /^[a-z0-9-]{1,80}$/.test(value);

export function scanFile(repo: string, token: string, scanId: string, file: string) {
  const url = `https://api.github.com/repos/${repo}/contents/backend/results/runs/${scanId}/${file}`;
  return axios.get<string>(url, {
    responseType: 'text', headers: { ...getGitHubAuthHeaders(token), Accept: 'application/vnd.github.raw+json' },
    params: { ref: 'main' }, timeout: 10000,
  });
}
