/**
 * ReportView — renders the markdown research report with copy &
 * download-as-markdown actions.
 */

import { useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ReportViewProps {
  report: string;
  symbol: string;
  streaming: boolean;
}

export default function ReportView({ report, symbol, streaming }: ReportViewProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  const handleDownload = () => {
    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${symbol || 'report'}-research-report.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="bg-card border border-border  shadow-lg animate-fade-in overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-background/40">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Research Report
          </span>
          {streaming && (
            <span className="flex items-center gap-1.5 text-[10px] text-primary uppercase tracking-wider">
              <span className="w-1.5 h-1.5  bg-emerald-400 animate-pulse-dot" aria-hidden="true" />
              generating
            </span>
          )}
        </div>
        {!streaming && report && (
          <div className="flex gap-2">
            <button
              onClick={handleCopy}
              className="text-xs text-muted-foreground hover:text-foreground bg-muted hover:bg-muted px-3 py-1.5  transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
            >
              {copied ? '✓ Copied' : 'Copy'}
            </button>
            <button
              onClick={handleDownload}
              className="text-xs text-muted-foreground hover:text-foreground bg-muted hover:bg-muted px-3 py-1.5  transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
            >
              Download .md
            </button>
          </div>
        )}
      </div>

      {/* Markdown body */}
      <div className="p-6 sm:p-8">
        <div className="prose-report">
          <Markdown remarkPlugins={[remarkGfm]}>{report}</Markdown>
        </div>
      </div>
    </div>
  );
}
