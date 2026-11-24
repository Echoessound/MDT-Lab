import { describe, expect, it } from 'vitest';
import { selectedModelsReady } from './model-settings';
import { agentModelSchema, modelProfileSchema, modelSnapshotSchema, runSchema } from './schemas';
import contract from '../../tests/fixtures/research-contract.json';

const configured = agentModelSchema.parse({ ...contract.model, agent_id: 'oncology', configured: true, has_api_key: true, configuration_source: 'agent', overridden: true });
describe('per-agent configuration readiness', () => {
  it('requires effective configurations for exactly the participating agents', () => {
    expect(selectedModelsReady(['oncology'], [configured])).toBe(true);
    expect(selectedModelsReady(['oncology', 'radiology'], [configured])).toBe(false);
    expect(selectedModelsReady([], [configured])).toBe(false);
    expect(selectedModelsReady(undefined, undefined)).toBe(false);
    expect(selectedModelsReady(['oncology'], [{ ...configured, configured: false }])).toBe(false);
  });
  it('keeps historical runs readable and strips credentials from public provenance', () => {
    expect(runSchema.parse(contract.run).model_configuration).toEqual([]);
    const snapshot = modelSnapshotSchema.parse({ ...configured, api_key: 'must-not-enter-ui-state' });
    expect('api_key' in snapshot).toBe(false);
    expect(snapshot.agent_id).toBe('oncology');
  });
  it('retains profile identity in connection cards and frozen runs', () => {
    const profile = { ...configured, profile_id: 'p_123', name: '对照模型', api_key: 'test-only-secret' };
    const card = modelProfileSchema.parse(profile);
    expect(card.name).toBe('对照模型');
    expect(card).not.toHaveProperty('api_key');
    const source = { ...profile, profile_name: card.name, configuration_source: 'default', overridden: false };
    expect(agentModelSchema.parse(source)).toMatchObject({ profile_id: card.profile_id, overridden: false });
    expect(modelSnapshotSchema.parse(source)).toMatchObject({ profile_id: card.profile_id, profile_name: card.name });
  });
});
