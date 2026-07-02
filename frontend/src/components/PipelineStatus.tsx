/**
 * PipelineStatus — per-agent step indicators derived from SSE status messages,
 * plus a scrolling raw log. Announced politely to screen readers.
 */

import { useEffect, useRef } from 'react';
import type { AgentState, PipelineAgents } from '../lib/pipeline';

function StateIcon({ state }: { state: AgentState }) {
  if (state === 'done') {
    return (
      <span className="w-4 h-4 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0" aria-hidden="true">
        <svg className="w-2.5 h-2.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </span>
    );
  }
  if (state === 'running') {
    return (
      <span className="w-4 h-4 rounded-full border-2 border-emerald-400/30 border-t-emerald-400 animate-spin shrink-0" aria-hidden="true" />
    );
  }
  return <span className="w-4 h-4 rounded-full border-2 border-ink-700 shrink-0" aria-hidden="true" />;
}

interface PipelineStatusProps {
  agents: PipelineAgents;
  log: string[];
}

export default function PipelineStatus({ agents, log }: PipelineStatusProps) {
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [log]);

  return (
    <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 shadow-lg">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-400 mb-3">
        Agent Pipeline
      </h3>

      {/* Agent steps */}
      <ul className="space-y-2.5 mb-4" aria-label="Agent progress">
        {(Object.keys(agents) as Array<keyof PipelineAgents>).map((name) => (
          <li key={name} className="flex items-center gap-2.5 text-sm">
            <StateIcon state={agents[name]} />
            <span className={agents[name] === 'pending' ? 'text-ink-500' : agents[name] === 'running' ? 'text-white' : 'text-ink-300'}>
              {name}
            </span>
            {agents[name] === 'running' && (
              <span className="text-[10px] text-emerald-400/80 uppercase tracking-wider ml-auto">running</span>
            )}
          </li>
        ))}
      </ul>

      {/* Raw log */}
      {log.length > 0 && (
        <div
          className="border-t border-ink-800 pt-3 max-h-40 overflow-y-auto space-y-1 text-xs"
          aria-live="polite"
          aria-label="Pipeline log"
        >
          {log.map((msg, i) => (
            <div key={i} className="text-ink-400 leading-relaxed animate-fade-in">
              <span className="text-ink-600 mr-1.5 tabular-nums">{String(i + 1).padStart(2, '0')}</span>
              {msg}
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}
    </div>
  );
}
