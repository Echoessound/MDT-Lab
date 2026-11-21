import type { ResearchCase } from './schemas';

/** The case API returns events in (date, event_id) order, including same-day events. */
export function inputThroughTrigger(source: ResearchCase, triggerId: string): ResearchCase | undefined {
  const index = source.timeline.findIndex(event => event.event_id === triggerId);
  if (index < 0) return undefined;
  return { ...source, timeline: source.timeline.slice(0, index + 1), unplaced_records: [] };
}
