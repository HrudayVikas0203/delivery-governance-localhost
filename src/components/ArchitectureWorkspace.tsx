import { useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, Bot, Boxes, Cloud, Database, Download, Eye, Globe2, KeyRound, Network, Radio, Server, ShieldCheck } from 'lucide-react';
import type { ArchitectureComponent, ArchitectureLayer, ArchitecturePayload, ArchitectureRelationship, BRDArtifact } from '../types';

const LABEL_WIDTH = 190;
const COMPONENT_WIDTH = 246;
const MIN_COMPONENT_HEIGHT = 132;
const COMPONENT_GAP = 30;
const BAND_GAP = 24;
const CANVAS_PADDING = 36;
const BAND_PADDING = 22;

type Palette = { fill: string; soft: string; border: string; accent: string };
type PositionedComponent = { key: string; name: string; x: number; y: number; width: number; height: number; layerIndex: number };
type DiagramLayer = Omit<ArchitectureLayer, 'components'> & { components: ArchitectureComponent[]; external?: boolean };

const palettes: Palette[] = [
  { fill: '#fff7ed', soft: '#ffedd5', border: '#f97316', accent: '#c2410c' },
  { fill: '#f5f3ff', soft: '#ede9fe', border: '#8b5cf6', accent: '#6d28d9' },
  { fill: '#eff6ff', soft: '#dbeafe', border: '#3b82f6', accent: '#1d4ed8' },
  { fill: '#ecfeff', soft: '#cffafe', border: '#06b6d4', accent: '#0e7490' },
  { fill: '#f0fdf4', soft: '#dcfce7', border: '#22c55e', accent: '#15803d' },
  { fill: '#f8fafc', soft: '#e2e8f0', border: '#64748b', accent: '#334155' },
];

function clean(value: unknown): string { return typeof value === 'string' ? value.trim() : ''; }
function cleanItem(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (!value || typeof value !== 'object') return '';
  const item = value as Record<string, unknown>;
  return clean(item.description || item.name || item.title || item.assumption || item.value);
}
function cleanList(value: unknown): string[] { return Array.isArray(value) ? value.map(cleanItem).filter(Boolean) : cleanItem(value) ? [cleanItem(value)] : []; }

function normalizeComponent(value: unknown, external = false): ArchitectureComponent | null {
  if (typeof value === 'string' && value.trim()) return { name: value.trim(), type: external ? 'external' : undefined };
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const name = clean(item.name || item.label);
  if (!name) return null;
  return { id: clean(item.id), name, type: clean(item.type) || (external ? 'external' : ''), responsibility: clean(item.responsibility || item.purpose), technology: clean(item.technology || item.platform), description: clean(item.description) };
}

function normalizeLayer(value: unknown): ArchitectureLayer | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const name = clean(item.name || item.label);
  const components = (Array.isArray(item.components) ? item.components : []).map((component) => normalizeComponent(component)).filter((component): component is ArchitectureComponent => Boolean(component));
  if (!name || components.length === 0) return null;
  return { name, purpose: clean(item.purpose || item.description), securityBoundary: clean(item.securityBoundary || item.security_boundary), components };
}

function normalizeRelationship(value: unknown): ArchitectureRelationship | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const source = clean(item.source || item.from || item.source_id);
  const target = clean(item.target || item.to || item.target_id);
  return source && target ? { source, target, label: clean(item.label || item.description), protocol: clean(item.protocol), type: clean(item.type || item.kind) } : null;
}

function paletteFor(name: string, index: number, external = false): Palette {
  if (external) return palettes[0];
  const value = name.toLowerCase();
  if (/experience|presentation|channel|user|front/.test(value)) return palettes[1];
  if (/application|api|gateway|interface/.test(value)) return palettes[2];
  if (/business|service|domain|integration|event|messag|ai/.test(value)) return palettes[3];
  if (/data|database|storage|information|analytics/.test(value)) return palettes[4];
  if (/cloud|platform|infrastructure|deployment|runtime/.test(value)) return palettes[5];
  return palettes[1 + (index % (palettes.length - 1))];
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

function componentHeight(component: ArchitectureComponent): number {
  const titleLines = Math.ceil(component.name.length / 30);
  const detailLines = Math.ceil(clean(component.responsibility || component.description).length / 46);
  return Math.max(MIN_COMPONENT_HEIGHT, Math.min(226, 78 + titleLines * 15 + detailLines * 13 + (clean(component.technology) ? 24 : 0)));
}

function ComponentCard({ component, palette, external }: { component: ArchitectureComponent; palette: Palette; external?: boolean }) {
  const Icon = componentIcon(component);
  const detail = clean(component.responsibility || component.description);
  return <div style={{ height: '100%', boxSizing: 'border-box', border: `${external ? '2px dashed' : '1.5px solid'} ${palette.border}`, background: '#fff', boxShadow: '0 5px 14px rgba(15,23,42,.08)', padding: 13, fontFamily: 'Inter,ui-sans-serif,system-ui,sans-serif' }}>
    <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start' }}><span style={{ display: 'flex', width: 29, height: 29, flex: '0 0 auto', alignItems: 'center', justifyContent: 'center', background: palette.soft, color: palette.accent }}><Icon size={16} /></span><span style={{ minWidth: 0 }}><strong style={{ display: 'block', color: '#0f172a', fontSize: 13, lineHeight: 1.25 }}>{component.name}</strong>{clean(component.type) && <span style={{ display: 'block', marginTop: 3, color: palette.accent, fontSize: 8.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.08em' }}>{external ? 'EXTERNAL · ' : ''}{component.type}</span>}</span></div>
    {detail && <p style={{ margin: '8px 0 0', color: '#475569', fontSize: 9.5, lineHeight: 1.35 }}>{detail}</p>}
    {clean(component.technology) && <span style={{ display: 'inline-block', marginTop: 8, background: palette.soft, color: palette.accent, padding: '3px 7px', fontSize: 8.5, fontWeight: 700 }}>{component.technology}</span>}
  </div>;
}

function relationshipPath(source: PositionedComponent, target: PositionedComponent, index: number, width: number): string {
  if (source.layerIndex === target.layerIndex) {
    const forward = target.x >= source.x;
    const x1 = forward ? source.x + source.width : source.x;
    const x2 = forward ? target.x : target.x + target.width;
    const y = source.y + source.height / 2;
    const lift = 18 + (index % 3) * 12;
    return `M ${x1} ${y} C ${(x1 + x2) / 2} ${y - lift}, ${(x1 + x2) / 2} ${y - lift}, ${x2} ${target.y + target.height / 2}`;
  }
  const downward = target.y > source.y;
  const x1 = source.x + source.width / 2;
  const y1 = downward ? source.y + source.height : source.y;
  const x2 = target.x + target.width / 2;
  const y2 = downward ? target.y : target.y + target.height;
  if (Math.abs(target.layerIndex - source.layerIndex) === 1) {
    const bend = (y1 + y2) / 2;
    return `M ${x1} ${y1} C ${x1} ${bend}, ${x2} ${bend}, ${x2} ${y2}`;
  }
  const corridor = width - CANVAS_PADDING - 12 - (index % 4) * 12;
  return `M ${x1} ${y1} L ${x1} ${y1 + (downward ? 12 : -12)} L ${corridor} ${y1 + (downward ? 12 : -12)} L ${corridor} ${y2 + (downward ? -12 : 12)} L ${x2} ${y2 + (downward ? -12 : 12)} L ${x2} ${y2}`;
}

interface Props { artifact: BRDArtifact | undefined; onExport: (format: 'pdf' | 'docx' | 'png' | 'drawio') => void; isExporting?: boolean }

export default function ArchitectureWorkspace({ artifact, onExport, isExporting }: Props) {
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);
  if (!artifact) return <Empty title="No architecture generated yet" detail="Generate an architecture from the selected BRD and requirements." />;

  const payload = (artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {}) as ArchitecturePayload;
  const layers = (Array.isArray(payload.layers) ? payload.layers : []).map(normalizeLayer).filter((layer): layer is ArchitectureLayer => Boolean(layer));
  const externalSource = payload.external_systems || payload.externalSystems;
  const externalComponents = (Array.isArray(externalSource) ? externalSource : []).map((component) => normalizeComponent(component, true)).filter((component): component is ArchitectureComponent => Boolean(component));
  const diagramLayers: DiagramLayer[] = [...(externalComponents.length ? [{ name: 'External systems', purpose: '', components: externalComponents, external: true }] : []), ...layers.map((layer) => ({ ...layer, components: (layer.components || []) as ArchitectureComponent[] }))];
  if (diagramLayers.length === 0) return <Empty title="No valid architecture components were generated" detail="Regenerate after confirming the BRD includes solution or integration context." />;

  const rawRelationships = [...(Array.isArray(payload.relationships) ? payload.relationships : []), ...(Array.isArray(payload.connections) ? payload.connections : [])];
  const relationships = rawRelationships.map(normalizeRelationship).filter((relationship): relationship is ArchitectureRelationship => Boolean(relationship));
  const maxComponents = Math.max(...diagramLayers.map((layer) => layer.components.length), 1);
  const canvasWidth = Math.max(900, CANVAS_PADDING * 2 + LABEL_WIDTH + maxComponents * COMPONENT_WIDTH + Math.max(0, maxComponents - 1) * COMPONENT_GAP + 52);
  const bandHeights = diagramLayers.map((layer) => Math.max(...layer.components.map(componentHeight), MIN_COMPONENT_HEIGHT) + BAND_PADDING * 2);
  const bandOffsets = bandHeights.map((_, index) => CANVAS_PADDING + bandHeights.slice(0, index).reduce((sum, height) => sum + height, 0) + index * BAND_GAP);
  const canvasHeight = CANVAS_PADDING * 2 + bandHeights.reduce((sum, height) => sum + height, 0) + Math.max(0, diagramLayers.length - 1) * BAND_GAP;
  const positioned = new Map<string, PositionedComponent>();
  diagramLayers.forEach((layer, layerIndex) => layer.components.forEach((component, componentIndex) => {
    const position = { key: clean(component.id) || component.name, name: component.name, x: CANVAS_PADDING + LABEL_WIDTH + componentIndex * (COMPONENT_WIDTH + COMPONENT_GAP), y: bandOffsets[layerIndex] + BAND_PADDING, width: COMPONENT_WIDTH, height: componentHeight(component), layerIndex };
    for (const key of [component.id, component.name]) if (clean(key)) positioned.set(clean(key).toLowerCase(), position);
  }));

  const decisions = (Array.isArray(payload.decisions) ? payload.decisions : []).map((value) => typeof value === 'string' ? { decision: value } : value).filter((value) => value && clean(value.decision));
  const risks = (Array.isArray(payload.risks) ? payload.risks : []).map((value) => typeof value === 'string' ? { description: value } : value).filter((value) => value && clean(value.description));
  const assumptions = cleanList(payload.assumptions);
  const tradeOffs = cleanList(payload.trade_offs);
  const security = cleanList(payload.security);
  const deployment = cleanList(payload.deployment);
  const concerns = payload.cross_cutting_concerns && typeof payload.cross_cutting_concerns === 'object' ? Object.entries(payload.cross_cutting_concerns).filter(([name]) => clean(name)) : [];
  const nfrs = payload.nfr_alignment && typeof payload.nfr_alignment === 'object' ? Object.entries(payload.nfr_alignment).filter(([name]) => clean(name)) : [];
  const technologies = payload.technology_stack && typeof payload.technology_stack === 'object' ? Object.entries(payload.technology_stack).filter(([name]) => clean(name)) : [];
  const safeId = artifact.id.replace(/[^a-zA-Z0-9]/g, '');
  const markerId = `architecture-arrow-${safeId}`;
  const patternId = `architecture-grid-${safeId}`;
  const connectedRelationships = relationships.map((relationship, index) => ({ relationship, index, source: positioned.get(clean(relationship.source || relationship.from).toLowerCase()), target: positioned.get(clean(relationship.target || relationship.to).toLowerCase()) })).filter((item) => item.source && item.target) as Array<{ relationship: ArchitectureRelationship; index: number; source: PositionedComponent; target: PositionedComponent }>;

  const handleExport = (format: 'pdf' | 'docx' | 'png' | 'drawio') => { setExportingFormat(format); onExport(format); window.setTimeout(() => setExportingFormat(null), 1800); };

  return <div className="space-y-5">
    <header className="border border-slate-700 bg-slate-950 p-6 text-white shadow-sm"><div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[.22em] text-blue-200">Enterprise solution blueprint</p><h2 className="mt-2 text-2xl font-bold">{clean(payload.title) || artifact.title || 'Solution Architecture'}</h2>{clean(payload.subtitle) && <p className="mt-2 text-sm font-medium text-blue-100">{payload.subtitle}</p>}{clean(payload.objective || payload.summary) ? <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-300">{clean(payload.objective || payload.summary)}</p> : <p className="mt-3 text-sm text-slate-400">Architecture objective not specified.</p>}</div><div className="grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-4">{[['Layers', layers.length], ['Components', layers.reduce((sum, layer) => sum + (layer.components?.length || 0), 0)], ['Integrations', connectedRelationships.length], ['External', externalComponents.length]].map(([label, value]) => <div key={label} className="border border-white/15 bg-white/5 px-3 py-3 text-center"><strong className="block text-lg">{value}</strong><span className="text-[9px] uppercase text-slate-300">{label}</span></div>)}</div></div></header>

    <section><div className="mb-3 flex flex-wrap items-end justify-between gap-2"><div><h3 className="text-sm font-bold text-ink">Layered architecture diagram</h3><p className="mt-1 text-xs text-ink-soft">Connectors map only to relationships supplied by the generated artifact.</p></div><span className="text-[10px] font-semibold uppercase tracking-wide text-ink-faint">Top to bottom · source to platform</span></div><div className="max-h-[760px] overflow-auto border border-slate-200 bg-slate-50 shadow-inner"><svg width={canvasWidth} height={canvasHeight} role="img" aria-label="Enterprise solution architecture diagram"><defs><pattern id={patternId} width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#e2e8f0" /></pattern><marker id={markerId} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#475569" /></marker></defs><rect width="100%" height="100%" fill={`url(#${patternId})`} />
      {diagramLayers.map((layer, index) => { const palette = paletteFor(layer.name, index, layer.external); const y = bandOffsets[index]; const bandHeight = bandHeights[index]; return <g key={`${layer.name}-${index}`}><rect x={CANVAS_PADDING} y={y} width={canvasWidth - CANVAS_PADDING * 2} height={bandHeight} fill={palette.fill} stroke={palette.border} strokeWidth="1.5" strokeDasharray={layer.external ? '8 5' : undefined} /><rect x={CANVAS_PADDING} y={y} width={LABEL_WIDTH - 16} height={bandHeight} fill={palette.soft} /><text x={CANVAS_PADDING + 16} y={y + 30} fill={palette.accent} fontSize="10" fontWeight="800" letterSpacing="1.1">{layer.external ? 'EXTERNAL' : `LAYER ${String(index + (externalComponents.length ? 0 : 1)).padStart(2, '0')}`}</text><text x={CANVAS_PADDING + 16} y={y + 54} fill="#0f172a" fontSize="15" fontWeight="800">{layer.name.slice(0, 24)}</text>{clean(layer.purpose) && <foreignObject x={CANVAS_PADDING + 16} y={y + 64} width={LABEL_WIDTH - 46} height={Math.max(50, bandHeight - 104)}><p style={{ margin: 0, color: '#475569', fontSize: 9.5, lineHeight: 1.35 }}>{clean(layer.purpose)}</p></foreignObject>}{clean(layer.securityBoundary) && <text x={CANVAS_PADDING + 16} y={y + bandHeight - 14} fill={palette.accent} fontSize="8.5" fontWeight="700">{clean(layer.securityBoundary).slice(0, 28)}</text>}</g>; })}
      {connectedRelationships.map(({ relationship, source, target, index }) => { const label = clean(relationship.label || relationship.protocol || relationship.type); const labelX = (source.x + source.width / 2 + target.x + target.width / 2) / 2; const labelY = (source.y + source.height / 2 + target.y + target.height / 2) / 2; const integration = /event|message|async|stream/.test(clean(relationship.type).toLowerCase()); return <g key={`${source.key}-${target.key}-${index}`}><path d={relationshipPath(source, target, index, canvasWidth)} fill="none" stroke={integration ? '#7c3aed' : '#475569'} strokeWidth="2" strokeDasharray={integration ? '7 4' : undefined} markerEnd={`url(#${markerId})`} />{label && <g><rect x={labelX - Math.min(78, label.length * 3.1)} y={labelY - 11} width={Math.min(156, Math.max(56, label.length * 6.2))} height="20" fill="white" stroke="#cbd5e1" /><text x={labelX} y={labelY + 3} textAnchor="middle" fill="#334155" fontSize="9" fontWeight="700">{label.slice(0, 27)}</text></g>}</g>; })}
      {diagramLayers.flatMap((layer, layerIndex) => { const palette = paletteFor(layer.name, layerIndex, layer.external); return layer.components.map((component) => { const position = positioned.get((clean(component.id) || component.name).toLowerCase())!; return <foreignObject key={`${layer.name}-${component.name}`} x={position.x} y={position.y} width={position.width} height={position.height}><ComponentCard component={component} palette={palette} external={layer.external} /></foreignObject>; }); })}
    </svg></div>{relationships.length > connectedRelationships.length && <p className="mt-2 text-xs text-amber-700">{relationships.length - connectedRelationships.length} relationship{relationships.length - connectedRelationships.length === 1 ? '' : 's'} could not be mapped because the referenced component is not present in this artifact version.</p>}</section>

    {(concerns.length > 0 || security.length > 0 || deployment.length > 0) && <section className="border border-slate-800 bg-slate-950 p-5 text-white"><div className="flex items-center gap-2"><ShieldCheck size={17} className="text-cyan-300" /><h3 className="text-sm font-bold">Cross-cutting concerns</h3></div><div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{security.length > 0 && <Concern title="Security" values={security} icon={<KeyRound size={14} />} tone="emerald" />}{deployment.length > 0 && <Concern title="Deployment" values={deployment} icon={<Cloud size={14} />} tone="blue" />}{concerns.map(([name, details]) => <Concern key={name} title={name} values={cleanList(details)} icon={<Eye size={14} />} tone="violet" />)}</div></section>}

    {decisions.length > 0 && <section className="border border-indigo-200 bg-indigo-50 p-5"><h3 className="text-sm font-bold text-indigo-950">Architectural decisions and rationale</h3><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[640px] border-collapse bg-white text-left text-xs"><thead><tr className="bg-indigo-100 text-indigo-950"><th className="border border-indigo-200 p-3">Architectural choice</th><th className="border border-indigo-200 p-3">Why it matters</th><th className="border border-indigo-200 p-3">Trade-off</th></tr></thead><tbody>{decisions.map((decision, index) => <tr key={`${decision.decision}-${index}`}><td className="border border-indigo-100 p-3 font-semibold text-indigo-950">{clean(decision.decision)}</td><td className="border border-indigo-100 p-3 text-indigo-800">{clean(decision.rationale) || 'Not specified'}</td><td className="border border-indigo-100 p-3 text-indigo-700">{clean(decision.trade_offs) || 'Not specified'}</td></tr>)}</tbody></table></div></section>}

    {(nfrs.length > 0 || assumptions.length > 0 || tradeOffs.length > 0 || technologies.length > 0) && <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">{nfrs.length > 0 && <DetailSection title="NFR alignment" entries={nfrs} />}{technologies.length > 0 && <DetailSection title="Technology landscape" entries={technologies} />}{assumptions.length > 0 && <ListSection title="Assumptions" values={assumptions} tone="amber" />}{tradeOffs.length > 0 && <ListSection title="Trade-offs" values={tradeOffs} tone="slate" />}</div>}
    {risks.length > 0 && <section className="border border-rose-200 bg-rose-50 p-5"><h3 className="text-sm font-bold text-rose-950">Architecture risks</h3><div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">{risks.map((risk, index) => <article key={`${risk.description}-${index}`} className="border border-rose-200 bg-white p-4"><p className="text-sm font-bold text-rose-950">{clean(risk.description)}</p>{clean(risk.impact) && <p className="mt-2 text-xs text-rose-800"><strong>Impact:</strong> {clean(risk.impact)}</p>}{clean(risk.mitigation) && <p className="mt-1 text-xs text-rose-700"><strong>Mitigation:</strong> {clean(risk.mitigation)}</p>}</article>)}</div></section>}
    {clean(payload.so_what) && <section className="flex items-start gap-3 border border-cyan-200 bg-cyan-50 p-5"><ShieldCheck size={19} className="mt-0.5 shrink-0 text-cyan-700" /><div><h3 className="text-sm font-bold text-cyan-950">Executive takeaway</h3><p className="mt-1 text-sm leading-relaxed text-cyan-900">{clean(payload.so_what)}</p></div></section>}
    <section className="border border-border bg-surface p-5"><h3 className="flex items-center gap-2 text-sm font-bold text-ink"><Download size={16} /> Export architecture</h3><p className="mt-1 text-xs text-ink-soft">PNG and PDF provide shareable views; draw.io remains editable. DOCX includes the visual and supporting details.</p><div className="mt-4 flex flex-wrap gap-2">{(['png', 'pdf', 'docx', 'drawio'] as const).map((format) => <button key={format} onClick={() => handleExport(format)} disabled={Boolean(isExporting && exportingFormat === format)} className="border border-border bg-surface-alt px-4 py-2 text-xs font-bold uppercase text-ink-soft hover:border-cyan-400 hover:bg-cyan-50 disabled:opacity-50">{exportingFormat === format ? 'Preparing…' : format === 'drawio' ? 'draw.io' : format}</button>)}</div></section>
  </div>;
}

function Empty({ title, detail }: { title: string; detail: string }) { return <div className="flex flex-col items-center justify-center py-24 text-center"><AlertCircle size={32} className="mb-4 text-cyan-600" /><p className="text-lg font-semibold text-ink">{title}</p><p className="mt-2 text-sm text-ink-soft">{detail}</p></div>; }
function Concern({ title, values, icon, tone }: { title: string; values: string[]; icon: ReactNode; tone: 'emerald' | 'blue' | 'violet' }) { const classes = { emerald: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200', blue: 'border-blue-400/30 bg-blue-400/10 text-blue-200', violet: 'border-violet-400/30 bg-violet-400/10 text-violet-200' }; return <article className={`border p-4 ${classes[tone]}`}><p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider">{icon}{title}</p><ul className="mt-3 space-y-1.5 text-xs text-slate-200">{values.map((value, index) => <li key={`${value}-${index}`}>• {value}</li>)}</ul></article>; }
function DetailSection({ title, entries }: { title: string; entries: Array<[string, unknown]> }) { return <section className="border border-blue-200 bg-blue-50 p-5"><h3 className="text-sm font-bold text-blue-950">{title}</h3><dl className="mt-3 space-y-3">{entries.map(([name, value]) => <div key={name} className="border-l-2 border-blue-400 pl-3"><dt className="text-xs font-bold text-blue-900">{name}</dt><dd className="mt-1 text-xs leading-relaxed text-blue-800">{cleanList(value).join(' · ') || 'Not specified'}</dd></div>)}</dl></section>; }
function ListSection({ title, values, tone }: { title: string; values: string[]; tone: 'amber' | 'slate' }) { return <section className={`border p-5 ${tone === 'amber' ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}><h3 className="text-sm font-bold text-ink">{title}</h3><ul className="mt-3 space-y-2 text-xs leading-relaxed text-ink-soft">{values.map((value, index) => <li key={`${value}-${index}`}>• {value}</li>)}</ul></section>; }
