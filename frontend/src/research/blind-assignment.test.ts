import { expect, it } from 'vitest';
import { assignedQueue, parseBlindAssignment } from './blind-assignment';

const material = (id: string) => JSON.stringify({
  scenario_id: id, input_sha256: 'a'.repeat(64), events: [{
    event_id: 'E1', occurred_at: '2020-02-05', event_type: 'imaging', title: '检查', facts: { documented: true },
  }],
});
const task = (id: string) => ({
  scenario_id: id, case_id: id, case_version: 1, trigger_event_id: 'E1',
  submission_count: 0, own_submitted: false, adjudicated: false,
});

it('restricts the queue to the ordered assignment and refuses partial matches', () => {
  const assignment = parseBlindAssignment([material('B'), material('A')].join('\n'), 'dev.jsonl');
  const tasks = ['A', 'C', 'B'].map(task);
  expect(assignedQueue(tasks, assignment).queue.map(t => t.scenario_id)).toEqual(['B', 'A']);
  const incomplete = assignedQueue(tasks.slice(0, 1), assignment);
  expect(incomplete.queue).toEqual([]);
  expect(incomplete.error).toContain('B');
  expect(JSON.stringify(assignment)).not.toContain('documented');
});

it('rejects duplicate IDs, invalid material and empty assignments', () => {
  for (const file of [[material('A'), material('A')].join('\n'), '{}', ' ']) {
    expect(() => parseBlindAssignment(file, 'a.jsonl')).toThrow();
  }
});
