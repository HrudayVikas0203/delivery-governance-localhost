import { AlertCircle, CircleDot, GitBranch, UserRound } from 'lucide-react';
import type { BRDArtifact, BusinessFlowEdge, BusinessFlowNode, BusinessFlowPayload } from '../types';

const NODE_WIDTH = 300;
const MIN_NODE_HEIGHT = 184;
const COLUMN_GAP = 96;
const ROW_GAP = 62;
const CANVAS_PADDING = 52;

type NodePosition = { x: number; y: number; rank: number; height: number };

const palettes = {
  start: { fill: '#ecfdf5', border: '#10b981', accent: '#047857', badge: '#d1fae5' },
  end: { fill: '#f0fdf4', border: '#22c55e', accent: '#166534', badge: '#dcfce7' },
  decision: { fill: '#fffbeb', border: '#f59e0b', accent: '#92400e', badge: '#fef3c7' },
  input: { fill: '#f5f3ff', border: '#8b5cf6', accent: '#6d28d9', badge: '#ede9fe' },
  output: { fill: '#f0fdfa', border: '#14b8a6', accent: '#0f766e', badge: '#ccfbf1' },
  exception: { fill: '#fff1f2', border: '#f43f5e', accent: '#be123c', badge: '#ffe4e6' },
  process: { fill: '#eff6ff', border: '#3b82f6', accent: '#1d4ed8', badge: '#dbeafe' },
  system: { fill: '#faf5ff', border: '#a855f7', accent: '#7e22ce', badge: '#f3e8ff' },
  subprocess: { fill: '#f5f3ff', border: '#7c3aed', accent: '#5b21b6', badge: '#ede9fe' },
};

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : text(value) ? [text(value)] : [];
}

function normalizeNode(value: unknown, index: number): BusinessFlowNode | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const id = text(item.id || item.key) || `step-${index + 1}`;
  const label = text(item.label || item.name || item.step);
  if (!label) return null;
  return { id, label, type: text(item.type || item.kind), description: text(item.description), actor: text(item.actor || item.role), system: text(item.system), inputs: stringList(item.inputs || item.input), outputs: stringList(item.outputs || item.output), business_rule: text(item.business_rule || item.rule), condition: text(item.condition), exception_handling: text(item.exception_handling || item.exception), status: text(item.status) };
}

function normalizeEdge(value: unknown): BusinessFlowEdge | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const source = text(item.source || item.from || item.source_id);
  const target = text(item.target || item.to || item.target_id);
  return source && target ? { source, target, label: text(item.label || item.condition), kind: text(item.kind), type: text(item.type) } : null;
}

function measuredHeight(node: BusinessFlowNode): number {
  const titleLines = Math.ceil(text(node.label).length / 28);
  const actorLines = Math.ceil(([text(node.actor), text(node.system)].filter(Boolean).join(' · ')).length / 40);
  const descriptionLines = Math.ceil(text(node.description).length / 44);
  const ruleLines = Math.ceil(text(node.business_rule || node.condition).length / 38);
  const exceptionLines = Math.ceil(text(node.exception_handling).length / 38);
  const ioLines = stringList(node.inputs).length || stringList(node.outputs).length ? 42 : 0;
  return Math.max(MIN_NODE_HEIGHT, Math.min(330, 96 + titleLines * 18 + actorLines * 13 + descriptionLines * 14 + ruleLines * 13 + exceptionLines * 13 + ioLines));
}

function nodeType(node: BusinessFlowNode, incoming: number, outgoing: number): keyof typeof palettes {
  const raw = text(node.type).toLowerCase();
  if (raw === 'decision' || raw === 'gateway' || node.label.includes('?')) return 'decision';
  if (raw in palettes) return raw as keyof typeof palettes;
  if (/system|service|automation/.test(raw)) return 'system';
  if (/sub.?process/.test(raw)) return 'subprocess';
  if (incoming === 0) return 'start';
  if (outgoing === 0) return 'end';
  return 'process';
}

function buildLayout(nodes: BusinessFlowNode[], edges: BusinessFlowEdge[]) {
  const ids = new Set(nodes.map((node) => node.id));
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]));

  edges.forEach((edge) => {
    if (!ids.has(edge.source) || !ids.has(edge.target)) return;
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
    outgoing.get(edge.source)?.push(edge.target);
  });

  const ranks = new Map(nodes.map((node) => [node.id, 0]));
  const remainingIncoming = new Map(incoming);
  const queue = nodes.filter((node) => remainingIncoming.get(node.id) === 0).map((node) => node.id);
  const processed = new Set<string>();

  while (queue.length) {
    const id = queue.shift()!;
    processed.add(id);
    (outgoing.get(id) || []).forEach((target) => {
      ranks.set(target, Math.max(ranks.get(target) || 0, (ranks.get(id) || 0) + 1));
      remainingIncoming.set(target, (remainingIncoming.get(target) || 1) - 1);
      if (remainingIncoming.get(target) === 0) queue.push(target);
    });
  }

  nodes.filter((node) => !processed.has(node.id)).forEach((node, index) => {
    ranks.set(node.id, Math.max(...ranks.values(), 0) + index + 1);
  });

  const groups = new Map<number, BusinessFlowNode[]>();
  nodes.forEach((node) => {
    const rank = ranks.get(node.id) || 0;
    groups.set(rank, [...(groups.get(rank) || []), node]);
  });

  const groupHeights = Array.from(groups.values(), (group) => group.reduce((sum, node) => sum + measuredHeight(node), 0) + Math.max(0, group.length - 1) * ROW_GAP);
  const contentHeight = Math.max(...groupHeights, MIN_NODE_HEIGHT);
  const positions = new Map<string, NodePosition>();
  groups.forEach((group, rank) => {
    const groupHeight = group.reduce((sum, node) => sum + measuredHeight(node), 0) + Math.max(0, group.length - 1) * ROW_GAP;
    const offset = (contentHeight - groupHeight) / 2;
    let cursor = CANVAS_PADDING + 54 + offset;
    group.forEach((node) => {
      const height = measuredHeight(node);
      positions.set(node.id, {
        x: CANVAS_PADDING + rank * (NODE_WIDTH + COLUMN_GAP),
        y: cursor,
        rank,
        height,
      });
      cursor += height + ROW_GAP;
    });
  });

  const maxRank = Math.max(...ranks.values(), 0);
  return {
    positions,
    incoming,
    outgoing,
    width: CANVAS_PADDING * 2 + (maxRank + 1) * NODE_WIDTH + maxRank * COLUMN_GAP,
    height: CANVAS_PADDING * 2 + 54 + contentHeight,
  };
}

function connectorPath(source: NodePosition, target: NodePosition): string {
  const x1 = source.x + NODE_WIDTH;
  const y1 = source.y + source.height / 2;
  const x2 = target.x;
  const y2 = target.y + target.height / 2;
  if (target.rank > source.rank) {
    const bend = x1 + Math.max(38, (x2 - x1) / 2);
    return `M ${x1} ${y1} C ${bend} ${y1}, ${bend} ${y2}, ${x2} ${y2}`;
  }
  const bottom = Math.max(source.y + source.height, target.y + target.height) + 34;
  return `M ${x1} ${y1} C ${x1 + 42} ${y1}, ${x1 + 42} ${bottom}, ${x2 - 42} ${bottom} S ${x2 - 42} ${y2}, ${x2} ${y2}`;
}

function NodeCard({ node, kind }: { node: BusinessFlowNode; kind: keyof typeof palettes }) {
  const palette = palettes[kind];
  const inputs = stringList(node.inputs);
  const outputs = stringList(node.outputs);
  const description = text(node.description);
  const actor = [text(node.actor), text(node.system)].filter((value, index, values) => value && values.indexOf(value) === index).join(' · ');
  const rule = text(node.business_rule || node.condition);
  const exception = text(node.exception_handling);
  const status = text(node.status);

  return (
    <div
      style={{
        height: '100%', boxSizing: 'border-box', border: kind === 'decision' ? 'none' : `2px solid ${palette.border}`,
        borderRadius: kind === 'start' || kind === 'end' ? 28 : 14, background: kind === 'decision' ? 'transparent' : palette.fill,
        boxShadow: kind === 'decision' ? 'none' : '0 8px 20px rgba(15, 23, 42, 0.08)', padding: kind === 'decision' ? '30px 58px' : '14px 16px', color: '#0f172a',
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ color: palette.accent, fontSize: 10, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase' }}>{kind === 'process' ? 'Activity' : kind}</span>
        {status && <span style={{ borderRadius: 999, background: palette.badge, color: palette.accent, padding: '3px 8px', fontSize: 9, fontWeight: 700 }}>{status}</span>}
      </div>
      <div style={{ marginTop: 6, fontSize: 15, lineHeight: 1.25, fontWeight: 800 }}>{text(node.label) || 'Untitled step'}</div>
      {actor && <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6, color: '#475569', fontSize: 10, fontWeight: 700 }}><UserRound size={12} /> {actor}</div>}
      {description && <div style={{ marginTop: 7, color: '#475569', fontSize: 10.5, lineHeight: 1.35 }}>{description}</div>}
      {rule && <div style={{ marginTop: 7, borderLeft: `3px solid ${palette.border}`, paddingLeft: 7, color: palette.accent, fontSize: 10, lineHeight: 1.3 }}><strong>Rule:</strong> {rule}</div>}
      {exception && <div style={{ marginTop: 7, borderLeft: '3px solid #f43f5e', paddingLeft: 7, color: '#be123c', fontSize: 10, lineHeight: 1.3 }}><strong>Exception:</strong> {exception}</div>}
      {(inputs.length > 0 || outputs.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8, borderTop: '1px solid rgba(100,116,139,.2)', paddingTop: 7 }}>
          <div><div style={{ color: '#64748b', fontSize: 8, fontWeight: 800, textTransform: 'uppercase' }}>Input</div><div style={{ color: '#334155', fontSize: 9.5, lineHeight: 1.25 }}>{inputs.slice(0, 2).join(', ') || '—'}</div></div>
          <div><div style={{ color: '#64748b', fontSize: 8, fontWeight: 800, textTransform: 'uppercase' }}>Output</div><div style={{ color: '#334155', fontSize: 9.5, lineHeight: 1.25 }}>{outputs.slice(0, 2).join(', ') || '—'}</div></div>
        </div>
      )}
    </div>
  );
}

interface BusinessFlowWorkspaceProps { artifact: BRDArtifact | undefined }

export default function BusinessFlowWorkspace({ artifact }: BusinessFlowWorkspaceProps) {
  if (!artifact) {
    return <div className="flex flex-col items-center justify-center py-24 text-center"><div className="mb-4 rounded-full bg-violet-50 p-6"><AlertCircle size={32} className="text-violet-600" /></div><p className="text-lg font-semibold text-ink">No business flow generated yet</p><p className="mt-2 text-sm text-ink-soft">Generate a flow from the selected BRD and requirements.</p></div>;
  }

  const payload = (artifact.payload && typeof artifact.payload === 'object' ? artifact.payload : {}) as BusinessFlowPayload;
  const nodeSource = payload.nodes || payload.steps;
  const nodes = (Array.isArray(nodeSource) ? nodeSource : []).map(normalizeNode).filter((node): node is BusinessFlowNode => Boolean(node));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edgeSource = payload.edges || payload.transitions;
  const edges = (Array.isArray(edgeSource) ? edgeSource : []).map(normalizeEdge).filter((edge): edge is BusinessFlowEdge => Boolean(edge && nodeIds.has(edge.source) && nodeIds.has(edge.target)));
  const swimlanes = (Array.isArray(payload.swimlanes) ? payload.swimlanes : []).filter((lane) => lane && text(lane.name));

  if (nodes.length === 0) {
    return <div className="flex flex-col items-center justify-center py-24 text-center"><AlertCircle size={32} className="mb-4 text-violet-600" /><p className="text-lg font-semibold text-ink">No valid process steps were generated</p><p className="mt-2 text-sm text-ink-soft">Regenerate the artifact after confirming the BRD contains process information.</p></div>;
  }

  const layout = buildLayout(nodes, edges);
  const safeId = artifact.id.replace(/[^a-zA-Z0-9]/g, '');
  const markerId = `business-arrow-${safeId}`;
  const exceptionMarkerId = `business-error-arrow-${safeId}`;
  const patternId = `flow-grid-${safeId}`;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 rounded-xl border border-violet-200 bg-gradient-to-r from-violet-950 via-indigo-950 to-slate-950 p-6 text-white lg:flex-row lg:items-center lg:justify-between">
        <div><p className="text-[10px] font-bold uppercase tracking-[0.22em] text-violet-200">Business process model</p><h2 className="mt-2 text-2xl font-bold">{artifact.title || 'Business Flow'}</h2><p className="mt-2 max-w-3xl text-sm text-slate-300">A structured process view generated from the selected project, BRD, and requirement context.</p></div>
        <div className="flex gap-3"><div className="rounded-lg border border-white/15 bg-white/10 px-4 py-3"><span className="block text-xl font-bold">{nodes.length}</span><span className="text-[10px] uppercase tracking-wider text-slate-300">Steps</span></div><div className="rounded-lg border border-white/15 bg-white/10 px-4 py-3"><span className="block text-xl font-bold">{edges.length}</span><span className="text-[10px] uppercase tracking-wider text-slate-300">Transitions</span></div></div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-50 shadow-inner">
        <svg width={Math.max(layout.width, 760)} height={Math.max(layout.height, 430)} role="img" aria-label="Business process diagram">
          <defs><pattern id={patternId} width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" fill="none" stroke="#e2e8f0" strokeWidth="1" /></pattern><marker id={markerId} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" /></marker><marker id={exceptionMarkerId} markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 10 5 L 0 10 z" fill="#e11d48" /></marker></defs>
          <rect width="100%" height="100%" fill={`url(#${patternId})`} />
          <text x={CANVAS_PADDING} y={36} fill="#64748b" fontSize="11" fontWeight="700" letterSpacing="1.4">ENTRY → ACTIVITIES → DECISIONS → OUTCOME</text>
          {edges.map((edge, index) => {
            const source = layout.positions.get(edge.source); const target = layout.positions.get(edge.target);
            if (!source || !target) return null;
            const label = text(edge.label); const labelX = (source.x + NODE_WIDTH + target.x) / 2; const labelY = (source.y + source.height / 2 + target.y + target.height / 2) / 2 - 8;
            const edgeSemantics = `${edge.kind || ''} ${edge.type || ''} ${edge.label || ''}`.toLowerCase();
            const exception = /exception|error|failure|reject|invalid|no\b/.test(edgeSemantics);
            return <g key={`${edge.source}-${edge.target}-${index}`}><path d={connectorPath(source, target)} fill="none" stroke={exception ? '#e11d48' : '#64748b'} strokeWidth="2.25" strokeDasharray={exception ? '7 5' : undefined} markerEnd={`url(#${exception ? exceptionMarkerId : markerId})`} />{label && <g><rect x={labelX - Math.min(74, label.length * 3.2)} y={labelY - 13} width={Math.min(148, Math.max(54, label.length * 6.4))} height="22" rx="11" fill="white" stroke={exception ? '#fecdd3' : '#cbd5e1'} /><text x={labelX} y={labelY + 2} textAnchor="middle" fill={exception ? '#be123c' : '#475569'} fontSize="10" fontWeight="700">{label.slice(0, 24)}</text></g>}</g>;
          })}
          {nodes.map((node) => {
            const position = layout.positions.get(node.id)!;
            const kind = nodeType(node, layout.incoming.get(node.id) || 0, layout.outgoing.get(node.id)?.length || 0);
            return <g key={node.id}>{kind === 'decision' && <polygon points={`${position.x + NODE_WIDTH / 2},${position.y} ${position.x + NODE_WIDTH},${position.y + position.height / 2} ${position.x + NODE_WIDTH / 2},${position.y + position.height} ${position.x},${position.y + position.height / 2}`} fill={palettes.decision.fill} stroke={palettes.decision.border} strokeWidth="2.5" />}<foreignObject x={position.x} y={position.y} width={NODE_WIDTH} height={position.height}><NodeCard node={node} kind={kind} /></foreignObject></g>;
          })}
        </svg>
      </div>

      {swimlanes.length > 0 && <section className="rounded-xl border border-border bg-surface p-5"><h3 className="flex items-center gap-2 text-sm font-bold text-ink"><UserRound size={16} className="text-indigo-600" /> Actors and swimlanes</h3><div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{swimlanes.map((lane, index) => <article key={`${lane.name}-${index}`} className="rounded-lg border border-indigo-200 bg-indigo-50 p-4"><p className="text-sm font-bold text-indigo-950">{text(lane.name)}</p>{text(lane.actor) && <p className="mt-1 text-xs font-semibold text-indigo-700">{text(lane.actor)}</p>}{text(lane.description) && <p className="mt-2 text-xs leading-relaxed text-indigo-800">{text(lane.description)}</p>}</article>)}</div></section>}
      {text(payload.outcome) && <section className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-5"><CircleDot size={19} className="mt-0.5 shrink-0 text-emerald-700" /><div><h3 className="text-sm font-bold text-emerald-950">Business outcome</h3><p className="mt-1 text-sm leading-relaxed text-emerald-800">{text(payload.outcome)}</p></div></section>}
      <div className="flex items-center gap-2 text-xs text-ink-faint"><GitBranch size={14} /> Solid connectors are standard transitions; dashed red connectors identify exception paths when provided.</div>
    </div>
  );
}
