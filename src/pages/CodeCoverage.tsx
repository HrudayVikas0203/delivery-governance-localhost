import { useCallback, useEffect, useState } from 'react';
import { BarChart3, Download, ExternalLink, RefreshCw } from 'lucide-react';
import { useStore } from '../store/useStore';
import { apiDownloadCoverageReport, apiGetCoverage, apiRefreshCoverage } from '../services/api';

function CoverageStatus({ status }: { status?: string }) {
  const className = status === 'Healthy' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : status === 'Needs Attention' ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-rose-50 text-rose-700 border-rose-200';
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${className}`}>{status || 'Unknown'}</span>;
}

export default function CodeCoverage() {
  const authToken = useStore(s => s.authToken);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!authToken) return;
    setLoading(true);
    try { setData(await apiGetCoverage(authToken)); setError(''); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load coverage.'); }
    finally { setLoading(false); }
  }, [authToken]);
  useEffect(() => { void load(); }, [load]);
  const refresh = async () => {
    if (!authToken) return;
    setRefreshing(true);
    try { setData(await apiRefreshCoverage(authToken)); setError(''); }
    catch (err) { setError(err instanceof Error ? err.message : 'Coverage refresh failed.'); }
    finally { setRefreshing(false); }
  };
  const report = async (kind: 'html' | 'lcov') => {
    if (!authToken) return;
    try {
      const blob = await apiDownloadCoverageReport(kind, authToken);
      const url = URL.createObjectURL(blob);
      if (kind === 'html') window.open(url, '_blank', 'noopener,noreferrer');
      else { const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'lcov.info'; anchor.click(); }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) { setError(err instanceof Error ? err.message : 'Coverage report is unavailable.'); }
  };
  const metrics = data?.metrics || {};
  const metricLabel: Record<string, string> = { statements: 'Statements', branches: 'Branches', functions: 'Functions', lines: 'Lines' };

  return <div className="space-y-6">
    <div><h1 className="text-2xl font-display font-bold text-ink">Code Coverage</h1><p className="mt-1 text-sm text-ink-soft">Project-wide unit-test coverage from the latest real backend test analysis.</p></div>
    <section className="bg-surface border border-border rounded-xl p-5 shadow-sm space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><h2 className="flex items-center gap-2 text-base font-bold text-ink"><BarChart3 size={18} className="text-blue-600" /> Code Quality &amp; Unit Test Coverage</h2><p className="mt-1 text-xs text-ink-soft">Live pytest + Coverage.py analysis across application source.</p></div><div className="flex items-center gap-2"><CoverageStatus status={data?.overall_status} /><button onClick={refresh} disabled={refreshing || !authToken} className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60"><RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />{refreshing ? 'Analyzing…' : 'Refresh Coverage'}</button></div></div>
      {loading ? <p className="text-sm text-ink-soft">Loading the latest coverage report…</p> : error ? <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : !data?.available ? <div className="rounded-lg border border-dashed border-border p-5 text-sm text-ink-soft">No coverage report is available yet. Use Refresh Coverage to run the actual unit-test suite.</div> : <>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5"><div className="flex items-center gap-4 rounded-xl border border-blue-100 bg-blue-50/50 p-4 lg:col-span-1"><div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-[7px] border-blue-500 bg-white text-xl font-bold text-ink">{data.overall?.toFixed(1)}%</div><div><p className="text-xs font-semibold text-ink-soft">Overall Coverage</p><p className="mt-1 text-xs text-ink-soft">Statements threshold: {data.thresholds.statements}%</p></div></div>{Object.entries(metricLabel).map(([key, label]) => <div key={key} className="rounded-xl border border-border p-4"><p className="text-xs font-semibold text-ink-soft">{label}</p><p className="mt-1 text-2xl font-bold text-ink">{metrics[key] == null ? '—' : `${metrics[key].toFixed(1)}%`}</p><p className="mt-1 text-[10px] text-ink-faint">Target {data.thresholds[key]}%</p></div>)}</div>
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2"><div className="rounded-xl border border-border p-4"><h3 className="text-sm font-bold text-ink">Coverage Breakdown</h3><div className="mt-4 space-y-3">{Object.entries(metricLabel).map(([key, label]) => { const value = metrics[key]; return <div key={key} className="grid grid-cols-[85px_1fr_48px] items-center gap-3 text-xs"><span className="text-ink-soft">{label}</span><div className="h-2.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${value >= data.thresholds[key] ? 'bg-emerald-500' : 'bg-amber-500'}`} style={{ width: `${value ?? 0}%` }} /></div><span className="text-right font-bold text-ink">{value == null ? 'N/A' : `${value.toFixed(1)}%`}</span></div>; })}</div></div><div className="rounded-xl border border-border p-4"><h3 className="text-sm font-bold text-ink">Test Statistics</h3><div className="mt-4 grid grid-cols-3 gap-3 text-center">{Object.entries(data.test_statistics).map(([key, value]) => <div key={key} className="rounded-lg bg-surface-alt p-2"><p className="text-lg font-bold text-ink">{key === 'duration' ? `${value}s` : String(value)}</p><p className="text-[10px] capitalize text-ink-soft">{key}</p></div>)}</div><p className="mt-4 text-xs text-ink-soft">Last analyzed: {new Date(data.last_analyzed).toLocaleString()} · <span className="font-semibold text-emerald-700">{data.test_status || 'Latest result available'}</span></p></div></div>
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2"><div className="rounded-xl border border-border p-4"><h3 className="text-sm font-bold text-ink">Coverage by Module / Folder</h3><div className="mt-3 max-h-52 overflow-auto"><table className="w-full text-left text-xs"><thead className="text-ink-faint"><tr><th className="pb-2">Module</th><th>Coverage</th><th>Status</th></tr></thead><tbody>{data.modules.map((item: any) => <tr key={item.module} className="border-t border-border"><td className="py-2 font-medium text-ink">{item.module}</td><td>{item.coverage.toFixed(1)}%</td><td><CoverageStatus status={item.status} /></td></tr>)}</tbody></table></div></div><div className="rounded-xl border border-border p-4"><h3 className="text-sm font-bold text-ink">Low Coverage Areas</h3><div className="mt-3 max-h-52 space-y-2 overflow-auto">{data.low_areas.length ? data.low_areas.map((item: any) => <div key={item.file} className="flex items-center justify-between rounded-lg bg-rose-50/50 px-3 py-2 text-xs"><span className="truncate pr-3 font-medium text-ink">{item.file}</span><span className="whitespace-nowrap font-bold text-rose-700">{item.coverage.toFixed(1)}%</span></div>) : <p className="text-xs text-emerald-700">No files are below the statement threshold.</p>}</div></div></div>
        {data.history.length > 1 && <div className="rounded-xl border border-border p-4"><h3 className="text-sm font-bold text-ink">Coverage Trend</h3><div className="mt-3 flex h-16 items-end gap-1">{data.history.map((point: any) => <div key={point.timestamp} title={`${new Date(point.timestamp).toLocaleString()}: ${point.overall}%`} className="min-w-2 flex-1 rounded-t bg-blue-500" style={{ height: `${point.overall}%` }} />)}</div><p className="mt-2 text-[10px] text-ink-faint">Historical runs retained from actual coverage refreshes only.</p></div>}
        <div className="flex flex-wrap gap-2">{data.reports.html && <button onClick={() => report('html')} className="inline-flex items-center gap-1 text-xs font-bold text-blue-700 hover:text-blue-900"><ExternalLink size={13} /> View HTML report</button>}{data.reports.lcov && <button onClick={() => report('lcov')} className="inline-flex items-center gap-1 text-xs font-bold text-blue-700 hover:text-blue-900"><Download size={13} /> Download LCOV</button>}</div>
      </>}
    </section>
  </div>;
}
