import type { RoleCategory } from '../types';

export function normalizeRoleValue(value?: string | null): string {
  const raw = String(value ?? '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  if (!raw) return 'employee';
  if (raw === 'delivery_head' || raw === 'studio_head') return 'studio_head';
  if (raw === 'program_director' || raw === 'program_manager') return 'program_manager';
  if (raw === 'project_director' || raw === 'project_manager') return 'project_manager';
  if (raw === 'team_lead' || raw === 'architect') return 'team_lead';
  if (raw === 'developer' || raw === 'intern' || raw === 'qa' || raw === 'devops') return raw;
  return raw;
}

export function mapRoleCategory(role?: string | null, department?: string): RoleCategory {
  const normalized = normalizeRoleValue(role);

  if (normalized === 'studio_head' || normalized === 'delivery_head') return 'Studio Head';
  if (normalized === 'program_manager' || normalized === 'program_director') return 'Program Manager';
  if (normalized === 'project_manager' || normalized === 'project_director') return 'Manager';
  if (normalized === 'team_lead') return 'Architect';
  if (normalized === 'qa') return 'QA';
  if (normalized === 'devops') return 'DevOps';
  if (normalized === 'intern') return 'Intern';

  if (department === 'Quality Assurance') return 'QA';
  if (department === 'Platform' || department === 'DevOps') return 'DevOps';
  return 'Developer';
}

export function getPreviewRoleForUser(roleCategory?: string | null): 'employee' | 'manager' | 'project_director' | 'studio_head' {
  const category = String(roleCategory ?? '').trim();
  if (category === 'Studio Head') return 'studio_head';
  if (category === 'Program Manager') return 'manager';
  if (category === 'Manager') return 'manager';
  return 'employee';
}

export function isStudioHeadRole(role?: string | null): boolean {
  return normalizeRoleValue(role) === 'studio_head';
}

export function isManagerRole(role?: string | null): boolean {
  const normalized = normalizeRoleValue(role);
  return normalized === 'program_manager' || normalized === 'project_manager' || normalized === 'studio_head';
}
