import { type UIEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { openUrl } from '@tauri-apps/plugin-opener'
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow'
import { QRCodeSVG } from 'qrcode.react'
import {
  Archive,
  Check,
  ClipboardCopy,
  File,
  FileSearch,
  FolderOpen,
  Image,
  LoaderCircle,
  MonitorSmartphone,
  Play,
  QrCode,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Square,
  Upload,
  Video,
  X,
} from 'lucide-react'
import './App.css'

type RuntimeInfo = { running: boolean; port: number | null; key: string }
type BridgeState = {
  version: string
  port: number
  key: string
  mobile_url: string
  local_url: string
  host: string
  data_dir: string
}
type HistorySummary = { kind: string; preview: string; info: string }
type HistoryRecord = {
  id: string
  type: 'text' | 'file'
  text?: string
  ts: number
  category: string
  has_thumbnail: boolean
  summary: HistorySummary
}
type HistoryResponse = { items: HistoryRecord[]; total: number; has_more: boolean }
type TunnelConfig = {
  enabled: boolean
  name: string
  public_url: string
  cloudflared_path: string
  metrics_port: number
  config_path: string
}
type TunnelStatus = {
  enabled: boolean
  name: string
  public_url: string
  probe_url: string
  ready: boolean
  running: boolean
  managed: boolean
  owned_pid: number
  cloudflared_path: string
  cloudflared_available: boolean
  stop_result?: { stopped: boolean; reason: string }
}
type TunnelCandidate = {
  name: string
  config_path: string
  tunnel: string
  hostnames: string[]
  public_url: string
}
type TunnelResponse = {
  config: TunnelConfig
  status: TunnelStatus
  candidates: TunnelCandidate[]
}
type ConfigResponse = {
  minimax_configured: boolean
  minimax_model: string
  update_url: string
  update_source: string
  tunnel: TunnelConfig
  tunnel_status: TunnelStatus
}
type UpdateResult = {
  configured: boolean
  available: boolean
  version: string
  notes?: string
  error?: string
  source?: string
}

const CATEGORIES = [
  ['all', '全部内容'],
  ['text', '文字'],
  ['image', '图片'],
  ['video', '视频'],
  ['file', '文件'],
] as const

// 更新源改成 GitHub 之后，自动检查必须收敛：未认证的 releases API 只有 60 次/小时，
// 原本 5 分钟一轮 + 聚焦节流会把它打满。服务端另有 30 分钟 TTL 缓存兜底。
const AUTO_UPDATE_INITIAL_DELAY_MS = 1_200
const AUTO_UPDATE_INTERVAL_MS = 30 * 60 * 1000
const AUTO_UPDATE_FOCUS_THROTTLE_MS = 5 * 60 * 1000

const sleep = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds))

function formatTime(timestamp: number) {
  const value = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function recordIcon(category: string, size = 20) {
  if (category === 'text') return <ClipboardCopy size={size} />
  if (category === 'image') return <Image size={size} />
  if (category === 'video') return <Video size={size} />
  return <File size={size} />
}

function App() {
  const [runtime, setRuntime] = useState<RuntimeInfo>({ running: false, port: null, key: '' })
  const [bridge, setBridge] = useState<BridgeState | null>(null)
  const [records, setRecords] = useState<HistoryRecord[]>([])
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('all')
  const [loading, setLoading] = useState(true)
  const loadingMoreRef = useRef(false)
  const [modal, setModal] = useState<'qr' | 'publish' | 'manage' | null>(null)
  const [notice, setNotice] = useState('')
  const [availableUpdate, setAvailableUpdate] = useState<UpdateResult | null>(null)
  const [autoUpdating, setAutoUpdating] = useState(false)
  const updateCheckInFlightRef = useRef(false)
  const lastUpdateCheckAtRef = useRef(0)
  const dismissedUpdateVersionRef = useRef<string | null>(null)

  const baseUrl = useMemo(
    () => (runtime.port ? `http://127.0.0.1:${runtime.port}` : ''),
    [runtime.port],
  )

  const apiGet = useCallback(
    async <T,>(path: string, params: Record<string, string | number> = {}) => {
      if (!baseUrl || !runtime.key) throw new Error('服务尚未就绪')
      const search = new URLSearchParams({ key: runtime.key })
      Object.entries(params).forEach(([name, value]) => search.set(name, String(value)))
      const response = await fetch(`${baseUrl}${path}?${search}`)
      const payload = await response.json()
      if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`)
      return payload as T & { ok: boolean }
    },
    [baseUrl, runtime.key],
  )

  const apiPost = useCallback(
    async <T,>(path: string, data: Record<string, unknown> = {}) => {
      if (!baseUrl || !runtime.key) throw new Error('服务尚未就绪')
      const response = await fetch(`${baseUrl}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, key: runtime.key }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`)
      return payload as T & { ok: boolean }
    },
    [baseUrl, runtime.key],
  )

  const notify = useCallback((message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 2600)
  }, [])

  const syncRuntime = useCallback(async () => {
    const info = await invoke<RuntimeInfo>('bridge_runtime')
    setRuntime(info)
    return info
  }, [])

  const loadBridgeState = useCallback(async () => {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const info = await syncRuntime()
      if (info.running && info.port && info.key) {
        try {
          const state = await fetch(
            `http://127.0.0.1:${info.port}/desktop/state?key=${encodeURIComponent(info.key)}`,
          ).then((response) => response.json())
          if (state.ok) {
            setBridge(state)
            return state as BridgeState
          }
        } catch {
          // The one-file sidecar can take a moment to unpack on first launch.
        }
      }
      await sleep(250)
    }
    throw new Error('桥接服务启动超时')
  }, [syncRuntime])

  const loadHistory = useCallback(
    async (append = false) => {
      if (append && loadingMoreRef.current) return
      if (append) loadingMoreRef.current = true
      setLoading(true)
      try {
        const offset = append ? records.length : 0
        const result = await apiGet<HistoryResponse>('/desktop/history', {
          q: query,
          category,
          offset,
          limit: 30,
        })
        setRecords((current) => (append ? [...current, ...result.items] : result.items))
        setTotal(result.total)
        setHasMore(result.has_more)
      } catch (error) {
        notify(error instanceof Error ? error.message : '读取历史失败')
      } finally {
        if (append) loadingMoreRef.current = false
        setLoading(false)
      }
    },
    [apiGet, category, notify, query, records.length],
  )

  const handleHistoryScroll = (event: UIEvent<HTMLElement>) => {
    const { scrollHeight, scrollTop, clientHeight } = event.currentTarget
    if (hasMore && !loading && scrollHeight - scrollTop - clientHeight <= 96) {
      void loadHistory(true)
    }
  }

  useEffect(() => {
    loadBridgeState()
      .then(() => setLoading(false))
      .catch((error) => {
        setLoading(false)
        notify(error instanceof Error ? error.message : '服务启动失败')
      })
  }, [loadBridgeState, notify])

  useEffect(() => {
    if (!bridge) return
    const timer = window.setTimeout(() => void loadHistory(false), 180)
    return () => window.clearTimeout(timer)
  }, [bridge, category, query]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!bridge) return
    const timer = window.setInterval(() => void loadHistory(false), 10_000)
    return () => window.clearInterval(timer)
  }, [bridge, loadHistory])

  useEffect(() => {
    if (!bridge) return
    let cancelled = false
    const checkForUpdate = () => {
      const now = Date.now()
      if (updateCheckInFlightRef.current || now - lastUpdateCheckAtRef.current < AUTO_UPDATE_FOCUS_THROTTLE_MS) return
      updateCheckInFlightRef.current = true
      lastUpdateCheckAtRef.current = now
      void apiGet<{ result: UpdateResult }>('/desktop/update')
        .then((response) => {
          if (
            !cancelled
            && response.result.available
            && dismissedUpdateVersionRef.current !== response.result.version
          ) setAvailableUpdate(response.result)
        })
        .catch(() => {
          // Automatic update checks stay silent when the LAN source is offline.
        })
        .finally(() => { updateCheckInFlightRef.current = false })
    }
    const checkAfterFocus = () => checkForUpdate()
    const initialTimer = window.setTimeout(checkForUpdate, AUTO_UPDATE_INITIAL_DELAY_MS)
    const intervalTimer = window.setInterval(checkForUpdate, AUTO_UPDATE_INTERVAL_MS)
    window.addEventListener('focus', checkAfterFocus)
    return () => {
      cancelled = true
      window.clearTimeout(initialTimer)
      window.clearInterval(intervalTimer)
      window.removeEventListener('focus', checkAfterFocus)
    }
  }, [apiGet, bridge])

  const toggleService = async () => {
    try {
      if (runtime.running) {
        await invoke('stop_bridge')
        setRuntime({ running: false, port: null, key: runtime.key })
        setBridge(null)
        notify('服务已停止')
      } else {
        await invoke('start_bridge')
        await loadBridgeState()
        notify('服务已启动')
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : '服务操作失败')
    }
  }

  const openQrDialog = async () => {
    try {
      await loadBridgeState()
      setModal('qr')
    } catch (error) {
      notify(error instanceof Error ? error.message : '无法刷新手机连接地址')
    }
  }

  const activateRecord = async (record: HistoryRecord) => {
    try {
      if (record.type === 'text') {
        await apiPost('/desktop/copy', { text: record.text || '' })
        notify('文字已复制到剪贴板')
      } else {
        await apiPost('/desktop/open', { id: record.id, mode: 'file' })
        notify('已使用默认应用打开')
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : '操作失败')
    }
  }

  const openRecordFolder = async (record: HistoryRecord) => {
    try {
      await apiPost('/desktop/open', { id: record.id, mode: 'folder' })
      notify('已打开文件所在目录')
    } catch (error) {
      notify(error instanceof Error ? error.message : '打开目录失败')
    }
  }

  const installAvailableUpdate = async () => {
    setAutoUpdating(true)
    try {
      const prepared = await apiPost<{ package_path: string; version: string }>('/desktop/update/prepare')
      notify(`版本 ${prepared.version} 已下载，正在重启安装`)
      await invoke('install_update', { installerPath: prepared.package_path, expectedVersion: prepared.version })
    } catch (error) {
      notify(error instanceof Error ? error.message : '自动更新失败')
      setAutoUpdating(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img src="/app-icon.png" alt="" />
          <div><strong>声笺</strong><span>桌面版 v{bridge?.version || '—'}</span></div>
        </div>
        <nav aria-label="主导航">
          <button className="nav-item active" onClick={() => void loadHistory(false)}><Archive size={19} /><span>史记</span><RefreshCw className="nav-trailing" size={15} /></button>
          <button className="nav-item" onClick={() => void openQrDialog()}><QrCode size={19} /><span>连接手机</span></button>
          <button className="nav-item" onClick={() => setModal('publish')}><Send size={19} /><span>发布给手机</span></button>
          <button className="nav-item" onClick={() => setModal('manage')}><Settings size={19} /><span>管理</span></button>
        </nav>
        {availableUpdate && (
          <button className="update-indicator" disabled={autoUpdating} onClick={() => void installAvailableUpdate()}>
            {autoUpdating ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}
            <span>
              <strong>有新版本 {availableUpdate.version}</strong>
              <small>{autoUpdating ? '正在下载安装…' : '点击立即更新'}</small>
            </span>
          </button>
        )}
        <div className={`service-summary ${runtime.running ? 'online' : ''}`}>
          <span className="status-dot" />
          <div><strong>{runtime.running ? '服务运行中' : '服务已停止'}</strong><span>{runtime.running ? '手机可以连接' : '点击启动恢复连接'}</span></div>
          <button className="icon-button" title={runtime.running ? '停止服务' : '启动服务'} onClick={toggleService}>
            {runtime.running ? <Square size={16} /> : <Play size={16} />}
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="history-banner">
          <div className="history-banner-title"><span className="history-banner-icon"><Archive size={20} /></span><h1 className="history-title">史记</h1><span className="history-seal" aria-hidden="true">录</span></div>
          <div className="history-banner-art" aria-hidden="true">
            <div className="history-banner-wave"><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
          </div>
        </header>

        <section className="filter-bar" aria-label="历史筛选">
          <div className="search-field"><Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索文字、文件名、路径或类型" />{query && <button onClick={() => setQuery('')} title="清除搜索"><X size={16} /></button>}</div>
          <div className="category-tabs" role="group" aria-label="内容类型">
            {CATEGORIES.map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={category === value ? 'active' : ''}
                aria-pressed={category === value}
                onClick={() => setCategory(value)}
              >
                {value === 'all' ? <FileSearch size={15} /> : recordIcon(value, 15)}
                <span>{label}</span>
              </button>
            ))}
          </div>
          <span className="result-count">共 {total} 条</span>
        </section>

        <section className="history-list" aria-live="polite" onScroll={handleHistoryScroll}>
          {records.map((record) => (
            <article className={`history-row type-${record.category}`} key={record.id} onDoubleClick={() => void activateRecord(record)} tabIndex={0} onKeyDown={(event) => event.key === 'Enter' && void activateRecord(record)}>
              <div className="record-visual">
                {record.has_thumbnail && bridge ? (
                  <img src={`${baseUrl}/desktop/history/thumbnail?key=${encodeURIComponent(runtime.key)}&id=${encodeURIComponent(record.id)}`} alt="图片缩略图" />
                ) : recordIcon(record.category)}
              </div>
              <div className="record-content"><div className="record-title"><span className="type-label">{record.summary.kind}</span><strong>{record.summary.preview}</strong></div><div className="record-meta"><span>{formatTime(record.ts)}</span><span>{record.summary.info}</span><span>{record.type === 'text' ? '双击复制' : '双击打开'}</span></div></div>
              <button className="icon-button row-action" title={record.type === 'text' ? '复制' : '打开所在目录'} onClick={() => void (record.type === 'text' ? activateRecord(record) : openRecordFolder(record))}>{record.type === 'text' ? <ClipboardCopy size={17} /> : <FolderOpen size={17} />}</button>
            </article>
          ))}
          {!records.length && !loading && <div className="empty-state"><Archive size={34} /><strong>没有匹配的历史内容</strong><span>调整搜索条件，或从手机发送新的内容。</span></div>}
          {loading && <div className="loading-state"><LoaderCircle className="spin" size={22} />正在读取历史...</div>}
        </section>
      </main>

      {modal === 'qr' && bridge && <QrDialog bridge={bridge} onClose={() => setModal(null)} onRefresh={async () => { const result = await apiPost<{ key: string; mobile_url: string }>('/desktop/key/regenerate'); setRuntime((current) => ({ ...current, key: result.key })); await loadBridgeState(); notify('二维码和访问密钥已刷新') }} onOpen={() => void openUrl(bridge.local_url)} />}
      {modal === 'publish' && <PublishDialog onClose={() => setModal(null)} onPublish={async (text, paths) => { await apiPost('/desktop/publish', { text, paths }); notify('内容已发布到手机缓冲区'); setModal(null); await loadHistory(false) }} />}
      {modal === 'manage' && <ManageDialog apiGet={apiGet} apiPost={apiPost} currentVersion={bridge?.version || '0.12.2'} onClose={() => setModal(null)} notify={notify} />}
      {availableUpdate && <UpdateDialog update={availableUpdate} installing={autoUpdating} onClose={() => { dismissedUpdateVersionRef.current = availableUpdate.version; setAvailableUpdate(null) }} onInstall={installAvailableUpdate} />}
      {notice && <div className="toast"><Check size={17} />{notice}</div>}
    </div>
  )
}

function DialogFrame({ title, subtitle, onClose, children, wide = false }: { title: string; subtitle: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className={`dialog ${wide ? 'dialog-wide' : ''}`} role="dialog" aria-modal="true"><header><div><h2>{title}</h2><p>{subtitle}</p></div><button className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></header>{children}</section></div>
}

function QrDialog({ bridge, onClose, onRefresh, onOpen }: { bridge: BridgeState; onClose: () => void; onRefresh: () => Promise<void>; onOpen: () => void }) {
  const [refreshing, setRefreshing] = useState(false)
  return <DialogFrame title="扫码连接手机" subtitle="手机和电脑连接同一 Wi-Fi 后扫码。" onClose={onClose}><div className="qr-layout"><div className="qr-code"><QRCodeSVG value={bridge.mobile_url} size={256} level="M" /></div><div className="qr-status"><span className="status-dot" /><strong>连接码可用</strong><p>访问密钥不会显示在界面中。二维码刷新后，旧二维码立即失效。</p></div></div><footer className="dialog-actions"><button className="button secondary" onClick={onOpen}><MonitorSmartphone size={17} />打开本机页面</button><button className="button primary" disabled={refreshing} onClick={async () => { setRefreshing(true); await onRefresh(); setRefreshing(false) }}><RefreshCw className={refreshing ? 'spin' : ''} size={17} />刷新二维码</button></footer></DialogFrame>
}

function UpdateDialog({ update, installing, onClose, onInstall }: { update: UpdateResult; installing: boolean; onClose: () => void; onInstall: () => Promise<void> }) {
  return <DialogFrame title="发现新版本" subtitle={`版本 ${update.version} 已准备好。`} onClose={installing ? () => {} : onClose}>
    <div className="update-prompt">
      <RefreshCw size={26} />
      <div><strong>声笺 {update.version}</strong><p>{update.notes || '包含功能改进和问题修复。'}</p></div>
    </div>
    <footer className="dialog-actions">
      <button className="button secondary" disabled={installing} onClick={onClose}>稍后</button>
      <button className="button primary" disabled={installing} onClick={() => void onInstall()}>{installing ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}{installing ? '正在下载...' : '下载并更新'}</button>
    </footer>
  </DialogFrame>
}

function PublishDialog({ onClose, onPublish }: { onClose: () => void; onPublish: (text: string, paths: string[]) => Promise<void> }) {
  const [text, setText] = useState('')
  const [paths, setPaths] = useState<string[]>([])
  const [publishing, setPublishing] = useState(false)
  useEffect(() => {
    let unlisten: (() => void) | undefined
    getCurrentWebviewWindow().onDragDropEvent((event) => {
      if (event.payload.type === 'drop') {
        const droppedPaths = event.payload.paths
        setPaths((current) => Array.from(new Set([...current, ...droppedPaths])))
      }
    }).then((dispose) => { unlisten = dispose })
    return () => unlisten?.()
  }, [])
  const chooseFiles = async () => {
    const selected = await open({ multiple: true, directory: false })
    if (selected) setPaths((current) => Array.from(new Set([...current, ...(Array.isArray(selected) ? selected : [selected])])))
  }
  return <DialogFrame title="发布给手机" subtitle="文字与文件可以在一次操作中同时发布。" onClose={onClose} wide><div className="publish-grid"><label className="publish-text"><span>文字内容</span><textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="输入需要在手机上复制的文字..." /></label><div className="drop-zone" onClick={() => void chooseFiles()}><Upload size={28} /><strong>拖入文件，或点击选择</strong><span>支持图片、视频、Word、PDF 和其他小文件</span></div></div>{paths.length > 0 && <div className="selected-files"><div><strong>已选择 {paths.length} 个文件</strong><button onClick={() => setPaths([])}>全部清除</button></div>{paths.map((path) => <p key={path}><File size={15} /><span>{path.split(/[\\/]/).pop()}</span><button title="移除" onClick={() => setPaths((current) => current.filter((item) => item !== path))}><X size={14} /></button></p>)}</div>}<footer className="dialog-actions"><button className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={publishing || (!text.trim() && !paths.length)} onClick={async () => { setPublishing(true); await onPublish(text, paths).finally(() => setPublishing(false)) }}>{publishing ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}发布到手机</button></footer></DialogFrame>
}

function TunnelPanel({ apiGet, apiPost, notify }: { apiGet: <T>(path: string, params?: Record<string, string | number>) => Promise<T & { ok: boolean }>; apiPost: <T>(path: string, data?: Record<string, unknown>) => Promise<T & { ok: boolean }>; notify: (message: string) => void }) {
  const [config, setConfig] = useState<TunnelConfig | null>(null)
  const [status, setStatus] = useState<TunnelStatus | null>(null)
  const [candidates, setCandidates] = useState<TunnelCandidate[]>([])
  const [form, setForm] = useState({ name: '', public_url: '', cloudflared_path: '', metrics_port: '20244' })
  const [busy, setBusy] = useState('')

  const applyState = useCallback((next: { config: TunnelConfig; status: TunnelStatus; candidates?: TunnelCandidate[] }) => {
    setConfig(next.config)
    setStatus(next.status)
    if (next.candidates) setCandidates(next.candidates)
    setForm({
      name: next.config.name,
      public_url: next.config.public_url,
      cloudflared_path: next.config.cloudflared_path,
      metrics_port: String(next.config.metrics_port),
    })
  }, [])

  const load = useCallback(async () => {
    try {
      applyState(await apiGet<TunnelResponse>('/desktop/tunnel'))
    } catch (error) {
      notify(error instanceof Error ? error.message : '读取隧道状态失败')
    }
  }, [apiGet, applyState, notify])

  useEffect(() => { void load() }, [load])

  const payload = () => ({ ...form, metrics_port: Number(form.metrics_port) || 20244 })

  const save = async () => {
    setBusy('save')
    try {
      const response = await apiPost<{ config: TunnelConfig; status: TunnelStatus }>('/desktop/tunnel/config', payload())
      applyState(response)
      notify('隧道配置已保存')
    } catch (error) {
      notify(error instanceof Error ? error.message : '保存隧道配置失败')
    } finally {
      setBusy('')
    }
  }

  const run = async (action: 'start' | 'stop') => {
    setBusy(action)
    try {
      const response = await apiPost<{ config: TunnelConfig; status: TunnelStatus }>(`/desktop/tunnel/${action}`, { ...payload(), enabled: action === 'start' })
      applyState(response)
      if (action === 'start') {
        notify(response.status.ready ? '隧道已连通，二维码改用公网地址' : '隧道已启动但尚未连通，二维码暂时使用局域网地址')
      } else if (response.status.stop_result && !response.status.stop_result.stopped) {
        notify('该隧道由外部程序托管，未做停止')
      } else {
        notify('已停止声笺托管的隧道')
      }
      await load()
    } catch (error) {
      notify(error instanceof Error ? error.message : '隧道操作失败')
    } finally {
      setBusy('')
    }
  }

  const stateText = !config
    ? '读取中…'
    : status?.ready
      ? '已连通'
      : status?.running
        ? '进程在跑但未连通'
        : '未运行'
  const ownerText = status?.managed ? '由声笺托管' : status?.running ? '由外部程序托管' : ''

  return (
    <section>
      <h3>公网隧道</h3>
      <div className="settings-row">
        <div>
          <strong>Cloudflare 隧道</strong>
          <span>{stateText}{ownerText ? ` · ${ownerText}` : ''}</span>
        </div>
        <button className="button secondary" disabled={Boolean(busy)} onClick={() => void load()}><RefreshCw size={16} />刷新状态</button>
      </div>
      {candidates.length > 0 && (
        <div className="tunnel-candidates">
          <span>检测到本机隧道配置，点一下即可填入：</span>
          {candidates.map((item) => (
            <button
              key={item.name}
              type="button"
              disabled={!item.public_url}
              onClick={() => setForm({ ...form, name: item.name, public_url: item.public_url })}
            >
              {item.name}{item.public_url ? ` · ${item.public_url.replace(/^https?:\/\//, '')}` : ' · 未识别域名'}
            </button>
          ))}
        </div>
      )}
      <label className="form-field"><span>隧道名称</span><input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如 shenjian" /></label>
      <label className="form-field"><span>公网地址</span><input value={form.public_url} onChange={(event) => setForm({ ...form, public_url: event.target.value })} placeholder="https://sj.q-ze.top" /></label>
      <label className="form-field"><span>cloudflared 路径</span><input value={form.cloudflared_path} onChange={(event) => setForm({ ...form, cloudflared_path: event.target.value })} placeholder={status?.cloudflared_path || '留空则自动探测'} /></label>
      <label className="form-field"><span>metrics 端口</span><input value={form.metrics_port} onChange={(event) => setForm({ ...form, metrics_port: event.target.value })} placeholder="20244" /></label>
      <div className="tunnel-actions">
        <button className="button secondary" disabled={Boolean(busy)} onClick={() => void save()}>保存配置</button>
        <button className="button primary" disabled={Boolean(busy)} onClick={() => void run('start')}>启动隧道</button>
        <button className="button secondary" disabled={Boolean(busy)} onClick={() => void run('stop')}>停止隧道</button>
      </div>
      <p className="tunnel-hint">隧道连通时二维码走公网地址，断开时自动回落局域网。不再需要手写 public_url.txt 或额外的计划任务。</p>
    </section>
  )
}

function ManageDialog({ apiGet, apiPost, currentVersion, onClose, notify }: { apiGet: <T>(path: string, params?: Record<string, string | number>) => Promise<T & { ok: boolean }>; apiPost: <T>(path: string, data?: Record<string, unknown>) => Promise<T & { ok: boolean }>; currentVersion: string; onClose: () => void; notify: (message: string) => void }) {
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [checking, setChecking] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [updateResult, setUpdateResult] = useState<UpdateResult | null>(null)
  const [toolResult, setToolResult] = useState('')
  useEffect(() => { void apiGet<ConfigResponse>('/desktop/config').then(setConfig) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const checkUpdate = async () => {
    setChecking(true)
    try {
      const response = await apiGet<{ result: UpdateResult }>('/desktop/update', { refresh: 1 })
      const result = response.result
      setUpdateResult(result)
      if (result.error) notify(`检查更新失败：${result.error}`)
      else notify(result.available ? `发现新版本 ${result.version}` : `当前已是最新版 ${currentVersion}`)
    } catch (error) { notify(error instanceof Error ? error.message : '检查更新失败') } finally { setChecking(false) }
  }
  const installUpdate = async () => {
    setInstalling(true)
    try {
      const prepared = await apiPost<{ package_path: string; version: string }>('/desktop/update/prepare')
      notify(`版本 ${prepared.version} 已下载，正在重启安装`)
      await invoke('install_update', { installerPath: prepared.package_path, expectedVersion: prepared.version })
    } catch (error) {
      notify(error instanceof Error ? error.message : '自动更新失败')
      setInstalling(false)
    }
  }
  const copyDiagnostics = async () => {
    try {
      const { result } = await apiPost<{ result: { copied: boolean; characters: number } }>('/desktop/diagnostics/copy')
      const message = `诊断信息已复制，共 ${result.characters} 个字符`
      setToolResult(message)
      notify(message)
    } catch (error) {
      const message = error instanceof Error ? error.message : '复制诊断失败'
      setToolResult(message)
      notify(message)
    }
  }
  const allowFirewall = async () => {
    try {
      const { result } = await apiPost<{ result: { allowed: boolean; launched: boolean; rule: string } }>('/desktop/firewall')
      const message = result.allowed
        ? `防火墙规则已生效：${result.rule}`
        : result.launched
          ? '已弹出管理员确认，请允许后再次点击检查'
          : '防火墙规则尚未生效'
      setToolResult(message)
      notify(message)
    } catch (error) {
      const message = error instanceof Error ? error.message : '防火墙放行失败'
      setToolResult(message)
      notify(message)
    }
  }
  return <DialogFrame title="管理" subtitle="低频配置集中在这里，日常使用无需进入。" onClose={onClose} wide>
    <div className="manage-sections">
      <TunnelPanel apiGet={apiGet} apiPost={apiPost} notify={notify} />
      <section>
        <h3>更新与模型</h3>
        <div className="settings-row">
          <div><strong>软件更新</strong><span>更新源由发布端统一管理</span></div>
          <button className="button secondary" onClick={() => void checkUpdate()} disabled={checking || installing}>{checking ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}检查更新</button>
        </div>
        {updateResult && <div className={`update-result ${updateResult.available ? 'available' : 'current'}`}>
          <div>
            <strong>{updateResult.available ? `发现新版本 ${updateResult.version}` : `当前已是最新版 ${currentVersion}`}</strong>
            <span>{updateResult.notes || (updateResult.available ? '下载完成后将自动安装并重新打开软件。' : '无需执行其他操作。')}</span>
          </div>
          {updateResult.available && <button className="button primary" disabled={installing} onClick={() => void installUpdate()}>{installing ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}{installing ? '正在下载...' : '立即更新'}</button>}
        </div>}
        <label className="form-field"><span>MiniMax API Key</span><input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config?.minimax_configured ? '已配置，留空表示不修改' : '尚未配置'} /></label>
        <button className="button primary compact" disabled={!apiKey.trim()} onClick={async () => { await apiPost('/desktop/config', { minimax_api_key: apiKey.trim() }); notify('配置已保存'); setApiKey(''); setUpdateResult(null) }}><Check size={16} />保存配置</button>
      </section>
      <section>
        <h3>数据与诊断</h3>
        <div className="tool-grid">
          <button onClick={() => void apiPost('/desktop/open-folder', { target: 'history' })}><Archive size={19} /><span><strong>历史归档</strong><small>打开分类存储目录</small></span></button>
          <button onClick={() => void apiPost('/desktop/open-folder', { target: 'shared' })}><FolderOpen size={19} /><span><strong>共享目录</strong><small>查看手机可下载文件</small></span></button>
          <button onClick={() => void copyDiagnostics()}><FileSearch size={19} /><span><strong>复制诊断</strong><small>复制后会显示实际字符数</small></span></button>
          <button onClick={() => void allowFirewall()}><ShieldCheck size={19} /><span><strong>放行防火墙</strong><small>验证自动端口范围是否生效</small></span></button>
        </div>
        {toolResult && <div className="tool-result" role="status"><Check size={15} /><span>{toolResult}</span></div>}
      </section>
    </div>
  </DialogFrame>
}

export default App
