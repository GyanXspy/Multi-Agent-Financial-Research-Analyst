/**
 * Fetch-based SSE reader with auto-reconnect.
 *
 * Native EventSource cannot send an Authorization header, so we stream the
 * response body with fetch + ReadableStream and parse `text/event-stream`
 * frames ourselves. Returns an abort function for cleanup.
 *
 * Production features:
 * - Auto-reconnect with exponential backoff on stream failures
 * - Max reconnect attempts with configurable limit
 * - Retry-After header support
 */

export interface SSEHandlers {
  onEvent: (event: string, data: string) => void;
  onError: (message: string) => void;
  onClose: () => void;
  onReconnect?: (attempt: number) => void;
}

interface SSEOptions {
  maxReconnects?: number;
  baseDelay?: number;
  maxDelay?: number;
}

const DEFAULT_OPTIONS: Required<SSEOptions> = {
  maxReconnects: 5,
  baseDelay: 1000,
  maxDelay: 30000,
};

function jitter(ms: number): number {
  return ms + Math.random() * ms * 0.3;
}

export function connectSSE(
  url: string,
  token: string,
  handlers: SSEHandlers,
  options?: SSEOptions,
): () => void {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  const controller = new AbortController();
  let reconnectCount = 0;
  let isAborted = false;

  async function connect() {
    let response: Response;
    try {
      response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'text/event-stream',
        },
        signal: controller.signal,
      });
    } catch (err) {
      if (!controller.signal.aborted) {
        // Try to reconnect on network errors
        if (reconnectCount < opts.maxReconnects) {
          await attemptReconnect();
          return;
        }
        handlers.onError(err instanceof Error ? err.message : 'Connection failed');
      }
      return;
    }

    if (!response.ok || !response.body) {
      // On retryable status codes, attempt reconnect
      if ((response.status === 429 || response.status >= 500) && reconnectCount < opts.maxReconnects) {
        const retryAfter = response.headers.get('Retry-After');
        const delay = retryAfter
          ? parseInt(retryAfter, 10) * 1000
          : jitter(opts.baseDelay * Math.pow(2, reconnectCount));
        reconnectCount++;
        handlers.onReconnect?.(reconnectCount);
        await new Promise(resolve => setTimeout(resolve, delay));
        if (!isAborted) {
          await connect();
        }
        return;
      }

      let detail = `Stream failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        /* ignore */
      }
      handlers.onError(detail);
      return;
    }

    // Reset reconnect count on successful connection
    reconnectCount = 0;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const dispatchFrame = (frame: string) => {
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
      }
      if (dataLines.length > 0) handlers.onEvent(event, dataLines.join('\n'));
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line (handle \r\n too)
        let sep: number;
        while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep).replace(/^\r?\n\r?\n/, '');
          if (frame.trim()) dispatchFrame(frame);
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        // Stream interrupted — try to reconnect
        if (reconnectCount < opts.maxReconnects) {
          await attemptReconnect();
          return;
        }
        handlers.onError(err instanceof Error ? err.message : 'Stream interrupted');
        return;
      }
    }

    if (!controller.signal.aborted) handlers.onClose();
  }

  async function attemptReconnect() {
    if (isAborted) return;
    reconnectCount++;
    const delay = Math.min(
      jitter(opts.baseDelay * Math.pow(2, reconnectCount - 1)),
      opts.maxDelay,
    );
    console.warn(`[SSE] Reconnecting (attempt ${reconnectCount}/${opts.maxReconnects}) in ${Math.round(delay)}ms`);
    handlers.onReconnect?.(reconnectCount);
    await new Promise(resolve => setTimeout(resolve, delay));
    if (!isAborted) {
      await connect();
    }
  }

  // Start the connection
  connect();

  // Return abort function
  return () => {
    isAborted = true;
    controller.abort();
  };
}
