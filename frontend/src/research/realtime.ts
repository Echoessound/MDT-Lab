import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { researchApi } from './api';
import { auditEventSchema, type AuditEvent, type Run } from './schemas';

export const terminal = (status: string) => ['completed', 'incomplete', 'failed', 'cancelled'].includes(status);
export const newerSnapshot = (current: Run | undefined, incoming: Run) => current && current.run_id === incoming.run_id && current.last_seq > incoming.last_seq ? current : incoming;
export type EventBuffer = { runId: string; cursor: number; events: AuditEvent[]; pending: Map<number, AuditEvent> };
export const emptyBuffer = (runId: string): EventBuffer => ({ runId, cursor: 0, events: [], pending: new Map() });

/** Confirm only contiguous events. A failed gap fetch can never advance the recovery cursor. */
export function reconcileEvents(state: EventBuffer, incoming: AuditEvent[]): EventBuffer {
  const pending = new Map(state.pending);
  incoming.forEach(event => {
    if (event.run_id === state.runId && event.seq > state.cursor && !pending.has(event.seq)) pending.set(event.seq, event);
  });
  let cursor = state.cursor;
  const accepted: AuditEvent[] = [];
  while (pending.has(cursor + 1)) {
    cursor += 1;
    accepted.push(pending.get(cursor)!);
    pending.delete(cursor);
  }
  return { ...state, cursor, pending, events: [...state.events, ...accepted].slice(-500) };
}

export function useResearchRun(runId: string) {
  const client = useQueryClient();
  return useQuery({
    queryKey: ['research-run', runId],
    queryFn: async () => newerSnapshot(client.getQueryData<Run>(['research-run', runId]), await researchApi.run(runId)),
    refetchInterval: query => query.state.data && terminal(query.state.data.status) ? false : 900,
  });
}

export function useResearchStream(runId: string) {
  const client = useQueryClient();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [connection, setConnection] = useState<'connecting' | 'connected' | 'reconnecting' | 'synced' | 'offline'>('connecting');
  const [retry, setRetry] = useState(0);
  const state = useRef(emptyBuffer(runId));
  useEffect(() => {
    let disposed = false;
    let source: EventSource | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let disconnectedAt: number | undefined;
    let recovering: Promise<void> | undefined;
    let finalizing = false;
    if (state.current.runId !== runId) { state.current = emptyBuffer(runId); setEvents([]); }

    const syncSnapshot = async () => {
      const fresh = await researchApi.run(runId);
      if (!disposed) client.setQueryData<Run>(['research-run', runId], old => newerSnapshot(old, fresh));
      return fresh;
    };
    const finish = async () => {
      if (finalizing || disposed) return;
      finalizing = true;
      source?.close();
      try {
        await syncSnapshot();
        if (!disposed) { setConnection('synced'); void client.invalidateQueries({ queryKey: ['research-runs'] }); }
      } catch { if (!disposed) setConnection('offline'); }
    };
    const receive = (batch: AuditEvent[]) => {
      if (disposed) return;
      const previous = state.current.cursor;
      state.current = reconcileEvents(state.current, batch);
      setEvents(state.current.events);
      const accepted = state.current.events.filter(event => event.seq > previous);
      if (accepted.some(event => ['run.completed', 'run.failed', 'run.cancelled'].includes(event.type))) void finish();
      if (accepted.length) void client.invalidateQueries({ queryKey: ['research-run', runId] });
    };
    const catchUp = (): Promise<void> => {
      if (recovering) return recovering;
      recovering = (async () => {
        let more = true;
        while (!disposed && more) {
          const before = state.current.cursor;
          const page = await researchApi.events(runId, before);
          receive(page.events);
          more = page.events.length === 500 && state.current.cursor > before;
        }
      })().finally(() => { recovering = undefined; });
      return recovering;
    };
    const schedule = () => {
      if (disposed || finalizing) return;
      source?.close();
      disconnectedAt ??= Date.now();
      if (Date.now() - disconnectedAt >= 30000) { setConnection('offline'); return; }
      setConnection('reconnecting');
      clearTimeout(timer);
      timer = setTimeout(() => void connect(), Math.min(500 * 2 ** attempts++, 5000));
    };
    const connect = async () => {
      if (disposed || finalizing) return;
      try {
        await catchUp();
        if (disposed || finalizing) return;
        const snapshot = await syncSnapshot();
        if (disposed) return;
        if (terminal(snapshot.status) && state.current.cursor >= snapshot.last_seq) { await finish(); return; }
        source = new EventSource(`/api/v2/runs/${encodeURIComponent(runId)}/events?after_seq=${state.current.cursor}`);
        source.onopen = () => { if (!disposed) { attempts = 0; disconnectedAt = undefined; setConnection('connected'); } };
        source.onmessage = message => {
          if (disposed) return;
          try {
            const parsed = auditEventSchema.safeParse(JSON.parse(message.data));
            if (!parsed.success) { source?.close(); setConnection('offline'); return; }
            receive([parsed.data]);
            if (state.current.pending.size) void catchUp().catch(schedule);
          } catch { source?.close(); setConnection('offline'); }
        };
        source.onerror = () => { if (!disposed) schedule(); };
      } catch { schedule(); }
    };
    void connect();
    return () => { disposed = true; clearTimeout(timer); source?.close(); };
  }, [client, runId, retry]);
  return { events, connection, reconnect: () => { setConnection('connecting'); setRetry(value => value + 1); } };
}
