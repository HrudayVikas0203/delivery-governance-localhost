import { AlertCircle } from 'lucide-react';
import type { BRDArtifact } from '../types';

interface BusinessFlowNode {
  id: string;
  label: string;
  type?: string;
  description?: string;
  actor?: string;
  system?: string;
  x?: number;
  y?: number;
}

interface BusinessFlowEdge {
  source: string;
  target: string;
  label?: string;
  type?: string;
}

interface BusinessFlowPayload {
  nodes?: BusinessFlowNode[];
  edges?: BusinessFlowEdge[];
  swimlanes?: Array<{
    name: string;
    actor?: string;
    description?: string;
  }>;
  decisions?: Array<{
    node_id: string;
    branches?: Array<{
      condition: string;
      target_id: string;
    }>;
  }>;
  outcome?: string;
  notes?: string;
}

type NodeTypeColor = {
  bg: string;
  border: string;
  text: string;
  icon: string;
};

const nodeTypeColors: Record<string, NodeTypeColor> = {
  start: {
    bg: 'bg-emerald-50',
    border: 'border-emerald-400',
    text: 'text-emerald-700',
    icon: '▶',
  },
  end: {
    bg: 'bg-rose-50',
    border: 'border-rose-400',
    text: 'text-rose-700',
    icon: '⏹',
  },
  decision: {
    bg: 'bg-amber-50',
    border: 'border-amber-400',
    text: 'text-amber-700',
    icon: '◇',
  },
  process: {
    bg: 'bg-blue-50',
    border: 'border-blue-300',
    text: 'text-blue-700',
    icon: '▢',
  },
  system: {
    bg: 'bg-purple-50',
    border: 'border-purple-300',
    text: 'text-purple-700',
    icon: '⚙',
  },
  approval: {
    bg: 'bg-cyan-50',
    border: 'border-cyan-300',
    text: 'text-cyan-700',
    icon: '✓',
  },
  default: {
    bg: 'bg-slate-50',
    border: 'border-slate-300',
    text: 'text-slate-700',
    icon: '→',
  },
};

function getNodeTypeColor(type?: string): NodeTypeColor {
  if (!type) return nodeTypeColors.default;
  const normalized = type.toLowerCase();
  return nodeTypeColors[normalized] || nodeTypeColors.default;
}

function isDecisionNode(node: BusinessFlowNode): boolean {
  return node.type?.toLowerCase() === 'decision' || node.label?.toLowerCase().includes('?');
}

function calculateNodeLayout(
  nodes: BusinessFlowNode[],
  edges: BusinessFlowEdge[],
): Array<{ id: string; x: number; y: number }> {
  // Build adjacency graph
  const graph = new Map<string, string[]>();
  nodes.forEach((node) => graph.set(node.id, []));
  edges.forEach((edge) => {
    if (graph.has(edge.source)) {
      graph.get(edge.source)!.push(edge.target);
    }
  });

  // Simple topological layout
  const positions: Map<string, { x: number; y: number }> = new Map();
  const visited = new Set<string>();
  let nodeInLayer = 0;

  function visit(nodeId: string, currentLayer: number): void {
    if (visited.has(nodeId)) return;
    visited.add(nodeId);

    const x = currentLayer * 200 + 50;
    const y = nodeInLayer * 120 + 50;
    positions.set(nodeId, { x, y });

    const children = graph.get(nodeId) || [];
    children.forEach((child, idx) => {
      nodeInLayer = idx;
      visit(child, currentLayer + 1);
    });
  }

  // Find start nodes (no incoming edges)
  const incomingCount = new Map<string, number>();
  nodes.forEach((node) => incomingCount.set(node.id, 0));
  edges.forEach((edge) => {
    incomingCount.set(edge.target, (incomingCount.get(edge.target) || 0) + 1);
  });

  const startNodes = nodes.filter((node) => incomingCount.get(node.id) === 0);
  startNodes.forEach((node) => visit(node.id, 0));

  // Visit remaining nodes
  nodes.forEach((node) => visit(node.id, 0));

  return Array.from(positions.entries()).map(([id, { x, y }]) => ({ id, x, y }));
}

interface BusinessFlowWorkspaceProps {
  artifact: BRDArtifact | undefined;
}

export default function BusinessFlowWorkspace({ artifact }: BusinessFlowWorkspaceProps) {
  if (!artifact) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="rounded-full bg-violet-50 p-6 mb-4">
          <AlertCircle size={32} className="text-violet-600" />
        </div>
        <p className="text-lg font-semibold text-ink">No business flow generated yet</p>
        <p className="text-sm text-ink-soft mt-2">
          Use the Regenerate button to create your first Business Flow.
        </p>
      </div>
    );
  }

  const payload = artifact.payload as BusinessFlowPayload;

  // Normalize data with defensive rendering
  const nodes = (Array.isArray(payload.nodes) ? payload.nodes : []).filter(
    (node) => node && typeof node === 'object' && node.id,
  );

  const edges = (Array.isArray(payload.edges) ? payload.edges : []).filter(
    (edge) => edge && typeof edge === 'object' && edge.source && edge.target,
  );

  const swimlanes = (Array.isArray(payload.swimlanes) ? payload.swimlanes : []).filter(
    (lane) => lane && typeof lane === 'object' && lane.name,
  );

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <AlertCircle size={32} className="text-violet-600 mb-4" />
        <p className="text-lg font-semibold text-ink">No process steps generated</p>
        <p className="text-sm text-ink-soft mt-2">The business flow appears to be incomplete.</p>
      </div>
    );
  }

  // Calculate layout
  const layout = calculateNodeLayout(nodes, edges);
  const nodePositions = new Map(layout.map((pos) => [pos.id, { x: pos.x, y: pos.y }]));

  // Determine SVG dimensions
  const maxX = Math.max(...layout.map((pos) => pos.x + 120), 400);
  const maxY = Math.max(...layout.map((pos) => pos.y + 100), 300);

  return (
    <div className="space-y-6">
      {/* Business Flow Header */}
      <div className="rounded-xl border border-border bg-gradient-to-br from-surface to-surface-alt p-6">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-mono text-violet-600 uppercase tracking-widest">Business Process</span>
        </div>
        <h2 className="text-3xl font-display font-bold text-ink mb-2">Business Flow</h2>
        <p className="text-sm text-ink leading-relaxed max-w-2xl">
          {nodes.length} steps, {edges.length} transitions. Visual representation of your business process.
        </p>
      </div>

      {/* Main Flow Diagram */}
      <div className="rounded-xl border border-border bg-surface overflow-x-auto">
        <div className="p-6 min-h-[500px] flex items-center justify-center">
          <svg
            width={maxX + 40}
            height={maxY + 40}
            className="min-w-full"
            style={{ background: 'white' }}
          >
            {/* Draw connectors/edges first (so they appear behind nodes) */}
            <defs>
              <marker
                id="arrowhead"
                markerWidth="10"
                markerHeight="10"
                refX="9"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 10 3, 0 6" fill="#64748b" />
              </marker>
            </defs>

            {edges.map((edge, idx) => {
              const sourcePos = nodePositions.get(edge.source);
              const targetPos = nodePositions.get(edge.target);
              if (!sourcePos || !targetPos) return null;

              const x1 = sourcePos.x + 60;
              const y1 = sourcePos.y + 50;
              const x2 = targetPos.x + 60;
              const y2 = targetPos.y;

              const midX = (x1 + x2) / 2;
              const midY = (y1 + y2) / 2;

              return (
                <g key={`edge-${idx}`}>
                  {/* Connection line */}
                  <path
                    d={`M ${x1} ${y1} Q ${midX} ${(y1 + y2) / 2} ${x2} ${y2}`}
                    stroke="#94a3b8"
                    strokeWidth="2"
                    fill="none"
                    markerEnd="url(#arrowhead)"
                  />
                  {/* Edge label */}
                  {edge.label && (
                    <text
                      x={midX}
                      y={midY - 10}
                      textAnchor="middle"
                      fontSize="12"
                      fill="#64748b"
                      fontWeight="600"
                      className="pointer-events-none"
                    >
                      {edge.label}
                    </text>
                  )}
                </g>
              );
            })}

            {/* Draw nodes */}
            {nodes.map((node) => {
              const pos = nodePositions.get(node.id);
              if (!pos) return null;

              const isDecision = isDecisionNode(node);
              const colors = getNodeTypeColor(node.type);
              const nodeWidth = isDecision ? 100 : 120;
              const nodeHeight = isDecision ? 100 : 100;

              return (
                <g key={`node-${node.id}`}>
                  {/* Node shape */}
                  {isDecision ? (
                    // Diamond shape for decisions
                    <polygon
                      points={`${pos.x + nodeWidth / 2},${pos.y} ${pos.x + nodeWidth},${pos.y + nodeHeight / 2} ${pos.x + nodeWidth / 2},${pos.y + nodeHeight} ${pos.x},${pos.y + nodeHeight / 2}`}
                      fill={colors.bg}
                      stroke={colors.border}
                      strokeWidth="2"
                    />
                  ) : (
                    // Rectangle for other nodes
                    <rect
                      x={pos.x}
                      y={pos.y}
                      width={nodeWidth}
                      height={nodeHeight}
                      rx="8"
                      fill={colors.bg}
                      stroke={colors.border}
                      strokeWidth="2"
                    />
                  )}

                  {/* Node icon */}
                  <text
                    x={pos.x + nodeWidth / 2}
                    y={pos.y + 20}
                    textAnchor="middle"
                    fontSize="16"
                    className="pointer-events-none"
                  >
                    {colors.icon}
                  </text>

                  {/* Node label */}
                  <text
                    x={pos.x + nodeWidth / 2}
                    y={pos.y + 45}
                    textAnchor="middle"
                    fontSize="13"
                    fontWeight="600"
                    fill={colors.text}
                    className="pointer-events-none"
                  >
                    {node.label?.substring(0, 12)}
                  </text>

                  {node.description && (
                    <text
                      x={pos.x + nodeWidth / 2}
                      y={pos.y + 65}
                      textAnchor="middle"
                      fontSize="11"
                      fill="#64748b"
                      className="pointer-events-none"
                    >
                      {node.description.substring(0, 15)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      </div>

      {/* Process Details */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Steps Summary */}
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">📋</span> Process Steps
          </h3>
          <div className="space-y-2">
            {nodes.map((node, idx) => {
              const colors = getNodeTypeColor(node.type);
              const isDecision = isDecisionNode(node);
              return (
                <div
                  key={node.id}
                  className={`rounded-lg border-2 ${colors.border} ${colors.bg} p-3 flex items-start gap-3`}
                >
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-white border-2 border-current flex items-center justify-center">
                    <span className={`text-sm font-bold ${colors.text}`}>{idx + 1}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-bold ${colors.text}`}>{node.label}</p>
                    {node.description && (
                      <p className="text-xs text-ink-soft mt-1 line-clamp-2">{node.description}</p>
                    )}
                    {node.system && (
                      <p className="text-[10px] text-ink-faint font-mono mt-1">🔧 {node.system}</p>
                    )}
                    {node.actor && (
                      <p className="text-[10px] text-ink-faint font-mono mt-1">👤 {node.actor}</p>
                    )}
                    {isDecision && <span className="inline-block mt-1 text-[10px] font-semibold text-amber-700 bg-amber-100 px-2 py-1 rounded">Decision</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Transitions */}
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">🔗</span> Transitions
          </h3>
          <div className="space-y-2">
            {edges.length > 0 ? (
              edges.map((edge, idx) => {
                const sourceNode = nodes.find((n) => n.id === edge.source);
                const targetNode = nodes.find((n) => n.id === edge.target);
                return (
                  <div key={idx} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-700 truncate">{sourceNode?.label || edge.source}</span>
                      <span className="text-slate-400">→</span>
                      <span className="font-semibold text-slate-700 truncate">{targetNode?.label || edge.target}</span>
                    </div>
                    {edge.label && (
                      <p className="text-xs text-slate-600 mt-1">
                        <span className="font-mono bg-white px-2 py-1 rounded border border-slate-200">{edge.label}</span>
                      </p>
                    )}
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-ink-soft">No transitions defined.</p>
            )}
          </div>
        </div>
      </div>

      {/* Swimlanes if present */}
      {swimlanes.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">👥</span> Process Actors / Swimlanes
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {swimlanes.map((lane, idx) => (
              <div key={idx} className="rounded-lg border border-indigo-200 bg-indigo-50 p-4">
                <p className="text-sm font-bold text-indigo-900">{lane.name}</p>
                {lane.actor && <p className="text-xs text-indigo-700 mt-1">Actor: {lane.actor}</p>}
                {lane.description && <p className="text-xs text-indigo-600 mt-2">{lane.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Outcome */}
      {payload.outcome && (
        <div className="rounded-xl border-2 border-emerald-400 bg-gradient-to-r from-emerald-50 to-emerald-100 p-6">
          <h3 className="text-sm font-bold text-emerald-900 mb-2">Expected Outcome</h3>
          <p className="text-base text-emerald-800">{payload.outcome}</p>
        </div>
      )}
    </div>
  );
}
