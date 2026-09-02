import { useState } from 'react';
import { Download, AlertCircle, CheckCircle } from 'lucide-react';
import type { BRDArtifact } from '../types';

interface ArchitectureLayer {
  name: string;
  description?: string;
  purpose?: string;
  components?: Array<{
    name: string;
    type?: string;
    responsibility?: string;
    technology?: string;
    description?: string;
  }> | string[];
}

interface ArchitectureComponent {
  name: string;
  type?: string;
  responsibility?: string;
  technology?: string;
  description?: string;
}

interface ArchitecturePayload {
  title?: string;
  subtitle?: string;
  objective?: string;
  style?: string;
  summary?: string;
  layers?: ArchitectureLayer[];
  external_systems?: Array<{
    name: string;
    type?: string;
    description?: string;
  }>;
  relationships?: Array<{
    source: string;
    target: string;
    type?: string;
    protocol?: string;
  }>;
  cross_cutting_concerns?: Record<string, string | string[]>;
  decisions?: Array<{
    decision: string;
    rationale?: string;
    trade_offs?: string;
  }>;
  technology_stack?: Record<string, string[]>;
  nfr_alignment?: Record<string, string>;
  assumptions?: string[];
  risks?: Array<{
    description: string;
    impact?: string;
    mitigation?: string;
  }>;
  trade_offs?: string[];
  so_what?: string;
  notes?: string;
}

interface ComponentTypeConfig {
  icon: string;
  color: string;
  bgColor: string;
  borderColor: string;
}

const componentTypeStyles: Record<string, ComponentTypeConfig> = {
  service: {
    icon: '⚙️',
    color: 'text-blue-700',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
  },
  database: {
    icon: '🗄️',
    color: 'text-green-700',
    bgColor: 'bg-green-50',
    borderColor: 'border-green-200',
  },
  external: {
    icon: '🔗',
    color: 'text-orange-700',
    bgColor: 'bg-orange-50',
    borderColor: 'border-orange-200',
  },
  api: {
    icon: '📡',
    color: 'text-purple-700',
    bgColor: 'bg-purple-50',
    borderColor: 'border-purple-200',
  },
  ai: {
    icon: '🤖',
    color: 'text-indigo-700',
    bgColor: 'bg-indigo-50',
    borderColor: 'border-indigo-200',
  },
  messaging: {
    icon: '📨',
    color: 'text-pink-700',
    bgColor: 'bg-pink-50',
    borderColor: 'border-pink-200',
  },
  storage: {
    icon: '💾',
    color: 'text-slate-700',
    bgColor: 'bg-slate-50',
    borderColor: 'border-slate-200',
  },
  infrastructure: {
    icon: '🏗️',
    color: 'text-amber-700',
    bgColor: 'bg-amber-50',
    borderColor: 'border-amber-200',
  },
  default: {
    icon: '📦',
    color: 'text-cyan-700',
    bgColor: 'bg-cyan-50',
    borderColor: 'border-cyan-200',
  },
};

function getComponentStyle(type?: string): ComponentTypeConfig {
  if (!type) return componentTypeStyles.default;
  const normalized = type.toLowerCase();
  return componentTypeStyles[normalized] || componentTypeStyles.default;
}

function normalizeComponent(comp: ArchitectureComponent | string): ArchitectureComponent {
  if (typeof comp === 'string') {
    return { name: comp };
  }
  return comp;
}

interface ArchitectureWorkspaceProps {
  artifact: BRDArtifact | undefined;
  onExport: (format: 'pdf' | 'docx' | 'png' | 'drawio') => void;
  isExporting?: boolean;
}

export default function ArchitectureWorkspace({
  artifact,
  onExport,
  isExporting,
}: ArchitectureWorkspaceProps) {
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);

  if (!artifact) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="rounded-full bg-cyan-50 p-6 mb-4">
          <AlertCircle size={32} className="text-cyan-600" />
        </div>
        <p className="text-lg font-semibold text-ink">No architecture generated yet</p>
        <p className="text-sm text-ink-soft mt-2">Use the Regenerate button to create your first Solution Architecture.</p>
      </div>
    );
  }

  const payload = artifact.payload as ArchitecturePayload;

  // Defensive rendering - normalize data
  const layers = (Array.isArray(payload.layers) ? payload.layers : []).filter(
    (layer) => layer && typeof layer === 'object',
  );
  const externalSystems = (Array.isArray(payload.external_systems) ? payload.external_systems : []).filter(
    (system) => system && typeof system === 'object',
  );
  const decisions = (Array.isArray(payload.decisions) ? payload.decisions : []).filter(
    (decision) => decision && typeof decision === 'object',
  );
  const assumptions = (Array.isArray(payload.assumptions) ? payload.assumptions : []).filter(
    (assumption) => typeof assumption === 'string',
  );
  const risks = (Array.isArray(payload.risks) ? payload.risks : []).filter(
    (risk) => risk && typeof risk === 'object',
  );
  const tradeOffs = (Array.isArray(payload.trade_offs) ? payload.trade_offs : []).filter(
    (tradeOff) => typeof tradeOff === 'string',
  );

  const handleExport = (format: 'pdf' | 'docx' | 'png' | 'drawio') => {
    setExportingFormat(format);
    onExport(format);
    setTimeout(() => setExportingFormat(null), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Architecture Overview Header */}
      <div className="rounded-xl border border-border bg-gradient-to-br from-surface to-surface-alt p-6">
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono text-cyan-600 uppercase tracking-widest">Solution Architecture</span>
            </div>
            <h2 className="text-3xl font-display font-bold text-ink mb-2">
              {payload.title || 'Enterprise Solution Architecture'}
            </h2>
            {payload.subtitle && <p className="text-lg text-ink-soft mb-4">{payload.subtitle}</p>}
            {payload.objective && (
              <p className="text-sm text-ink leading-relaxed max-w-2xl">{payload.objective}</p>
            )}
          </div>
          {payload.style && (
            <div className="flex-shrink-0">
              <span className="inline-flex items-center gap-2 rounded-full border border-cyan-200 bg-cyan-50 px-4 py-2 text-xs font-semibold text-cyan-700">
                ✓ {payload.style}
              </span>
            </div>
          )}
        </div>
        {payload.summary && (
          <div className="mt-4 rounded-lg bg-white border border-cyan-100 p-4">
            <p className="text-sm text-ink">{payload.summary}</p>
          </div>
        )}
      </div>

      {/* Layered Architecture Visualization */}
      {layers.length > 0 && (
        <div className="rounded-xl border border-border bg-surface overflow-hidden">
          <div className="border-b border-border px-6 py-4 bg-surface-alt">
            <h3 className="text-sm font-bold text-ink">Layered Architecture</h3>
            <p className="text-xs text-ink-soft mt-1">Core systems, components, and their interactions</p>
          </div>
          <div className="p-6 space-y-4">
            {layers.map((layer, layerIndex) => {
              const components = Array.isArray(layer.components)
                ? layer.components.map(normalizeComponent)
                : [];

              return (
                <div
                  key={layer.name || layerIndex}
                  className="rounded-lg border-2 border-cyan-200 bg-gradient-to-r from-cyan-50 to-white overflow-hidden"
                >
                  <div className="bg-cyan-100 px-4 py-3 border-b border-cyan-200">
                    <h4 className="text-sm font-bold text-cyan-900">{layer.name}</h4>
                    {layer.purpose && <p className="text-xs text-cyan-700 mt-1">{layer.purpose}</p>}
                  </div>
                  <div className="p-4">
                    {components.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {components.map((component, compIndex) => {
                          const style = getComponentStyle(component.type);
                          return (
                            <div
                              key={component.name || compIndex}
                              className={`rounded-lg border-2 ${style.borderColor} ${style.bgColor} p-4 transition hover:shadow-md`}
                            >
                              <div className="flex items-start gap-2">
                                <span className="text-xl flex-shrink-0">{style.icon}</span>
                                <div className="flex-1 min-w-0">
                                  <p className={`text-sm font-bold ${style.color} truncate`}>
                                    {component.name}
                                  </p>
                                  {component.type && (
                                    <span className={`inline-block mt-1 text-[10px] font-semibold ${style.color} uppercase tracking-wider`}>
                                      {component.type}
                                    </span>
                                  )}
                                </div>
                              </div>
                              {component.responsibility && (
                                <p className="text-xs text-ink-soft mt-2">{component.responsibility}</p>
                              )}
                              {component.technology && (
                                <p className="text-[10px] text-ink-faint font-mono mt-2">
                                  🔧 {component.technology}
                                </p>
                              )}
                              {component.description && (
                                <p className="text-xs text-ink-soft mt-2 line-clamp-2">
                                  {component.description}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-sm text-ink-faint">No components defined for this layer.</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* External Systems */}
      {externalSystems.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">🔗</span> External Systems & Integrations
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {externalSystems.map((system, index) => {
              const style = getComponentStyle('external');
              return (
                <div key={system.name || index} className={`rounded-lg border-2 ${style.borderColor} ${style.bgColor} p-4`}>
                  <p className={`text-sm font-bold ${style.color}`}>{system.name}</p>
                  {system.type && (
                    <p className={`text-[10px] font-semibold ${style.color} uppercase tracking-wider mt-1`}>
                      {system.type}
                    </p>
                  )}
                  {system.description && <p className="text-xs text-ink-soft mt-2">{system.description}</p>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Cross-Cutting Concerns */}
      {payload.cross_cutting_concerns && Object.keys(payload.cross_cutting_concerns).length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">🛡️</span> Cross-Cutting Concerns
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(payload.cross_cutting_concerns).map(([concern, details]) => (
              <div key={concern} className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                <p className="text-sm font-bold text-blue-900">{concern}</p>
                {Array.isArray(details) ? (
                  <ul className="mt-2 space-y-1">
                    {details.map((item, idx) => (
                      <li key={idx} className="text-xs text-blue-700 flex items-start gap-2">
                        <span className="flex-shrink-0 mt-0.5">→</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-blue-700 mt-2">{details}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Architectural Decisions & Rationale */}
      {decisions.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">🎯</span> Architectural Decisions
          </h3>
          <div className="space-y-3">
            {decisions.map((decision, index) => (
              <div key={index} className="rounded-lg border border-purple-200 bg-purple-50 p-4">
                <p className="text-sm font-bold text-purple-900">{decision.decision}</p>
                {decision.rationale && (
                  <div className="mt-3 ml-4 border-l-2 border-purple-200 pl-4">
                    <p className="text-[10px] font-semibold text-purple-700 uppercase tracking-wider">Why It Matters</p>
                    <p className="text-sm text-purple-700 mt-1">{decision.rationale}</p>
                  </div>
                )}
                {decision.trade_offs && (
                  <div className="mt-3 ml-4 border-l-2 border-purple-200 pl-4">
                    <p className="text-[10px] font-semibold text-purple-700 uppercase tracking-wider">Trade-offs</p>
                    <p className="text-sm text-purple-700 mt-1">{decision.trade_offs}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Technology Stack */}
      {payload.technology_stack && Object.keys(payload.technology_stack).length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">⚡</span> Technology Stack
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(payload.technology_stack).map(([category, techs]) => (
              <div key={category} className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-bold text-amber-900">{category}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {Array.isArray(techs) &&
                    techs.map((tech, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center rounded-full bg-white border border-amber-200 px-2.5 py-1 text-xs font-semibold text-amber-700"
                      >
                        {tech}
                      </span>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* NFR Alignment */}
      {payload.nfr_alignment && Object.keys(payload.nfr_alignment).length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
            <span className="text-lg">📊</span> Non-Functional Requirements Alignment
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(payload.nfr_alignment).map(([nfr, alignment]) => (
              <div key={nfr} className="rounded-lg border border-green-200 bg-green-50 p-4">
                <p className="text-sm font-bold text-green-900">{nfr}</p>
                <p className="text-sm text-green-700 mt-2">{alignment}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Assumptions, Risks & Trade-offs */}
      {(assumptions.length > 0 || risks.length > 0 || tradeOffs.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {assumptions.length > 0 && (
            <div className="rounded-xl border border-border bg-surface p-6">
              <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
                <span className="text-lg">💡</span> Assumptions
              </h3>
              <ul className="space-y-2">
                {assumptions.map((assumption, index) => (
                  <li key={index} className="flex gap-2 text-sm text-ink-soft">
                    <span className="flex-shrink-0 text-cyan-600">•</span>
                    <span>{assumption}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {risks.length > 0 && (
            <div className="rounded-xl border border-border bg-surface p-6">
              <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
                <span className="text-lg">⚠️</span> Risks
              </h3>
              <ul className="space-y-3">
                {risks.map((risk, index) => (
                  <div key={index} className="text-sm">
                    <p className="font-semibold text-red-700">{risk.description}</p>
                    {risk.impact && <p className="text-xs text-ink-soft mt-1">Impact: {risk.impact}</p>}
                    {risk.mitigation && (
                      <p className="text-xs text-ink-faint mt-1">→ {risk.mitigation}</p>
                    )}
                  </div>
                ))}
              </ul>
            </div>
          )}

          {tradeOffs.length > 0 && (
            <div className="rounded-xl border border-border bg-surface p-6">
              <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
                <span className="text-lg">⚖️</span> Trade-offs
              </h3>
              <ul className="space-y-2">
                {tradeOffs.map((tradeOff, index) => (
                  <li key={index} className="flex gap-2 text-sm text-ink-soft">
                    <span className="flex-shrink-0 text-orange-600">↔</span>
                    <span>{tradeOff}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Executive So What */}
      {payload.so_what && (
        <div className="rounded-xl border-2 border-cyan-400 bg-gradient-to-r from-cyan-50 to-cyan-100 p-6">
          <div className="flex items-start gap-4">
            <div className="flex-shrink-0">
              <CheckCircle size={24} className="text-cyan-700" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-cyan-900">Executive Takeaway</h3>
              <p className="text-base text-cyan-800 mt-2 leading-relaxed">{payload.so_what}</p>
            </div>
          </div>
        </div>
      )}

      {/* Export Section */}
      <div className="rounded-xl border border-border bg-surface p-6">
        <h3 className="text-sm font-bold text-ink mb-4 flex items-center gap-2">
          <Download size={16} /> Export Architecture
        </h3>
        <p className="text-xs text-ink-soft mb-4">
          Download your Solution Architecture as a professional document, image, or editable format.
        </p>
        <div className="flex flex-wrap gap-2">
          {(['png', 'pdf', 'docx', 'drawio'] as const).map((format) => (
            <button
              key={format}
              onClick={() => handleExport(format)}
              disabled={isExporting && exportingFormat === format}
              className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${
                exportingFormat === format
                  ? 'bg-cyan-600 text-white'
                  : 'border border-border bg-surface-alt text-ink-soft hover:bg-surface hover:border-cyan-400'
              } disabled:opacity-60`}
            >
              {exportingFormat === format && <span className="animate-spin">⟳</span>}
              {format === 'png' && '📸'}
              {format === 'pdf' && '📄'}
              {format === 'docx' && '📝'}
              {format === 'drawio' && '✎'}
              {format === 'drawio' ? 'Draw.io' : format.toUpperCase()}
            </button>
          ))}
        </div>
        <p className="text-xs text-ink-faint mt-3">
          Exports are generated from your architecture definition and are ready for sharing with stakeholders.
        </p>
      </div>
    </div>
  );
}
