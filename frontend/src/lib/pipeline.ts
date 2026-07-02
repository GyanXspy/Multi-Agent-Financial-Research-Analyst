/**
 * Pipeline state model — maps SSE status messages to per-agent progress.
 * Kept separate from the PipelineStatus component so the component file
 * only exports components (React fast-refresh requirement).
 */

export type AgentState = 'pending' | 'running' | 'done';

export interface PipelineAgents {
  'Financial Data': AgentState;
  News: AgentState;
  Filings: AgentState;
  'Peer Comparison': AgentState;
  'Thesis Writer': AgentState;
}

export const INITIAL_AGENTS: PipelineAgents = {
  'Financial Data': 'pending',
  News: 'pending',
  Filings: 'pending',
  'Peer Comparison': 'pending',
  'Thesis Writer': 'pending',
};

/** Fold one SSE status message into the agent state map. */
export function reduceAgentStates(prev: PipelineAgents, msg: string): PipelineAgents {
  const next = { ...prev };
  if (msg.includes('Starting Financial Data')) {
    next['Financial Data'] = 'running';
    next.News = 'running';
    next.Filings = 'running';
    next['Peer Comparison'] = 'running';
  }
  for (const name of ['Financial Data', 'News', 'Filings', 'Peer Comparison'] as const) {
    if (msg.includes(`${name} agent completed`)) next[name] = 'done';
  }
  if (msg.includes('All worker agents completed')) {
    next['Financial Data'] = 'done';
    next.News = 'done';
    next.Filings = 'done';
    next['Peer Comparison'] = 'done';
  }
  if (msg.includes('Thesis Writer Agent generating')) next['Thesis Writer'] = 'running';
  if (msg.includes('Analysis complete')) next['Thesis Writer'] = 'done';
  return next;
}
