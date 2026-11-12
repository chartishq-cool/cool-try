import axios from 'axios';
import type { NextApiRequest, NextApiResponse } from 'next';
import { getGitHubAuthHeaders, getGitHubConfig } from '../../lib/github';
import { requireScanAccess } from '../../lib/scan-access';
import { scheduledDefaults, settingsError, strategies } from '../../lib/scan-settings';

type Preset = {
  defaults?: Record<string, unknown>;
  override?: { date: string; params: Record<string, unknown> };
};

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET' && req.method !== 'PUT') return res.status(405).end();
  if (!requireScanAccess(req, res)) return;
  const { logic, timeframe, mode, params, date } = req.method === 'GET' ? req.query : (req.body ?? {});
  if (typeof logic !== 'string' || !strategies.includes(logic) ||
      (timeframe !== 'daily' && timeframe !== 'weekly')) {
    return res.status(400).json({ error: 'Choose an NSE daily or weekly preset.' });
  }
  if (req.method === 'PUT') {
    if (!['default', 'override', 'clear'].includes(mode)) return res.status(400).json({ error: 'Choose how to save.' });
    if (mode !== 'clear') {
      const invalid = settingsError(logic, timeframe, params);
      if (invalid) return res.status(400).json({ error: invalid });
    }
    if (mode === 'override') {
      const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' })
        .formatToParts(new Date()).filter((part) => part.type !== 'literal');
      const istDate = ['year', 'month', 'day'].map((key) => today.find((part) => part.type === key)?.value).join('-');
      const day = typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) ? new Date(date + 'T00:00:00Z') : new Date(NaN);
      if (!Number.isFinite(+day) || day.toISOString().slice(0, 10) !== date ||
          date < istDate || [0, 6].includes(day.getUTCDay())) {
        return res.status(400).json({ error: 'Choose today or a future weekday in India time.' });
      }
    }
  }

  const { token, repo, error } = getGitHubConfig();
  if (!token || !repo || error) return res.status(503).json({ error });
  const url = `https://api.github.com/repos/${repo}/contents/backend/schedule_presets.json`;
  const headers = getGitHubAuthHeaders(token);
  try {
    const { data } = await axios.get<{ sha: string; content: string }>(url, { headers, params: { ref: 'main' } });
    const presets: Record<string, Preset> = JSON.parse(Buffer.from(data.content, 'base64').toString('utf8'));
    const key = `${timeframe}-${logic}`;
    const preset = presets[key] ?? {};
    const defaults = scheduledDefaults(logic, timeframe);
    if (req.method === 'GET') {
      return res.json({ defaults: { ...defaults, ...preset.defaults }, override: preset.override });
    }
    if (mode === 'default') preset.defaults = params;
    if (mode === 'override') preset.override = { date, params };
    if (mode === 'clear') delete preset.override;
    presets[key] = preset;
    await axios.put(url, {
      message: `Update ARGUS ${key} scheduled preset`, branch: 'main', sha: data.sha,
      content: Buffer.from(JSON.stringify(presets, null, 2) + '\n').toString('base64'),
    }, { headers });
    return res.json({ defaults: { ...defaults, ...preset.defaults }, override: preset.override });
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 409) {
      return res.status(409).json({ error: 'A preset changed while saving. Try again.' });
    }
    return res.status(502).json({ error: 'GitHub could not read or save scheduled settings. Check the deployment token and branch settings.' });
  }
}
