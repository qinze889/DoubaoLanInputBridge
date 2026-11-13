import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronDown, Cloud, Globe, LoaderCircle, Network, RotateCw, Wifi } from 'lucide-react'

export type ConnectionState = {
  mode: string
  enabled: boolean
  ready: boolean
  phase: string
  url: string
  error: string
  cloudflare?: { stage: string; elapsed_seconds: number; protocol: string; last_error: string; log_tail: string } | null
  p2p: { connections: number }
  modes: { id: string; title: string; description: string; available: boolean; configured: boolean; experimental?: boolean }[]
}
type ApiGet = <T>(path: string, params?: Record<string, string | number>) => Promise<T & { ok: boolean }>
type ApiPost = <T>(path: string, data?: Record<string, unknown>) => Promise<T & { ok: boolean }>

const icons = { public: Globe, cloudflare: Cloud, p2p: Network, lan: Wifi }
const cloudflareStages: Record<string, string> = {
  allocating: '正在申请公网地址', connecting: '正在连接 Cloudflare',
  verifying: '正在验证公网访问', reconnecting: '连接中断，正在恢复', ready: '公网访问已验证', off: '已关闭',
}

export default function ConnectionPanel({ apiGet, apiPost, onState }: {
  apiGet: ApiGet; apiPost: ApiPost; onState?: (state: ConnectionState) => void
}) {
  const [state, setState] = useState<ConnectionState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    const next = await apiGet<ConnectionState>('/desktop/connections')
    setState(next)
    onState?.(next)
  }, [apiGet, onState])
  useEffect(() => {
    let active = true
    const read = () => { if (active) void refresh().catch(() => {}) }
    read()
    const timer = window.setInterval(read, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [refresh])

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try { await action(); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '连接配置未完成') }
    finally { setBusy(false) }
  }

  const mainModes = state?.modes.filter(mode => mode.id !== 'p2p') ?? []
  const p2p = state?.modes.find(mode => mode.id === 'p2p')
  const activeTitle = state?.modes.find(mode => mode.id === state.mode)?.title ?? '连接'
  const cloudflareStage = state?.cloudflare && cloudflareStages[state.cloudflare.stage]
  const status = !state?.enabled ? '连接已关闭' : state.ready ? activeTitle + '已就绪' : state.phase === 'error' ? '连接失败' : cloudflareStage || '正在建立连接'

  function modeButton(mode: ConnectionState['modes'][number]) {
    const Icon = icons[mode.id as keyof typeof icons] || Globe
    return <button
      key={mode.id}
      className={'connection-option ' + (state?.mode === mode.id ? 'selected' : '')}
      type="button"
      disabled={busy || !mode.available}
      aria-pressed={state?.mode === mode.id}
      onClick={() => void run(() => apiPost('/desktop/connections', { mode: mode.id, enabled: true }))}
    >
      <Icon size={20}/>
      <strong>{mode.title}</strong>
      {mode.id === 'cloudflare' && <small className="mode-recommended">免配置 · 一键启用</small>}
      {state?.mode === mode.id && <Check className="mode-check" size={15}/>}
    </button>
  }

  return <section className="connection-panel">
    <div className="connection-heading">
      <h3>连接方式</h3>
      <label className="connection-toggle">
        <input role="switch" aria-label="启用连接" type="checkbox"
          checked={state?.enabled ?? false}
          disabled={busy || !state}
          onChange={event => void run(() => apiPost('/desktop/connections', { mode: state?.mode, enabled: event.target.checked }))}/>
        <span aria-hidden="true"/>
      </label>
    </div>

    <div className="connection-options">{mainModes.map(modeButton)}</div>
    <p className="connection-description">{state?.modes.find(mode => mode.id === state.mode)?.description || '同一网络或跨网络，都可以把手机与电脑连接起来。'}</p>

    {p2p && <details className="connection-advanced">
      <summary><ChevronDown size={15}/>高级连接 · 实验功能</summary>
      <div className="connection-options connection-experiments">{modeButton(p2p)}</div>
      <p>P2P 目前不保证跨 NAT 成功，连接失败需要手动切回公网或局域网；不会隐式中转文件。</p>
    </details>}

    <div className="connection-heading connection-status-actions">
      <span role="status">{busy && <LoaderCircle size={14} className="spin"/>}{status}{state?.mode === 'p2p' && state.ready && ' · ' + state.p2p.connections + ' 个直连'}</span>
      {state?.enabled && !state.ready && !busy && <button className="connection-retry" type="button" onClick={() => void run(() => apiPost('/desktop/connections', { mode: state.mode, enabled: true, retry: true }))}><RotateCw size={14}/>重试</button>}
      <label className="connection-import">导入自建服务器配置
        <input type="file" accept=".json,application/json" hidden disabled={busy} onChange={event => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) void run(async () => {
            if (file.size > 16384) throw Error('配置文件过大')
            await apiPost('/desktop/connections/config', { config: JSON.parse(await file.text()) })
          })
        }}/>
      </label>
    </div>
    {(error || state?.error) && <p className="machine-error" role="alert">{error || state?.error}</p>}
    {state?.enabled && state.cloudflare && <details className="connection-advanced">
      <summary><ChevronDown size={15}/>连接诊断</summary>
      <p>{cloudflareStage || state.cloudflare.stage} · {state.cloudflare.elapsed_seconds} 秒 · HTTP/2（TCP 7844）</p>
      {state.cloudflare.last_error && <p className="machine-error">{state.cloudflare.last_error}</p>}
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 240, overflow: 'auto' }}>{state.cloudflare.log_tail || '等待 Cloudflare 日志…'}</pre>
    </details>}
  </section>
}

