import { blindMaterialSchema, type ReviewPanelTask } from './schemas';

export type BlindAssignment = { name: string; entries: [string, string][] };
const sessionKey = 'mdt-blind-assignment-v1';

export function parseBlindAssignment(text: string, name: string): BlindAssignment {
  const hashes = new Map<string, string>();
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let material;
    try {
      material = blindMaterialSchema.parse(JSON.parse(line));
    } catch {
      throw new Error(`第 ${index + 1} 行缺少有效的盲标材料、场景编号或指纹。`);
    }
    if (hashes.has(material.scenario_id)) throw new Error(`第 ${index + 1} 行的场景编号重复。`);
    hashes.set(material.scenario_id, material.input_sha256);
  }
  if (!hashes.size) throw new Error('任务文件为空。');
  return { name, entries: [...hashes] };
}

export function assignedQueue(tasks: ReviewPanelTask[], assignment: BlindAssignment) {
  const available = new Map(tasks.map(task => [task.scenario_id, task]));
  const queue: ReviewPanelTask[] = [];
  for (const [id] of assignment.entries) {
    const task = available.get(id);
    if (!task) return { queue: [], error: `研究库任务队列缺少 ${id}，请核对导入批次和病例版本。` };
    queue.push(task);
  }
  return { queue, error: '' };
}

export function restoreAssignment(): BlindAssignment | null {
  try {
    const item = JSON.parse(sessionStorage.getItem(sessionKey) || 'null');
    if (typeof item?.name === 'string' && Array.isArray(item.entries) && item.entries.length &&
        item.entries.every((e: unknown) => Array.isArray(e) && e.length === 2 &&
          typeof e[0] === 'string' && typeof e[1] === 'string' && /^[a-f0-9]{64}$/.test(e[1]))) return item;
  } catch { /* Restricted browser storage or an expired session. */ }
  return null;
}

export function rememberAssignment(assignment: BlindAssignment | null) {
  try {
    if (assignment) sessionStorage.setItem(sessionKey, JSON.stringify(assignment));
    else sessionStorage.removeItem(sessionKey);
  } catch { /* The in-memory selection still applies in this tab. */ }
}
