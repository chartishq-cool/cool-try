export type GitHubConfig = {
  token?: string;
  repo?: string;
  error?: string;
};

const PLACEHOLDER_REPOS = new Set([
  'your-username/screener-cloud',
  'owner/repo',
  'username/repository',
]);

function cleanEnv(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function repoFromVercelEnv(): string | undefined {
  const owner = cleanEnv(process.env.VERCEL_GIT_REPO_OWNER);
  const slug = cleanEnv(process.env.VERCEL_GIT_REPO_SLUG);

  return owner && slug ? `${owner}/${slug}` : undefined;
}

export function resolveGitHubRepo(): string | undefined {
  return (
    cleanEnv(process.env.NEXT_PUBLIC_GITHUB_REPO) ||
    cleanEnv(process.env.GITHUB_REPOSITORY) ||
    repoFromVercelEnv()
  );
}

export function getGitHubConfig(): GitHubConfig {
  const token = cleanEnv(process.env.GITHUB_TOKEN);
  const repo = resolveGitHubRepo();

  if (!token) {
    return { token, repo, error: 'GitHub token not configured. Set GITHUB_TOKEN in your deployment environment.' };
  }

  if (!repo || PLACEHOLDER_REPOS.has(repo)) {
    return {
      token,
      repo,
      error:
        'GitHub repo not configured. Set NEXT_PUBLIC_GITHUB_REPO to your owner/repo value, for example chartishq-cool/cool-try.',
    };
  }

  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) {
    return {
      token,
      repo,
      error:
        'Invalid NEXT_PUBLIC_GITHUB_REPO. Use the owner/repo format, for example chartishq-cool/cool-try.',
    };
  }

  return { token, repo };
}

export function getGitHubAuthHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

export function getGitHubErrorMessage(error: unknown, repo?: string): string {
  if (!error || typeof error !== 'object') {
    return 'GitHub request failed';
  }

  if (!('response' in error)) {
    return error instanceof Error ? error.message : 'GitHub request failed';
  }

  const axiosError = error as {
    message?: string;
    response?: { status?: number; data?: unknown };
  };

  if (axiosError.response?.status === 404 && repo) {
    return [
      `GitHub repository or path not found/inaccessible: ${repo}.`,
      'Verify NEXT_PUBLIC_GITHUB_REPO and make sure GITHUB_TOKEN can access the repo.',
    ].join(' ');
  }

  const data = axiosError.response?.data;
  const githubMessage =
    data && typeof data === 'object' && 'message' in data
      ? String((data as { message: unknown }).message)
      : undefined;

  return githubMessage || axiosError.message || 'GitHub request failed';
}
