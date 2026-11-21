import { describe, expect, it } from 'vitest';
import contract from '../../tests/fixtures/dataset-contract.json';
import { inputThroughTrigger } from './run-input';
import { caseSchema, datasetCatalogSchema, importBatchSchema, importPreviewSchema, reportSchema, runSchema } from './schemas';

describe('external dataset API to agent workspace contract', () => {
  it('parses public and mixed cases without dropping provenance or related information', () => {
    const source = caseSchema.parse(contract.case);
    expect(source.case_kind).toBe('public_research');
    expect(source.unplaced_records).toHaveLength(2);
    expect(source.provenance[0].artifact_sha256).toBe(contract.preview.artifact_sha256);
    expect(source.timeline[0].source_fields.recorded_date).toBe('CT Date');
    expect(caseSchema.parse(contract.mixed).case_kind).toBe('mixed');
  });
  it('accepts actual preview, committed batch and persisted catalog output', () => {
    expect(importPreviewSchema.parse(contract.preview).case_count).toBe(1);
    expect(importBatchSchema.parse(contract.batch).imported_case_ids).toEqual([contract.case.case_id]);
    expect(datasetCatalogSchema.parse(contract.catalog).sources).toHaveLength(3);
  });
  it('renders the same frozen input in the console as in the saved report', () => {
    const source = caseSchema.parse(contract.case);
    const report = reportSchema.parse(contract.report);
    expect(inputThroughTrigger(source, report.trigger_event_id)).toEqual(report.case_snapshot);
    expect(inputThroughTrigger(source, 'absent')).toBeUndefined();
    expect(source.unplaced_records).toHaveLength(2);
  });
  it('carries frozen evidence from imported data through agents and reports', () => {
    const run = runSchema.parse(contract.run);
    const report = reportSchema.parse(contract.report);
    expect(run.agents.filter(agent => agent.status === 'completed')).toHaveLength(2);
    expect(report.case_snapshot.timeline).toHaveLength(1);
    expect(report.case_snapshot.unplaced_records).toEqual([]);
    expect(report.evidence_registry[0].source_record_locator).toContain('clinical.csv');
    expect(report.evidence_registry[0].artifact_sha256).toBe(contract.preview.artifact_sha256);
    expect(report.final_decision).toBe('NEED_MORE_INFORMATION');
  });
});
