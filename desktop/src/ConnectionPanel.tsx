import { useCallback, useEffect, useState } from 'react'
import { Check, Cloud, Globe, Network, Wifi, LoaderCircle } from 'lucide-react'
export type ConnectionState = { mode: string; enabled: boolean; ready: boolean; phase: string; url: string; error: string; p2p: { connections: number }; modes: { id: string; title: string; description: string; available: boolean; configured: boolean }[] }
type ApiGet = <T>(path: string, params?: Record<string, string | number>) => Promise<T & { ok: boolean }>
type ApiPost = <T>(path: string, data?: Record<string, unknown>) => Promise<T & { ok: boolean }>
const icons = { public: Globe, cloudflare: Cloud, p2p: Network, lan: Wifi }
export default function ConnectionPanel({ apiGet, apiPost, onState }: { apiGet: ApiGet; apiPost: ApiPost; onState?: (state: ConnectionState) => void }) {
  const [state, setState] = useState<ConnectionState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => { const next = await apiGet<ConnectionState>('/desktop/connections'); setState(next); onState?.(next) }, [apiGet, onState])
  useEffect(() => { let active = true; const read = () => { if (active) void refresh().catch(() => {}) }; read(); const timer = window.setInterval(read, 2000); return () => { active = false; window.clearInterval(timer) } }, [refresh])
  async function run(action: () => Promise<unknown>) { setBusy(true); setError(''); try { await action(); await refresh() } catch (e) { setError(e instanceof Error ? e.message : '连接配置未完成') } finally { setBusy(false) } }
  return <section className="connection-panel">
    <div className="connection-heading"><h3>连接方式</h3><label className="connection-toggle"><input role="switch" aria-label="启用连接" type="checkbox" checked={state?.enabled || false} disabled={busy || !state} onChange={e => void run(() => apiPost('/desktop/connections', { mode: state?.mode, enabled: e.target.checked }))} /><span aria-hidden="true" /></label></div>
    <div className="connection-options">{state?.modes.map(mode => { const Icon = icons[mode.id as keyof typeof icons] || Globe; return <button key={mode.id} className={`connection-option ${state.mode === mode.id ? 'selected' : ''}`} disabled={busy || !mode.available} aria-pressed={state.mode === mode.id} onClick={() => void run(() => apiPost('/desktop/connections', { mode: mode.id, enabled: true }))}><Icon size={20} /><strong>{mode.title}</strong>{state.mode === mode.id && <Check className="mode-check" size={15} />}</button> })}</div>
    <p>{state?.modes.find(m => m.id === state.mode)?.description}</p>
    <div className="connection-heading"><span role="status">{busy && <LoaderCircle size={14} className="spin" />}{state?.ready ? `${state.modes.find(m => m.id === state.mode)?.title}已就绪` : state?.enabled ? '正在准备连接' : '连接已关闭'}{state?.mode === 'p2p' && state.ready && ` · ${state.p2p.connections} 个直连`}</span><label className="connection-import">导入服务器配置<input type="file" accept=".json,application/json" hidden disabled={busy} onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void run(async () => { if (file.size > 16384) throw Error('配置文件过大'); await apiPost('/desktop/connections/config', { config: JSON.parse(await file.text()) }) }) }} /></label></div>
    {(error || state?.error) && <p className="machine-error" role="alert">{error || state?.error}</p>}
  </section>
}
