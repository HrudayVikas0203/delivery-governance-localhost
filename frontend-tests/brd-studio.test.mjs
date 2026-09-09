import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const studio = readFileSync(new URL('../src/pages/BRDStudio.tsx', import.meta.url), 'utf8');
const flow = readFileSync(new URL('../src/components/BusinessFlowWorkspace.tsx', import.meta.url), 'utf8');
const architecture = readFileSync(new URL('../src/components/ArchitectureWorkspace.tsx', import.meta.url), 'utf8');

test('BRD Studio never presents raw artifact payloads', () => {
  const visibleSources = `${studio}\n${flow}\n${architecture}`;
  assert.doesNotMatch(visibleSources, /Payload Preview/i);
  assert.doesNotMatch(visibleSources, /JSON\.stringify\s*\(\s*artifact\.payload/);
  assert.doesNotMatch(visibleSources, /Payload saved in/i);
});

test('business flow uses valid SVG paint and directional connectors', () => {
  assert.match(flow, /markerEnd=/);
  assert.match(flow, /<path d=/);
  assert.match(flow, /fill: '#eff6ff'/);
  assert.doesNotMatch(flow, /fill=\{[^}]*\.bg\}/);
  assert.match(flow, /business_rule/);
  assert.match(flow, /inputs/);
  assert.match(flow, /outputs/);
  assert.match(flow, /measuredHeight/);
  assert.match(flow, /payload\.steps/);
  assert.match(flow, /payload\.transitions/);
  assert.match(flow, /exceptionMarkerId/);
});

test('architecture renders component relationships from both supported payload keys', () => {
  assert.match(architecture, /payload\.relationships/);
  assert.match(architecture, /payload\.connections/);
  assert.match(architecture, /markerEnd=/);
  assert.match(architecture, /external_systems/);
  assert.match(architecture, /cross_cutting_concerns/);
  assert.match(architecture, /nfr_alignment/);
  assert.match(architecture, /payload\.assumptions/);
  assert.match(architecture, /payload\.trade_offs/);
  assert.match(architecture, /component\.id/);
  assert.match(architecture, /bandHeight/);
  assert.match(architecture, /External systems/);
});

test('architecture omits unavailable supporting sections and does not fabricate objectives', () => {
  assert.match(architecture, /Architecture objective not specified/);
  assert.match(architecture, /nfrs\.length > 0/);
  assert.match(architecture, /assumptions\.length > 0/);
  assert.doesNotMatch(architecture, /Layered architecture generated from the selected project/);
});

test('upload control exposes supported formats and a real loading state', () => {
  assert.match(studio, /accept="\.pdf,\.docx,\.txt,\.md"/);
  assert.match(studio, /apiUploadBRDDocument\(formData, authToken\)/);
  assert.match(studio, /isUploading \? 'Uploading…' : 'Upload'/);
});
