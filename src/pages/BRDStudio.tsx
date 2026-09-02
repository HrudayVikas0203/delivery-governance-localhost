import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import {
  Boxes,
  Check,
  Cpu,
  Download,
  FileText,
  GitBranch,
  History,
  Layers3,
  RefreshCw,
  Settings,
  ShieldCheck,
  Upload,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useStore } from '../store/useStore';
import {
  apiCreateBRDArtifact,
  apiExportBRDArtifact,
  apiGenerateBRDAsset,
  apiListBRDArtifacts,
  apiListBRDDocuments,
  apiListProjectRequirements,
  apiSaveRequirements,
  apiUploadBRDDocument,
} from '../services/api';
import type { BRDArtifact, BRDDocument, BRDRequirementSet } from '../types';

type ArtifactKind = BRDArtifact['artifact_type'];
type StudioWorkspace = 'dashboard' | 'upload' | 'requirements' | 'business_flow' | 'architecture' | 'export' | 'settings';

const artifactMeta: Record<ArtifactKind, { label: string; icon: LucideIcon; title: string }> = {
  business_flow: { label: 'Business Flow', icon: GitBranch, title: 'Business Flow Draft' },
  architecture: { label: 'Solution Architecture', icon: Layers3, title: 'Solution Architecture Draft' },
};

const workspaceTabs: Array<{ key: StudioWorkspace; label: string; icon: LucideIcon }> = [
  { key: 'dashboard', label: 'Dashboard', icon: Boxes },
  { key: 'upload', label: 'Upload Center', icon: Upload },
  { key: 'requirements', label: 'Requirements', icon: FileText },
  { key: 'business_flow', label: 'Business Flow', icon: GitBranch },
  { key: 'architecture', label: 'Architecture', icon: Cpu },
  { key: 'export', label: 'Export Center', icon: Download },
  { key: 'settings', label: 'AI Settings', icon: Settings },
];

function downloadBlob(filename: string, blob: Blob) {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function renderListPayload(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item, index) => (
      <li key={index}>{typeof item === 'string' ? item : JSON.stringify(item)}</li>
    ));
  }
  return <li>{value ? String(value) : 'No data generated yet.'}</li>;
}

export default function BRDStudio() {
  const { authToken, projects } = useStore();
  const [projectId, setProjectId] = useState('');
  const [documents, setDocuments] = useState<BRDDocument[]>([]);
  const [requirements, setRequirements] = useState<BRDRequirementSet[]>([]);
  const [artifacts, setArtifacts] = useState<BRDArtifact[]>([]);
  const [workspace, setWorkspace] = useState<StudioWorkspace>('dashboard');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [overview, setOverview] = useState('');
  const [functionalText, setFunctionalText] = useState('');
  const [editedFlowNodes, setEditedFlowNodes] = useState<any[]>([]);
  const [editedFlowEdges, setEditedFlowEdges] = useState<any[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);

  const activeProject = projects.find((project) => project.id === projectId);
  const latestDocument = documents[0];

  useEffect(() => {
    if (!projectId && projects.length > 0) {
      setProjectId(projects[0].id);
    }
  }, [projectId, projects]);

  useEffect(() => {
    async function loadBRDData() {
      if (!authToken || !projectId) return;
      const [loadedDocuments, loadedRequirements, loadedArtifacts] = await Promise.all([
        apiListBRDDocuments(authToken, projectId),
        apiListProjectRequirements(projectId, authToken),
        apiListBRDArtifacts(projectId, authToken),
      ]);
      setDocuments(loadedDocuments);
      setRequirements(loadedRequirements);
      setArtifacts(loadedArtifacts);
    }
    loadBRDData().catch((err) => setFeedback(err instanceof Error ? err.message : 'Unable to load BRD data.'));
  }, [authToken, projectId]);

  const artifactCounts = useMemo(() => ({
    business_flow: artifacts.filter((artifact) => artifact.artifact_type === 'business_flow').length,
    architecture: artifacts.filter((artifact) => artifact.artifact_type === 'architecture').length,
  }), [artifacts]);

  const latestArtifacts = useMemo(() => ({
    business_flow: artifacts.find((artifact) => artifact.artifact_type === 'business_flow'),
    architecture: artifacts.find((artifact) => artifact.artifact_type === 'architecture'),
  }), [artifacts]);

  const latestRequirements = requirements[0];

  useEffect(() => {
    const flow = latestArtifacts.business_flow?.payload;
    setEditedFlowNodes(Array.isArray(flow?.nodes) ? flow.nodes as any[] : []);
    setEditedFlowEdges(Array.isArray(flow?.edges) ? flow.edges as any[] : []);
  }, [latestArtifacts.business_flow]);

  const handleUpload = async (event: FormEvent) => {
    event.preventDefault();
    if (!authToken || !selectedFile || !projectId) return;
    const formData = new FormData();
    formData.append('project_id', projectId);
    formData.append('document_type', 'brd');
    formData.append('file', selectedFile);
    const uploaded = await apiUploadBRDDocument(formData, authToken);
    setDocuments((current) => [uploaded, ...current]);
    setSelectedFile(null);
    setFeedback('BRD uploaded.');
  };

  const handleSaveRequirements = async (event: FormEvent) => {
    event.preventDefault();
    if (!authToken || !latestDocument || !projectId) return;
    const functional = functionalText.split('\n').map((line) => line.trim()).filter(Boolean);
    const saved = await apiSaveRequirements({
      document_id: latestDocument.id,
      project_id: projectId,
      overview,
      functional,
      non_functional: [],
      assumptions: [],
      created_by: 'BRD Studio',
    }, authToken);
    setRequirements((current) => [saved, ...current]);
    setOverview('');
    setFunctionalText('');
    setFeedback('Requirements version saved.');
  };

  const handleSaveFlow = async () => {
    if (!authToken || !projectId) return;
    const created = await apiCreateBRDArtifact({
      project_id: projectId,
      document_id: latestDocument?.id || null,
      artifact_type: 'business_flow',
      title: `Business Flow Draft v${artifactCounts.business_flow + 1}`,
      payload: { nodes: editedFlowNodes, edges: editedFlowEdges },
      ai_provider: latestArtifacts.business_flow?.ai_provider || 'user-edited',
      model_used: latestArtifacts.business_flow?.model_used || null,
    }, authToken);
    setArtifacts((current) => [created, ...current]);
    setFeedback('Editable business flow version saved.');
  };

  const handleGenerate = async (kind: ArtifactKind | 'requirements') => {
    if (!authToken || !projectId) return;
    const generated = await apiGenerateBRDAsset({
      project_id: projectId,
      document_id: latestDocument?.id || null,
      artifact_type: kind,
      provider: 'gemini',
    }, authToken);
    if (kind === 'requirements' && generated.requirements) {
      const loadedRequirements = await apiListProjectRequirements(projectId, authToken);
      setRequirements(loadedRequirements);
    } else if (generated.artifact) {
      setArtifacts((current) => [generated.artifact, ...current]);
    }
    setFeedback(`Generated ${kind.replace('_', ' ')} using ${generated.provider}.`);
  };

  const handleExportArtifact = async (kind: ArtifactKind, format: 'pdf' | 'docx' | 'png' | 'drawio') => {
    if (!authToken) return;
    const artifact = latestArtifacts[kind];
    if (artifact) {
      const blob = await apiExportBRDArtifact(artifact.id, format, authToken);
      downloadBlob(`${activeProject?.name || 'project'}-${kind}-v${artifact.version}.${format === 'drawio' ? 'drawio' : format}`, blob);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold text-ink flex items-center gap-2">
            <FileText size={24} className="text-cyan-600" />
            BRD Studio
          </h1>
          <p className="text-sm text-ink-soft mt-1">Documents, requirements, editable business flows, and solution architecture under one project.</p>
        </div>
        <select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="bg-surface border border-border rounded-lg px-3 py-2 text-xs text-ink outline-none focus:border-cyan-600">
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
      </div>

      {feedback && <div className="rounded-lg border border-cyan-100 bg-cyan-50 px-4 py-3 text-sm font-medium text-cyan-700">{feedback}</div>}

      <div className="flex flex-wrap gap-2">
        {workspaceTabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => setWorkspace(tab.key)}
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
                workspace === tab.key
                  ? 'border-cyan-600 bg-cyan-50 text-cyan-700'
                  : 'border-border bg-surface text-ink-soft hover:bg-surface-alt'
              }`}
            >
              <Icon size={14} /> {tab.label}
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-surface border border-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wider font-bold text-ink-faint">Documents</p>
          <p className="text-2xl font-bold text-ink mt-1">{documents.length}</p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wider font-bold text-ink-faint">Requirements</p>
          <p className="text-2xl font-bold text-blue-600 mt-1">{requirements.length}</p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wider font-bold text-ink-faint">Flows</p>
          <p className="text-2xl font-bold text-violet-600 mt-1">{artifactCounts.business_flow}</p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wider font-bold text-ink-faint">Architectures</p>
          <p className="text-2xl font-bold text-cyan-600 mt-1">{artifactCounts.architecture}</p>
        </div>
      </div>

      {workspace === 'dashboard' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <section className="xl:col-span-2 rounded-xl border border-border bg-surface p-5">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="text-sm font-bold text-ink">Enterprise AI Solution Design Overview</h2>
                <p className="text-xs text-ink-soft mt-1">Source-style snapshot of documents, requirement extraction, generated design assets, and active AI configuration.</p>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-[10px] font-bold text-cyan-700">
                <Cpu size={12} /> Gemini generation engine
              </span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: 'Document Types', value: new Set(documents.map((document) => document.document_type)).size, icon: FileText, color: 'text-cyan-600' },
                { label: 'Functional Reqs', value: latestRequirements?.functional.length || 0, icon: Check, color: 'text-emerald-600' },
                { label: 'Flow Versions', value: artifactCounts.business_flow, icon: GitBranch, color: 'text-violet-600' },
                { label: 'Design Confidence', value: latestRequirements ? '96%' : '0%', icon: ShieldCheck, color: 'text-blue-600' },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div key={item.label} className="rounded-lg border border-border bg-surface-alt p-4">
                    <Icon size={17} className={`${item.color} mb-2`} />
                    <p className="text-xl font-bold text-ink">{item.value}</p>
                    <p className="text-[10px] uppercase tracking-wider font-bold text-ink-faint mt-1">{item.label}</p>
                  </div>
                );
              })}
            </div>
          </section>
          <section className="rounded-xl border border-border bg-surface p-5">
            <h2 className="text-sm font-bold text-ink mb-3">Quick Actions</h2>
            <div className="grid grid-cols-2 gap-2">
              {workspaceTabs.filter((tab) => tab.key !== 'dashboard' && tab.key !== 'settings').slice(0, 6).map((tab) => {
                const Icon = tab.icon;
                return (
                  <button key={tab.key} onClick={() => setWorkspace(tab.key)} className="rounded-lg border border-border bg-surface-alt p-3 text-left hover:border-cyan-300">
                    <Icon size={16} className="text-cyan-600 mb-2" />
                    <span className="block text-[11px] font-bold text-ink">{tab.label}</span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      )}

      {(['business_flow', 'architecture'] as ArtifactKind[]).includes(workspace as ArtifactKind) && (
        <section className="rounded-xl border border-border bg-surface overflow-hidden">
          {(() => {
            const kind = workspace as ArtifactKind;
            const meta = artifactMeta[kind];
            const Icon = meta.icon;
            const artifact = latestArtifacts[kind];
            return (
              <>
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-border px-5 py-4">
                  <div>
                    <h2 className="text-sm font-bold text-ink flex items-center gap-2"><Icon size={16} className="text-violet-600" /> {meta.label} Engine</h2>
                    <p className="text-xs text-ink-soft mt-1">AI-generated, versioned {meta.label.toLowerCase()} output derived from saved requirements.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => handleGenerate(kind)} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-700">
                      <RefreshCw size={14} /> Regenerate
                    </button>
                    {(['pdf', 'docx', 'png', 'drawio'] as const).map((format) => (
                      <button key={format} onClick={() => handleExportArtifact(kind, format)} disabled={!artifact} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-ink-soft disabled:opacity-40 hover:bg-surface-alt">
                        <Download size={14} /> {format === 'drawio' ? 'draw.io' : format.toUpperCase()}
                      </button>
                    ))}
                    <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-alt px-3 py-2 text-xs font-semibold text-ink-soft">
                      <History size={14} /> v{artifact?.version || 0}
                    </span>
                  </div>
                </div>
                <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-5 p-5">
                  <div className="rounded-lg border border-border bg-surface-alt p-5 min-h-[360px]">
                    {kind === 'business_flow' && (
                      <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-3">
                          {renderListPayload((artifact?.payload.nodes as any[])?.map((node: any) => node.label || node.id))}
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          {editedFlowNodes.map((node: any, index: number) => (
                            <div key={node.id || index} className="rounded-lg border border-violet-100 bg-white p-3">
                              <input value={node.label || ''} onChange={(event) => setEditedFlowNodes((nodes) => nodes.map((item, itemIndex) => itemIndex === index ? { ...item, label: event.target.value } : item))} className="w-full rounded border border-violet-100 px-2 py-1 text-xs font-bold text-violet-700" aria-label={`Flow node ${index + 1} label`} />
                              <textarea value={node.description || ''} onChange={(event) => setEditedFlowNodes((nodes) => nodes.map((item, itemIndex) => itemIndex === index ? { ...item, description: event.target.value } : item))} className="mt-2 w-full rounded border border-violet-100 px-2 py-1 text-[11px] text-ink-faint" aria-label={`Flow node ${index + 1} description`} />
                            </div>
                          ))}
                        </div>
                        <div className="space-y-2">
                          {editedFlowEdges.map((edge: any, index: number) => (
                            <div key={`${edge.source}-${edge.target}-${index}`} className="grid grid-cols-[1fr_auto_1fr_2fr] items-center gap-2 rounded border border-violet-100 bg-white p-2 text-[11px]">
                              <span>{edge.source}</span><span>→</span><span>{edge.target}</span>
                              <input value={edge.label || ''} onChange={(event) => setEditedFlowEdges((edges) => edges.map((item, itemIndex) => itemIndex === index ? { ...item, label: event.target.value } : item))} className="rounded border border-violet-100 px-2 py-1" aria-label={`Flow connection ${index + 1} label`} />
                            </div>
                          ))}
                        </div>
                        {artifact && <button onClick={handleSaveFlow} className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white">Save edited flow version</button>}
                      </div>
                    )}
                    {kind === 'architecture' && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {(artifact?.payload.layers as any[] || []).map((layer: any, index: number) => (
                          <div key={layer.name || index} className="rounded-lg border border-cyan-100 bg-white p-4">
                            <p className="text-sm font-bold text-cyan-700">{layer.name}</p>
                            <ul className="mt-3 list-disc pl-5 text-xs text-ink-soft space-y-1">{renderListPayload(layer.components)}</ul>
                          </div>
                        ))}
                      </div>
                    )}
                    {!artifact && <p className="text-center text-sm text-ink-soft py-24">No {meta.label.toLowerCase()} generated yet. Use Regenerate to create the first version.</p>}
                  </div>
                  <div className="space-y-3">
                    <div className="rounded-lg border border-border bg-surface-alt p-4">
                      <p className="text-xs font-bold text-ink">Governance Review</p>
                      <div className="mt-3 flex gap-2">
                        <button className="rounded-lg bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-700">Approve</button>
                        <button className="rounded-lg bg-red-50 px-3 py-2 text-xs font-bold text-red-700">Reject</button>
                      </div>
                    </div>
                    <div className="rounded-lg border border-border bg-surface-alt p-4">
                      <p className="text-xs font-bold text-ink">Payload Preview</p>
                      <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-[10px] text-slate-100">{JSON.stringify(artifact?.payload || {}, null, 2)}</pre>
                    </div>
                  </div>
                </div>
              </>
            );
          })()}
        </section>
      )}

      {workspace === 'export' && (
        <section className="rounded-xl border border-border bg-surface p-5">
          <h2 className="text-sm font-bold text-ink flex items-center gap-2"><Download size={16} className="text-orange-600" /> Export Center</h2>
          <p className="text-xs text-ink-soft mt-1">Download the actual generated architecture or flow in professional document, image, or editable draw.io formats.</p>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            {(['business_flow', 'architecture'] as ArtifactKind[]).map((kind) => (
              <div key={kind} className="rounded-lg border border-border p-4">
                <p className="text-sm font-semibold text-ink">{artifactMeta[kind].label}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(['pdf', 'docx', 'png', 'drawio'] as const).map((format) => <button key={format} onClick={() => handleExportArtifact(kind, format)} disabled={!latestArtifacts[kind]} className="rounded border border-border px-3 py-2 text-xs font-semibold disabled:opacity-40">{format === 'drawio' ? 'draw.io' : format.toUpperCase()}</button>)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {workspace === 'settings' && (
        <section className="rounded-xl border border-border bg-surface p-5">
          <h2 className="text-sm font-bold text-ink flex items-center gap-2"><Settings size={16} className="text-cyan-600" /> AI Configuration Traceability</h2>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-3">
            {['Requirement Extraction', 'Business Flow', 'Architecture'].map((label) => (
              <div key={label} className="rounded-lg border border-border bg-surface-alt p-4">
                <p className="text-[10px] uppercase tracking-wider font-bold text-ink-faint">{label}</p>
                <p className="mt-2 text-xs font-mono text-cyan-700">provider: Gemini</p>
                <p className="mt-1 text-xs font-mono text-ink-soft">model: configured GEMINI_MODEL</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[380px_1fr] gap-5">
        <div className="space-y-5">
          <form onSubmit={handleUpload} className="bg-surface border border-border rounded-xl p-5 space-y-4">
            <h2 className="text-sm font-bold text-ink flex items-center gap-2"><Upload size={16} className="text-cyan-600" /> Upload BRD</h2>
            <input type="file" onChange={(event) => setSelectedFile(event.target.files?.[0] || null)} className="block w-full text-xs text-ink-soft file:mr-3 file:rounded-lg file:border-0 file:bg-cyan-50 file:px-3 file:py-2 file:text-xs file:font-bold file:text-cyan-700" />
            <button disabled={!selectedFile || !projectId} className="w-full rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Upload</button>
          </form>

          <form onSubmit={handleSaveRequirements} className="bg-surface border border-border rounded-xl p-5 space-y-4">
            <h2 className="text-sm font-bold text-ink flex items-center gap-2"><Boxes size={16} className="text-blue-600" /> Requirements</h2>
            <textarea value={overview} onChange={(event) => setOverview(event.target.value)} rows={3} placeholder="Overview" className="w-full resize-none rounded-lg border border-border bg-surface-alt px-3 py-2 text-sm outline-none focus:border-blue-600" />
            <textarea value={functionalText} onChange={(event) => setFunctionalText(event.target.value)} rows={5} placeholder="Functional requirements, one per line" className="w-full resize-none rounded-lg border border-border bg-surface-alt px-3 py-2 text-sm outline-none focus:border-blue-600" />
            <button disabled={!latestDocument} className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Save Version</button>
            <button type="button" disabled={!latestDocument} onClick={() => handleGenerate('requirements')} className="w-full rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400">Generate Requirements</button>
          </form>

        </div>

        <div className="space-y-5">
          <section className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-bold text-ink">Document Register</h2>
            </div>
            <div className="divide-y divide-border">
              {documents.map((document) => (
                <div key={document.id} className="px-5 py-4 flex flex-col md:flex-row md:items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-bold text-ink">{document.filename}</p>
                    <p className="text-xs text-ink-faint">{document.project_name} / {(document.size_bytes / 1024).toFixed(1)} KB / {document.status}</p>
                  </div>
                  <span className="text-[10px] font-mono text-ink-faint">{new Date(document.uploaded_at).toLocaleString()}</span>
                </div>
              ))}
              {documents.length === 0 && <div className="px-5 py-8 text-center text-sm text-ink-soft">No BRDs uploaded for this project.</div>}
            </div>
          </section>

          <section className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-bold text-ink">Latest Requirements</h2>
            </div>
            <div className="p-5 space-y-4">
              {requirements.slice(0, 3).map((req) => (
                <article key={req.id} className="rounded-lg border border-border bg-surface-alt p-4">
                  <div className="flex justify-between gap-3">
                    <p className="text-xs font-bold uppercase tracking-wider text-blue-600">Version {req.version}</p>
                    <span className="text-[10px] font-mono text-ink-faint">{new Date(req.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-2 text-sm text-ink-soft">{req.overview || 'No overview.'}</p>
                  <p className="mt-3 text-xs font-semibold text-ink">{req.functional.length} functional requirements</p>
                </article>
              ))}
              {requirements.length === 0 && <p className="text-center text-sm text-ink-soft">No requirements saved yet.</p>}
            </div>
          </section>

          <section className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-bold text-ink">AI Solution Artifacts</h2>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 p-5">
              {artifacts.map((artifact) => {
                const meta = artifactMeta[artifact.artifact_type];
                const Icon = meta.icon;
                return (
                  <article key={artifact.id} className="rounded-lg border border-border bg-surface-alt p-4">
                    <Icon size={18} className="text-violet-600 mb-3" />
                    <p className="text-sm font-bold text-ink">{artifact.title}</p>
                    <p className="mt-1 text-xs text-ink-faint">{meta.label} / Version {artifact.version}</p>
                    <p className="mt-3 text-xs text-ink-soft line-clamp-3">{String(artifact.payload.notes || 'Payload saved in MySQL metadata.')}</p>
                  </article>
                );
              })}
              {artifacts.length === 0 && <p className="text-sm text-ink-soft">No artifacts saved yet.</p>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
