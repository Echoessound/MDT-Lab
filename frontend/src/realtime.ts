import { useEffect, useReducer, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import { eventSchema, opinionSchema, type Run, type RunEvent } from './schemas';

export const isTerminal = (status: Run['status']) => ['completed', 'incomplete', 'failed', 'cancelled'].includes(status);

export function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  const bySeq = new Map(current.map(event => [event.seq, event]));
  incoming.forEach(event => { if (!bySeq.has(event.seq)) bySeq.set(event.seq, event); });
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq).slice(-500);
}

export function applyEvent(run: Run, event: RunEvent): Run {
  if (event.run_id !== run.run_id || event.seq <= run.last_seq) return run;
  const audit = event.payload;
  const next: Run = { ...run, last_seq: event.seq, stage: audit.stage, updated_at: event.timestamp, agents: { ...run.agents } };
  if (next.status === 'queued') next.status = 'running';
  if (audit.agent_name) {
    const name = audit.agent_name;
    const agent = { ...next.agents[name] };
    if (audit.event_type === 'agent_started') agent.status = 'running';
    if (audit.event_type === 'agent_completed') {
      const parsed = opinionSchema.safeParse(audit.details.opinion);
      if (parsed.success) {
        if (audit.stage === 'TARGETED_DISCUSSION') agent.previous_opinion = agent.opinion;
        agent.opinion = parsed.data;
      }
      agent.status = 'completed';
    }
    if (audit.event_type === 'agent_failed') { agent.status = 'failed'; agent.error = String(audit.details.error_code ?? 'agent_exception'); }
    next.agents[name] = agent;
  }
  if (audit.event_type === 'disagreement_detected') next.discussion_triggered = audit.details.has_disagreement === true;
  if (audit.event_type === 'report_saved') next.report_ready = true;
  if (audit.event_type === 'cancel_requested') { next.cancel_requested = true; next.status = 'cancel_requested'; }
  if (audit.event_type === 'run_finished') {
    const status = audit.details.status;
    if (['completed', 'incomplete', 'failed', 'cancelled'].includes(String(status))) next.status = status as Run['status'];
  }
  return next;
}

export function useRun(id: string) {
  const client = useQueryClient();
  return useQuery({
    queryKey: ['run', id], queryFn: async () => {
      const fresh = await api.run(id);
      const current = client.getQueryData<Run>(['run', id]);
      return current && current.last_seq > fresh.last_seq ? current : fresh;
    },
    refetchInterval: query => query.state.data && !isTerminal(query.state.data.status) ? 1800 : false,
  });
}

export function useRunEvents(id: string) {
  const client = useQueryClient();
  const [events, dispatch] = useReducer(mergeEvents, []);
  const [connection, setConnection] = useState<'connecting' | 'connected' | 'reconnecting' | 'synced' | 'offline'>('connecting');
  const [retry, setRetry] = useState(0);
  const last = useRef(0);
  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let disconnectedAt = Date.now();
    last.current = 0;
    const receive = (batch: RunEvent[]) => {
      if (disposed || !batch.length) return;
      dispatch(batch);
      for (const event of batch) {
        last.current = Math.max(last.current, event.seq);
        client.setQueryData<Run>(['run', id], current => current ? applyEvent(current, event) : current);
      }
      const final = batch.some(event => ['run.completed', 'run.failed', 'run.cancelled'].includes(event.type));
      if (final) {
        void client.invalidateQueries({ queryKey: ['run', id] });
        void client.invalidateQueries({ queryKey: ['runs'] });
      }
    };
    const catchUp = async () => {
      let more = true;
      while (more && !disposed) {
        const page = await api.events(id, last.current);
        receive(page.events);
        more = page.events.length === 500;
      }
    };
    const reconnect = () => {
      if (disposed) return;
      if (Date.now() - disconnectedAt > 30000) { setConnection('offline'); return; }
      setConnection('reconnecting');
      timer = setTimeout(() => void connect(), Math.min(500 * 2 ** attempts++, 10000) * (1 + Math.random() * .15));
    };
    const connect = async () => {
      try {
        await catchUp();
        if (disposed) return;
        socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/runs/${encodeURIComponent(id)}/events?after_seq=${last.current}`);
        socket.onopen = () => { if (!disposed) setConnection('connected'); };
        socket.onmessage = message => {
          if (disposed) return;
          try {
            const raw: unknown = JSON.parse(String(message.data));
            if (typeof raw === 'object' && raw && 'type' in raw && raw.type === 'heartbeat') return;
            const parsed = eventSchema.safeParse(raw);
            if (!parsed.success) { setConnection('offline'); socket?.close(); return; }
            if (parsed.data.seq > last.current + 1) void catchUp().catch(() => setConnection('reconnecting'));
            receive([parsed.data]);
            disconnectedAt = Date.now(); attempts = 0;
          } catch { setConnection('offline'); socket?.close(); }
        };
        socket.onerror = () => { /* onclose performs bounded recovery. */ };
        socket.onclose = async () => {
          if (disposed) return;
          try {
            const fresh = await api.run(id);
            client.setQueryData(['run', id], fresh);
            if (isTerminal(fresh.status)) { await catchUp(); if (!disposed) setConnection('synced'); return; }
          } catch { /* show bounded reconnect, never infer a terminal result */ }
          reconnect();
        };
      } catch { reconnect(); }
    };
    void connect();
    return () => { disposed = true; clearTimeout(timer); if (socket) { socket.onclose = null; socket.close(); } };
  }, [id, retry, client]);
  return { events, connection, reconnect: () => { setConnection('connecting'); setRetry(value => value + 1); } };
}
