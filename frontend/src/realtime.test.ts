import { describe, expect, it } from 'vitest';
import { applyEvent, mergeEvents } from './realtime';
import { caseSchema, eventSchema, runSchema, reportSchema, type RunEvent } from './schemas';
import contract from '../tests/fixtures/contract.json';

describe('Pydantic / Zod contract', () => {
  it('accepts real API output for case, snapshot, audit and report', () => {
    expect(caseSchema.parse(contract.case).is_synthetic).toBe(true);
    expect(runSchema.parse(contract.run).status).toBe('completed');
    expect(reportSchema.parse(contract.report).final_decision).toBe('NEED_MORE_INFORMATION');
    contract.events.forEach(event => expect(eventSchema.safeParse(event).success).toBe(true));
  });
  it('rejects real-data flag, unknown label and report disclaimer drift', () => {
    expect(caseSchema.safeParse({ ...contract.case, is_synthetic: false }).success).toBe(false);
    expect(reportSchema.safeParse({ ...contract.report, final_decision: 'PRESCRIBE' }).success).toBe(false);
    expect(reportSchema.safeParse({ ...contract.report, disclaimer: '' }).success).toBe(false);
  });
});

describe('recoverable event stream', () => {
  const events: RunEvent[] = contract.events.map(event => eventSchema.parse(event));
  it('deduplicates replayed events and orders an out-of-order recovery', () => {
    const result = mergeEvents([events[2], events[0]], [events[1], events[2]]);
    expect(result.map(event => event.seq)).toEqual([1, 2, 3]);
  });
  it('bounds browser audit memory without losing newest events', () => {
    const many = Array.from({ length: 520 }, (_, index) => ({ ...events[0], seq: index + 1 }));
    const result = mergeEvents([], many);
    expect(result).toHaveLength(500);
    expect(result[0].seq).toBe(21);
    expect(result.at(-1)?.seq).toBe(520);
  });
  it('does not regress state when an older event is replayed', () => {
    const run = runSchema.parse(contract.run);
    expect(applyEvent(run, events[0])).toBe(run);
  });
  it('cannot inject another run into the current snapshot', () => {
    const run = runSchema.parse(contract.run);
    expect(applyEvent(run, { ...events[0], run_id: 'run_other', seq: 999 })).toBe(run);
  });
  it('replays a complete workflow with real opinion changes', () => {
    const run = runSchema.parse(contract.initial);
    const final = events.reduce(applyEvent, run);
    expect(final.status).toBe('completed');
    expect(final.report_ready).toBe(true);
    expect(final.agents.surgery.previous_opinion?.decision).toBe('READY_FOR_REVIEW');
    expect(final.agents.surgery.opinion?.decision).toBe('NEED_MORE_INFORMATION');
  });
});
