import os from 'node:os';

/** The GitHub run ID in CI, or local-<user> on a laptop. */
export function runId(): string {
  if (process.env.GITHUB_RUN_ID) return process.env.GITHUB_RUN_ID;
  const user = os.userInfo().username.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `local-${user || 'user'}`;
}

/** Name for data a test creates: qa-auto-<run-id>-<name> (AR-13). */
export function qaAutoName(name: string): string {
  return `qa-auto-${runId()}-${name}`;
}
