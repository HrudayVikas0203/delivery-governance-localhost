import { useState } from 'react';
import {
  AlertCircle,
  Bot,
  Boxes,
  Cloud,
  Database,
  Download,
  Eye,
  Globe2,
  KeyRound,
  Network,
  Radio,
  Server,
  ShieldCheck,
} from 'lucide-react';
import type {
  ArchitectureComponent,
  ArchitectureLayer,
  ArchitecturePayload,
  ArchitectureRelationship,
  BRDArtifact,
} from '../types';

const COLUMN_WIDTH = 308;
const COLUMN_GAP = 58;
const COMPONENT_WIDTH = 264;
const COMPONENT_HEIGHT = 126;
const COMPONENT_GAP = 22;
const CANVAS_PADDING = 42;
const HEADER_HEIGHT = 74;

type Palette = { fill: string; soft: string; border: string; accent: string; label: string };
type PositionedComponent = { name: string; x: number; y: number; width: number; height: number };

const layerPalettes: Palette[] = [
  { fill: '#fff7ed', soft: '#ffedd5', border: '#fb923c', accent: '#c2410c', label: 'External' },
  { fill: '#f5f3ff', soft: '#ede9fe', border: '#8b5cf6', accent: '#6d28d9', label: 'Experience' },
  { fill: '#eff6ff', soft: '#dbeafe', border: '#3b82f6', accent: '#1d4ed8', label: 'Application' },
  { fill: '#ecfeff', soft: '#cffafe', border: '#06b6d4', accent: '#0e7490', label: 'Services' },
  { fill: '#f0fdf4', soft: '#dcfce7', border: '#22c55e', accent: '#15803d', label: 'Data' },
  { fill: '#f8fafc', soft: '#e2e8f0', border: '#64748b', accent: '#334155', label: 'Platform' },
];

function clean(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeComponent(value: unknown): ArchitectureComponent | null {
  if (typeof value === 'string' && value.trim()) return { name: value.trim() };
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const name = clean(item.name);
  if (!name) return null;
  return {
    name,
    type: clean(item.type),
    responsibility: clean(item.responsibility),
    technology: clean(item.technology),
    description: clean(item.description),
  };
}

function normalizeLayer(value: unknown): ArchitectureLayer | null {
  if (!value || typeof value !== 'object') return null;
  const layer = value as Record<string, unknown>;
  const name = clean(layer.name);
  const components = (Array.isArray(layer.components) ? layer.components : []).map(normalizeComponent).filter((item): item is ArchitectureComponent => Boolean(item));
  if (!name || components.length === 0) return null;
  return {
    name,
    purpose: clean(layer.purpose || layer.description),
    securityBoundary: clean(layer.securityBoundary || layer.security_boundary),
    components,
  };
}

function normalizeRelationship(value: unknown): ArchitectureRelationship | null {
  if (!value || typeof value !== 'object') return null;
  const relationship = value as Record<string, unknown>;
  const source = clean(relationship.source || relationship.from);
  const target = clean(relationship.target || relationship.to);
  if (!source || !target) return null;
  return {
    source,
    target,
    label: clean(relationship.label),
    protocol: clean(relationship.protocol),
    type: clean(relationship.type),
  };
}

function paletteForLayer(name: string, index: number, external = false): Palette {
  if (external) return layerPalettes[0];
  const value = name.toLowerCase();
  if (/experience|presentation|channel|user|front/.test(value)) return layerPalettes[1];
  if (/application|api|gateway|interface/.test(value)) return layerPalettes[2];
  if (/business|service|domain|integration|event|messag|ai/.test(value)) return layerPalettes[3];
  if (/data|database|storage|information|analytics/.test(value)) return layerPalettes[4];
  if (/cloud|platform|infrastructure|deployment|runtime/.test(value)) return layerPalettes[5];
  return layerPalettes[1 + (index % (layerPalettes.length - 1))];
}

function componentIcon(component: ArchitectureComponent) {
  const value = `${component.type || ''} ${component.name} ${component.technology || ''}`.toLowerCase();
  if (/database|data store|sql|warehouse|lake|cache/.test(value)) return Database;
  if (/external|partner|third.party|erp|crm/.test(value)) return Globe2;
  if (/ai|ml|llm|gemini|model/.test(value)) return Bot;
  if (/identity|auth|iam|security/.test(value)) return KeyRound;
  if (/event|queue|message|stream|bus/.test(value)) return Radio;
  if (/cloud|container|kubernetes|infrastructure/.test(value)) return Cloud;
  if (/api|gateway|integration/.test(value)) return Network;
  if (/server|service|backend/.test(value)) return Server;
  return Boxes;
}

function ComponentCard({ component, palette, external }: { component: ArchitectureComponent; palette: Palette; external?: boolean }) {
  const Icon = componentIcon(component);
  const detail = clean(component.responsibility || component.description);
  return (
    <div
      style={{
        height: '100%', boxSizing: 'border-box', border: `${external ? '2px dashed' : '1.5px solid'} ${palette.border}`,
        borderRadius: 12, background: '#ffffff', boxShadow: '0 7px 18px rgba(15, 23, 42, 0.08)',
        padding: '13px 14px', overflow: 'hidden', fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 9 }}>
        <div style={{ display: 'flex', width: 29, height: 29, flex: '0 0 auto', alignItems: 'center', justifyContent: 'center', borderRadius: 8, background: palette.soft, color: palette.accent }}><Icon size={16} /></div>
        <div style={{ minWidth: 0 }}><div style={{ color: '#0f172a', fontSize: 13, fontWeight: 800, lineHeight: 1.25 }}>{component.name}</div>{clean(component.type) && <div style={{ marginTop: 3, color: palette.accent, fontSize: 8.5, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase' }}>{component.type}</div>}</div>
      </div>
      {detail && <div style={{ marginTop: 8, color: '#475569', fontSize: 9.5, lineHeight: 1.35 }}>{detail}</div>}
      {clean(component.technology) && <div style={{ marginTop: 8, display: 'inline-block', borderRadius: 999, background: palette.soft, color: palette.accent, padding: '3px 8px', fontSize: 8.5, fontWeight: 700 }}>{component.technology}</div>}
    </div>
  );
}

function connectionPath(source: PositionedComponent, target: PositionedComponent): string {
  const forward = target.x >= source.x;
  const x1 = forward ? source.x + source.width : source.x;
  const x2 = forward ? target.x : target.x + target.width;
  const y1 = source.y + source.height / 2;
  const y2 = target.y + target.height / 2;
  const bend = x1 + (x2 - x1) / 2;
  return `M ${x1} ${y1} C ${bend} ${y1}, ${bend} ${y2}, ${x2} ${y2}`;
}

interface ArchitectureWorkspaceProps {
  artifact: BRDArtifact | undefined;
  onExport: (format: 'pdf' | 'docx' | 'png' | 'drawio') => void;
  isExporting?: boolean;
}

export default function ArchitectureWorkspace({ artifact, onExport, isExporting }: ArchitectureWorkspaceProps) {
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);

  if (!artifact) {
    return <div className="flex flex-col items-center justify-center py-24 text-center"><div className="mb-4 rounded-full bg-cyan-50 p-6"><AlertCircle size={32} className="text-cyan-600" /></div><p className="text-lg font-semibold text-ink">No architecture generated yet</p><p className="mt-2 text-sm text-ink-soft">Generate an architecture from the selected BRD and requirements.</p></div>;
  }

  const payload = (artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {}) as ArchitecturePayload;
  const layers = (Array.isArray(payload.layers) ? payload.layers : []).map(normalizeLayer).filter((layer): layer is ArchitectureLayer => Boolean(layer));
  const externalComponents = (Array.isArray(payload.external_systems) ? payload.external_systems : []).map(normalizeComponent).filter((component): component is ArchitectureComponent => Boolean(component));
  const rawRelationships = [
    ...(Array.isArray(payload.relationships) ? payload.relationships : []),
    ...(Array.isArray(payload.connections) ? payload.connections : []),
  ];
  const relationships = rawRelationships.map(normalizeRelationship).filter((relationship): relationship is ArchitectureRelationship => Boolean(relationship));

  const columns = [
    ...(externalComponents.length ? [{ name: 'External systems', purpose: 'Connected platforms and actors', components: externalComponents, external: true }] : []),
    ...layers.map((layer) => ({ ...layer, components: (layer.components || []) as ArchitectureComponent[], external: false })),
  ];
  const maxComponents = Math.max(...columns.map((column) => column.components.length), 1);
  const canvasWidth = Math.max(820, CANVAS_PADDING * 2 + columns.length * COLUMN_WIDTH + Math.max(0, columns.length - 1) * COLUMN_GAP);
  const canvasHeight = CANVAS_PADDING * 2 + HEADER_HEIGHT + maxComponents * COMPONENT_HEIGHT + Math.max(0, maxComponents - 1) * COMPONENT_GAP + 34;
  const positioned = new Map<string, PositionedComponent>();
  columns.forEach((column, columnIndex) => {
    const x = CANVAS_PADDING + columnIndex * (COLUMN_WIDTH + COLUMN_GAP) + (COLUMN_WIDTH - COMPONENT_WIDTH) / 2;
    column.components.forEach((component, componentIndex) => {
      positioned.set(component.name.toLowerCase(), { name: component.name, x, y: CANVAS_PADDING + HEADER_HEIGHT + 18 + componentIndex * (COMPONENT_HEIGHT + COMPONENT_GAP), width: COMPONENT_WIDTH, height: COMPONENT_HEIGHT });
    });
  });

  const decisions = (Array.isArray(payload.decisions) ? payload.decisions : []).map((value) => typeof value === 'string' ? { decision: value } : value).filter((value) => value && clean(value.decision));
  const risks = (Array.isArray(payload.risks) ? payload.risks : []).map((value) => typeof value === 'string' ? { description: value } : value).filter((value) => value && clean(value.description));
  const security = (Array.isArray(payload.security) ? payload.security : []).map(clean).filter(Boolean);
  const deployment = (Array.isArray(payload.deployment) ? payload.deployment : []).map(clean).filter(Boolean);
  const concerns = payload.cross_cutting_concerns && typeof payload.cross_cutting_concerns === 'object' ? Object.entries(payload.cross_cutting_concerns).filter(([name]) => clean(name)) : [];
  const markerId = `architecture-arrow-${artifact.id.replace(/[^a-zA-Z0-9]/g, '')}`;
  const patternId = `architecture-grid-${artifact.id.replace(/[^a-zA-Z0-9]/g, '')}`;

  const handleExport = (format: 'pdf' | 'docx' | 'png' | 'drawio') => {
    setExportingFormat(format);
    onExport(format);
    window.setTimeout(() => setExportingFormat(null), 1800);
  };

  if (columns.length === 0) {
    return <div className="flex flex-col items-center justify-center py-24 text-center"><AlertCircle size={32} className="mb-4 text-cyan-600" /><p className="text-lg font-semibold text-ink">No valid architecture components were generated</p><p className="mt-2 text-sm text-ink-soft">Regenerate after confirming the BRD includes solution or integration context.</p></div>;
  }

  return (
    <div className="space-y-5">
      <header className="rounded-xl border border-slate-700 bg-gradient-to-r from-slate-950 via-blue-950 to-indigo-950 p-6 text-white shadow-sm">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div><p className="text-[10px] font-bold uppercase tracking-[0.22em] text-blue-200">Enterprise solution blueprint</p><h2 className="mt-2 text-2xl font-bold">{clean(payload.title) || artifact.title || 'Solution Architecture'}</h2>{clean(payload.subtitle) && <p className="mt-2 text-sm font-medium text-blue-100">{payload.subtitle}</p>}<p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-300">{clean(payload.objective || payload.summary) || 'Layered architecture generated from the selected project, BRD, and requirement context.'}</p></div>
          <div className="grid shrink-0 grid-cols-3 gap-2"><div className="rounded-lg border border-white/15 bg-white/10 px-3 py-3 text-center"><strong className="block text-lg">{layers.length}</strong><span className="text-[9px] uppercase text-slate-300">Layers</span></div><div className="rounded-lg border border-white/15 bg-white/10 px-3 py-3 text-center"><strong className="block text-lg">{columns.reduce((sum, column) => sum + column.components.length, 0)}</strong><span className="text-[9px] uppercase text-slate-300">Components</span></div><div className="rounded-lg border border-white/15 bg-white/10 px-3 py-3 text-center"><strong className="block text-lg">{relationships.length}</strong><span className="text-[9px] uppercase text-slate-300">Links</span></div></div>
        </div>
      </header>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-50 shadow-inner">
        <svg width={canvasWidth} height={canvasHeight} role="img" aria-label="Enterprise solution architecture diagram">
          <defs><pattern id={patternId} width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" fill="none" stroke="#e2e8f0" strokeWidth="1" /></pattern><marker id={markerId} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" /></marker></defs>
          <rect width="100%" height="100%" fill={`url(#${patternId})`} />
          {columns.map((column, columnIndex) => {
            const x = CANVAS_PADDING + columnIndex * (COLUMN_WIDTH + COLUMN_GAP);
            const palette = paletteForLayer(column.name, columnIndex, column.external);
            return <g key={`${column.name}-${columnIndex}`}><rect x={x} y={CANVAS_PADDING} width={COLUMN_WIDTH} height={canvasHeight - CANVAS_PADDING * 2} rx="16" fill={palette.fill} stroke={palette.border} strokeWidth="1.5" strokeDasharray={column.external ? '8 5' : undefined} /><rect x={x} y={CANVAS_PADDING} width={COLUMN_WIDTH} height={HEADER_HEIGHT} rx="16" fill={palette.soft} /><rect x={x} y={CANVAS_PADDING + HEADER_HEIGHT - 16} width={COLUMN_WIDTH} height="16" fill={palette.soft} /><text x={x + 18} y={CANVAS_PADDING + 27} fill={palette.accent} fontSize="11" fontWeight="800" letterSpacing="1.1">{(column.external ? 'SOURCE / EXTERNAL' : `LAYER ${String(columnIndex + (externalComponents.length ? 0 : 1)).padStart(2, '0')}`).toUpperCase()}</text><text x={x + 18} y={CANVAS_PADDING + 50} fill="#0f172a" fontSize="15" fontWeight="800">{column.name.slice(0, 34)}</text>{columnIndex < columns.length - 1 && <path d={`M ${x + COLUMN_WIDTH + 12} ${CANVAS_PADDING + 37} L ${x + COLUMN_WIDTH + COLUMN_GAP - 12} ${CANVAS_PADDING + 37}`} stroke="#64748b" strokeWidth="2" markerEnd={`url(#${markerId})`} />}</g>;
          })}
          {relationships.map((relationship, index) => {
            const source = positioned.get(clean(relationship.source || relationship.from).toLowerCase());
            const target = positioned.get(clean(relationship.target || relationship.to).toLowerCase());
            if (!source || !target) return null;
            const label = clean(relationship.label || relationship.protocol || relationship.type);
            const labelX = (source.x + source.width + target.x) / 2; const labelY = (source.y + target.y) / 2 + COMPONENT_HEIGHT / 2 - 7;
            return <g key={`${source.name}-${target.name}-${index}`}><path d={connectionPath(source, target)} fill="none" stroke="#475569" strokeWidth="2.1" markerEnd={`url(#${markerId})`} />{label && <g><rect x={labelX - Math.min(78, label.length * 3.2)} y={labelY - 13} width={Math.min(156, Math.max(56, label.length * 6.4))} height="22" rx="11" fill="white" stroke="#cbd5e1" /><text x={labelX} y={labelY + 2} textAnchor="middle" fill="#334155" fontSize="9.5" fontWeight="700">{label.slice(0, 26)}</text></g>}</g>;
          })}
          {columns.flatMap((column, columnIndex) => { const palette = paletteForLayer(column.name, columnIndex, column.external); return column.components.map((component) => { const position = positioned.get(component.name.toLowerCase())!; return <foreignObject key={`${column.name}-${component.name}`} x={position.x} y={position.y} width={position.width} height={position.height}><ComponentCard component={component} palette={palette} external={column.external} /></foreignObject>; }); })}
        </svg>
      </div>

      {(concerns.length > 0 || security.length > 0 || deployment.length > 0) && <section className="rounded-xl border border-slate-200 bg-slate-950 p-5 text-white"><div className="flex items-center gap-2"><ShieldCheck size={17} className="text-cyan-300" /><h3 className="text-sm font-bold">Cross-cutting controls and platform concerns</h3></div><div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{security.length > 0 && <article className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 p-4"><p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-emerald-200"><KeyRound size={14} /> Security</p><ul className="mt-3 space-y-1.5 text-xs text-slate-200">{security.map((item) => <li key={item}>• {item}</li>)}</ul></article>}{deployment.length > 0 && <article className="rounded-lg border border-blue-400/30 bg-blue-400/10 p-4"><p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-blue-200"><Cloud size={14} /> Deployment</p><ul className="mt-3 space-y-1.5 text-xs text-slate-200">{deployment.map((item) => <li key={item}>• {item}</li>)}</ul></article>}{concerns.map(([name, details]) => <article key={name} className="rounded-lg border border-violet-400/30 bg-violet-400/10 p-4"><p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-violet-200"><Eye size={14} /> {name}</p><div className="mt-3 text-xs leading-relaxed text-slate-200">{Array.isArray(details) ? details.map((item) => <p key={item}>• {clean(item)}</p>) : clean(details)}</div></article>)}</div></section>}

      {(decisions.length > 0 || risks.length > 0) && <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">{decisions.length > 0 && <section className="rounded-xl border border-indigo-200 bg-indigo-50 p-5"><h3 className="text-sm font-bold text-indigo-950">Architecture decisions</h3><div className="mt-3 space-y-3">{decisions.map((decision, index) => <article key={`${decision.decision}-${index}`} className="rounded-lg border border-indigo-200 bg-white p-4"><p className="text-sm font-bold text-indigo-950">{clean(decision.decision)}</p>{clean(decision.rationale) && <p className="mt-2 text-xs leading-relaxed text-indigo-800">{clean(decision.rationale)}</p>}{clean(decision.trade_offs) && <p className="mt-2 text-xs text-indigo-600"><strong>Trade-off:</strong> {clean(decision.trade_offs)}</p>}</article>)}</div></section>}{risks.length > 0 && <section className="rounded-xl border border-rose-200 bg-rose-50 p-5"><h3 className="text-sm font-bold text-rose-950">Architecture risks</h3><div className="mt-3 space-y-3">{risks.map((risk, index) => <article key={`${risk.description}-${index}`} className="rounded-lg border border-rose-200 bg-white p-4"><p className="text-sm font-bold text-rose-950">{clean(risk.description)}</p>{clean(risk.impact) && <p className="mt-2 text-xs text-rose-800"><strong>Impact:</strong> {clean(risk.impact)}</p>}{clean(risk.mitigation) && <p className="mt-1 text-xs text-rose-700"><strong>Mitigation:</strong> {clean(risk.mitigation)}</p>}</article>)}</div></section>}</div>}

      {clean(payload.so_what) && <section className="flex items-start gap-3 rounded-xl border border-cyan-200 bg-cyan-50 p-5"><ShieldCheck size={19} className="mt-0.5 shrink-0 text-cyan-700" /><div><h3 className="text-sm font-bold text-cyan-950">Executive takeaway</h3><p className="mt-1 text-sm leading-relaxed text-cyan-900">{clean(payload.so_what)}</p></div></section>}

      <section className="rounded-xl border border-border bg-surface p-5"><h3 className="flex items-center gap-2 text-sm font-bold text-ink"><Download size={16} /> Export architecture</h3><p className="mt-1 text-xs text-ink-soft">PNG and PDF provide shareable views; draw.io remains editable. DOCX includes the visual plus supporting details.</p><div className="mt-4 flex flex-wrap gap-2">{(['png', 'pdf', 'docx', 'drawio'] as const).map((format) => <button key={format} onClick={() => handleExport(format)} disabled={Boolean(isExporting && exportingFormat === format)} className="rounded-lg border border-border bg-surface-alt px-4 py-2 text-xs font-bold uppercase text-ink-soft transition hover:border-cyan-400 hover:bg-cyan-50 disabled:opacity-50">{exportingFormat === format ? 'Preparing…' : format === 'drawio' ? 'draw.io' : format}</button>)}</div></section>
    </div>
  );
}
