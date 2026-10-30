/**
 * Search progress-bar percent derived from the per-tool live state
 * (SearchJob.tool_progress), NOT from a flat per-status guess.
 *
 * The orchestrator pre-populates EVERY planned tool as `pending` the
 * moment a search starts, then flips each to `running` and finally to a
 * terminal status (success/partial/error). So `tool_progress.length` is
 * the true total tool count from t=0, and we can show real completion:
 * finished tools full credit, in-flight tools half credit. Capped below
 * 100 until the job itself is terminal so the bar never claims "done"
 * before the results are persisted.
 */
const TERMINAL_TOOL = new Set(['success', 'partial', 'error'])

export function searchProgressPercent(
  toolProgress: Array<{ status?: string }> | undefined,
  jobStatus: string | undefined,
  jobIsTerminal: boolean,
): number {
  // A cancelled job is terminal but did NOT finish, so it keeps the percent
  // it actually reached. Showing 100 % would tell the investigator the
  // search ran to the end, which is the one thing that did not happen.
  if (jobIsTerminal && jobStatus !== 'cancelled') return 100
  const tp = toolProgress || []
  const total = tp.length
  if (!total) return jobStatus === 'running' ? 8 : 3
  const done = tp.filter((t) => t.status && TERMINAL_TOOL.has(t.status)).length
  const running = tp.filter((t) => t.status === 'running').length
  const pct = ((done + running * 0.5) / total) * 100
  return Math.min(99, Math.max(3, Math.round(pct)))
}
