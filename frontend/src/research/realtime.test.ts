import { describe, expect, it } from 'vitest';
import contract from '../../tests/fixtures/research-contract.json';
import { auditEventSchema, caseSchema, modelStatusSchema, reportSchema, runSchema } from './schemas';
import { emptyBuffer, newerSnapshot, reconcileEvents } from './realtime';

const events = contract.events.map(event => auditEventSchema.parse(event));
const runId = contract.run.run_id;

describe('v2 API contract', () => {
  it('accepts actual persisted backend output including dynamic agents and evidence', () => {
    contract.cases.forEach(item => expect(caseSchema.safeParse(item).success).toBe(true));
    expect(runSchema.parse(contract.run).agents).toHaveLength(4);
    const report = reportSchema.parse(contract.report);
    expect(report.routing.selected_agents).toEqual(['oncology', 'radiology']);
    expect(report.case_snapshot.timeline).toHaveLength(2);
    expect(report.final_decision).toBe('NEED_MORE_INFORMATION');
    expect(modelStatusSchema.parse(contract.model).has_api_key).toBe(false);
  });
  it('refuses invalid decision labels and non-scalar facts', () => {
    expect(reportSchema.safeParse({ ...contract.report, final_decision: 'PRESCRIBE' }).success).toBe(false);
    const item = structuredClone(contract.cases[0]);
    const bad = { ...item, timeline: [{ ...item.timeline[0], facts: { nested: { unsupported: true } } }] };
    expect(caseSchema.safeParse(bad).success).toBe(false);
  });
});

describe('contiguous SSE recovery', () => {
  it('does not acknowledge a high sequence when gap recovery fails', () => {
    let buffer = reconcileEvents(emptyBuffer(runId), [events[0], events[3]]);
    expect(buffer.cursor).toBe(1);
    expect(buffer.pending.size).toBe(1);
    // No incoming batch represents a failed HTTP gap fetch; the cursor stays at 1.
    buffer = reconcileEvents(buffer, []);
    expect(buffer.cursor).toBe(1);
    buffer = reconcileEvents(buffer, [events[1], events[2], events[3]]);
    expect(buffer.cursor).toBe(4);
    expect(buffer.events.map(event => event.seq)).toEqual([1, 2, 3, 4]);
  });
  it('deduplicates SSE delivery and REST replay without accepting another run', () => {
    let buffer = reconcileEvents(emptyBuffer(runId), events);
    buffer = reconcileEvents(buffer, [...events, { ...events[0], run_id: 'other', seq: 999 }]);
    expect(buffer.cursor).toBe(events.length);
    expect(buffer.events).toHaveLength(events.length);
    expect(buffer.pending.size).toBe(0);
  });
  it('keeps a monotonic snapshot after a slow REST response', () => {
    const current = runSchema.parse(contract.run);
    const stale = { ...current, last_seq: current.last_seq - 1, status: 'running' };
    expect(newerSnapshot(current, stale)).toBe(current);
  });
  it('bounds visible history while preserving the acknowledged cursor', () => {
    const batch = Array.from({ length: 520 }, (_, index) => ({ ...events[0], seq: index + 1 }));
    const buffer = reconcileEvents(emptyBuffer(runId), batch);
    expect(buffer.cursor).toBe(520);
    expect(buffer.events).toHaveLength(500);
    expect(buffer.events[0].seq).toBe(21);
  });
});
