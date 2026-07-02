/**
 * Fetch-based SSE reader.
 *
 * Native EventSource cannot send an Authorization header, so we stream the
 * response body with fetch + ReadableStream and parse `text/event-stream`
 * frames ourselves. Returns an abort function for cleanup.
 */

export interface SSEHandlers {
  onEvent: (event: string, data: string) => void;
  onError: (message: string) => void;
  onClose: () => void;
}

export function connectSSE(url: string, token: string, handlers: SSEHandlers): () => void {
  const controller = new AbortController();

  (async () => {
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
        handlers.onError(err instanceof Error ? err.message : 'Connection failed');
      }
      return;
    }

    if (!response.ok || !response.body) {
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
        handlers.onError(err instanceof Error ? err.message : 'Stream interrupted');
        return;
      }
    }

    if (!controller.signal.aborted) handlers.onClose();
  })();

  return () => controller.abort();
}
