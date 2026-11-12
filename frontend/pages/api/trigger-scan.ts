import axios from 'axios';
import { randomUUID } from 'crypto';
import { requireScanAccess } from '../../lib/scan-access';
import { markets, settingsError } from '../../lib/scan-settings';
import type { NextApiRequest, NextApiResponse } from 'next';
import { getGitHubAuthHeaders, getGitHubConfig, getGitHubErrorMessage } from '../../lib/github';

type TriggerScanResponse = {
  success?: boolean;
  jobId?: string;
  message?: string;
  error?: string;
};

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<TriggerScanResponse>
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  if (!requireScanAccess(req, res)) return;

  try {
    const { market, logic, timeframe, params } = (req.body ?? {}) as {
      market: string;
      logic: string;
      timeframe: string;
      params: Record<string, unknown>;
    };

    const invalid = !markets.includes(market) ? 'Choose a valid market.' : settingsError(logic, timeframe, params);
    if (invalid) return res.status(400).json({ error: invalid });

    const githubConfig = getGitHubConfig();

    if (githubConfig.error || !githubConfig.token || !githubConfig.repo) {
      return res.status(500).json({ error: githubConfig.error });
    }

    const { token: githubToken, repo: githubRepo } = githubConfig;

    const jobId = `${Date.now()}-${randomUUID()}`;

    await axios.post(
      `https://api.github.com/repos/${githubRepo}/dispatches`,
      {
        event_type: 'run-screener',
        client_payload: {
          market,
          logic,
          timeframe,
          params: JSON.stringify(params),
          jobId,
        },
      },
      {
        headers: getGitHubAuthHeaders(githubToken),
      }
    );

    return res.status(200).json({
      success: true,
      jobId,
      message: 'Scan triggered successfully',
    });
  } catch (error) {
    const message = getGitHubErrorMessage(error, getGitHubConfig().repo);
    console.error('Error triggering scan:', message);
    return res.status(500).json({ error: message });
  }
}
