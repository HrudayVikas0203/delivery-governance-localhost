import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tracker = readFileSync(new URL('../src/pages/TaskTracker.tsx', import.meta.url), 'utf8');
const api = readFileSync(new URL('../src/services/api.ts', import.meta.url), 'utf8');

test('task form has one required Assigned To field and no legacy multi-assignee UI', () => {
  assert.match(tracker, /aria-label="Assigned To" required/);
  assert.doesNotMatch(tracker, /Primary assignee|Additional assignees|extraAssigneeIds|assignee_ids/);
  assert.match(tracker, /No eligible developers\/testers are allocated to this project/);
});

test('Kanban restores the previous state when the backend rejects a move', () => {
  assert.match(tracker, /const previousStatus = task\.status/);
  assert.match(tracker, /status: previousStatus/);
  assert.match(tracker, /The change was reverted/);
  assert.match(tracker, /apiUpdateTaskStatus/);
});

test('frontend exposes only forward workflow destinations', () => {
  assert.match(tracker, /todo: \['in_progress', 'blocked'\]/);
  assert.match(tracker, /in_progress: \['review', 'blocked'\]/);
  assert.match(tracker, /review: \['blocked', 'done'\]/);
  assert.match(tracker, /blocked: \['done'\]/);
  assert.doesNotMatch(tracker, /'unblock'/);
});

test('task history and persisted notifications use backend APIs', () => {
  assert.match(api, /\/tasks\/\$\{taskId\}\/history/);
  assert.match(api, /request<any\[]>\('\/notifications'/);
  assert.match(api, /\/notifications\/read-all/);
});
