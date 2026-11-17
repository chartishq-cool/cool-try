import axios from 'axios';
import type { NextApiRequest, NextApiResponse } from 'next';
import { getGitHubAuthHeaders, getGitHubConfig, getGitHubErrorMessage } from '../../lib/github';
import { ScanSummary, scanFile, validScanId } from '../../lib/scan-results';

type ScanResults = { total: number; pure?: number; retry?: number; symbols: string[] };
type WorkflowRun = { id: number; event: string; created_at: string; status: string; conclusion: string | null; display_title: string; html_url: string };

function parseCsvLine(line: string): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const nextChar = line[i + 1];

    if (char === '"' && inQuotes && nextChar === '"') {
      current += '"';
      i += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      result.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }

  result.push(current.trim());
  return result;
}

function parseCsvResults(csvText: string): ScanResults {
  const lines = csvText
    .trim()
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0);

  if (lines.length < 2) {
    return { total: 0, pure: 0, retry: 0, symbols: [] };
  }

  const headers = parseCsvLine(lines[0]);
  const symbolColIndex =
    headers.indexOf('TV Symbol') !== -1
      ? headers.indexOf('TV Symbol')
      : headers.indexOf('TV_Symbol');
  const failedAttemptsIndex = headers.indexOf('Failed Attempts');

  if (symbolColIndex === -1) {
    return { total: 0, pure: 0, retry: 0, symbols: [] };
  }

  const dataRows = lines.slice(1).map((line) => parseCsvLine(line));
  const symbols = dataRows
    .map((row) => row[symbolColIndex])
    .filter((symbol): symbol is string => Boolean(symbol));
  const uniqueSymbols = Array.from(new Set(symbols));


    const symbolRowMap = new Map<string, string[]>();
dataRows.forEach((row) => {
  const sym = row[symbolColIndex];
  if (!sym) return;
  const existing = symbolRowMap.get(sym);
  if (!existing) {
    symbolRowMap.set(sym, row);
  } else if (failedAttemptsIndex !== -1) {
    const newAttempts = Number.parseInt(row[failedAttemptsIndex] ?? '99', 10);
    const oldAttempts = Number.parseInt(existing[failedAttemptsIndex] ?? '99', 10);
    if (newAttempts < oldAttempts) symbolRowMap.set(sym, row);
  }
});

const dedupedRows = Array.from(symbolRowMap.values());
    
    let pure = 0;
    let retry = 0;
    
    if (failedAttemptsIndex !== -1) {
      dedupedRows.forEach((row) => {
        const attempts = Number.parseInt(row[failedAttemptsIndex] ?? '0', 10);
        if (Number.isNaN(attempts) || attempts === 0) {
          pure += 1;
        } else {
          retry += 1;
        }
      });
    }
    
    return {
      total: dedupedRows.length,
      pure: failedAttemptsIndex !== -1 ? pure : undefined,
      retry: failedAttemptsIndex !== -1 ? retry : undefined,
      symbols: uniqueSymbols,
    };
}


async function readResult(repo: string, token: string, jobId: string) {
  const meta = await scanFile(repo, token, jobId, 'summary.json');
  const summary: ScanSummary = JSON.parse(meta.data);
  if (!/^[a-z0-9_]+\.csv$/.test(summary.csv_file)) throw new Error('Invalid result filename');
  const csv = await scanFile(repo, token, jobId, summary.csv_file);
  return { summary, csv: csv.data };
}

function resultResponse(jobId: string, summary: ScanSummary, csv: string) {
  return {
    jobId, csvFile: summary.csv_file,
    downloadUrl: `/api/scan-status?jobId=${jobId}&download=1`,
    results: parseCsvResults(csv), summary,
  };
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET') return res.status(405).end();
  const { download, latest, dashboard } = req.query;
  const lookupLatest = latest === '1' && download !== '1';
  let { jobId } = req.query;
  if (dashboard !== '1' && !lookupLatest && !validScanId(jobId)) return res.status(400).json({ status: 'failed', error: 'Invalid scan ID' });
  const { token, repo, error } = getGitHubConfig();
  if (!token || !repo || error) return res.status(503).json({ status: 'failed', error });

  try {
    if (dashboard === '1') {
      const listRuns = async (event: string, limit: number) => {
        const { data } = await axios.get<{ workflow_runs: WorkflowRun[] }>(
          `https://api.github.com/repos/${repo}/actions/workflows/screener.yml/runs`,
          {
            headers: getGitHubAuthHeaders(token),
            params: { branch: 'main', status: 'success', event, per_page: limit },
            timeout: 10000,
          },
        );
        return data.workflow_runs.sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
      };
      const scheduledResults = async () => {
        const runs = await listRuns('schedule', 14);
        const selected = new Map<string, WorkflowRun>();
        for (let offset = 0; offset < runs.length && selected.size < 2; offset += 4) {
          const candidates = await Promise.all(runs.slice(offset, offset + 4).map(async (run) => {
            const meta = await scanFile(repo, token, `${run.id}-breakout`, 'summary.json');
            return { run, summary: JSON.parse(meta.data) as ScanSummary };
          }));
          for (const { run, summary } of candidates) {
            if (summary.market === 'NSE' && ['daily', 'weekly'].includes(summary.timeframe) && !selected.has(summary.timeframe)) {
              selected.set(summary.timeframe, run);
            }
          }
        }
        return Promise.all(Array.from(selected.values()).flatMap((run) =>
          ['breakout', 'pullback'].map(async (strategy) => {
            const id = `${run.id}-${strategy}`;
            const { summary, csv } = await readResult(repo, token, id);
            return { ...resultResponse(id, summary, csv), startedAt: run.created_at, strategy };
          }),
        ));
      };
      const manualResult = async () => {
        const [run] = await listRuns('repository_dispatch', 1);
        if (!run) return null;
        const id = run.display_title.match(/^ARGUS (\d{13}-[a-f0-9-]{36})$/)?.[1];
        if (!id) throw new Error('Latest manual workflow has no scan ID');
        const { summary, csv } = await readResult(repo, token, id);
        return { ...resultResponse(id, summary, csv), startedAt: run.created_at };
      };
      const [scheduled, manual] = await Promise.allSettled([scheduledResults(), manualResult()]);
      return res.json({
        scheduled: scheduled.status === 'fulfilled' ? scheduled.value : [],
        manual: manual.status === 'fulfilled' ? manual.value : null,
        scheduledUnavailable: scheduled.status === 'rejected',
        manualUnavailable: manual.status === 'rejected',
      });
    }

    if (lookupLatest) {
      const { data } = await axios.get<{ workflow_runs: WorkflowRun[] }>(
        `https://api.github.com/repos/${repo}/actions/workflows/screener.yml/runs`,
        {
          headers: getGitHubAuthHeaders(token),
          params: { branch: 'main', status: 'success', per_page: 20 },
          timeout: 10000,
        },
      );
      const run = data.workflow_runs
        .filter((item) => item.event === 'schedule' || item.event === 'repository_dispatch')
        .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id)[0];
      if (!run) return res.json({ status: 'empty' });

      const manualId = run.display_title.match(/^ARGUS (\d{13}-[a-f0-9-]{36})$/)?.[1];
      const ids = run.event === 'schedule'
        ? [`${run.id}-breakout`, `${run.id}-pullback`]
        : manualId ? [manualId] : [];
      if (!ids.length) throw new Error('Latest workflow has no scan ID');

      const scans = await Promise.all(ids.map(async (id) => {
        const { summary, csv } = await readResult(repo, token, id);
        return resultResponse(id, summary, csv);
      }));
      return res.json({ status: 'completed', scans });
    }
    if (!validScanId(jobId)) return res.status(400).json({ status: 'failed', error: 'Invalid scan ID' });

    if (download !== '1') {
      const time = Number(jobId.split('-')[0]);
      if (!/^\d{13}-/.test(jobId) || !Number.isFinite(time)) {
        return res.status(400).json({ status: 'failed', error: 'Invalid manual scan ID' });
      }
      const created = new Date(time - 1000).toISOString();
      const { data } = await axios.get<{ workflow_runs: WorkflowRun[] }>(
        `https://api.github.com/repos/${repo}/actions/workflows/screener.yml/runs`,
        { headers: getGitHubAuthHeaders(token), params: { event: 'repository_dispatch', created: `>=${created}`, per_page: 100 }, timeout: 10000 },
      );
      const run = data.workflow_runs.find((item) => item.display_title === `ARGUS ${jobId}`);
      if (!run || run.status !== 'completed') return res.json({ status: 'pending' });
      if (run.conclusion !== 'success') {
        return res.json({ status: 'failed', error: `GitHub scan ended with status ${run.conclusion}.`, runUrl: run.html_url });
      }
    }

    const { summary, csv } = await readResult(repo, token, jobId);
    if (download === '1') {
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="${summary.csv_file}"`);
      return res.send(csv);
    }
    return res.json({ status: 'completed', ...resultResponse(jobId, summary, csv) });
  } catch (err) {
    const missing = axios.isAxiosError(err) && err.response?.status === 404;
    return res.status(missing ? 404 : 502).json({
      status: 'failed',
      error: missing ? 'GitHub did not return the workflow or files for this scan.' : getGitHubErrorMessage(err, repo),
    });
  }
}
