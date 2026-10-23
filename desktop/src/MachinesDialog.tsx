import ConnectionPanel from './ConnectionPanel'
import { useCallback, useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { QRCodeSVG } from 'qrcode.react'
import { Check, ClipboardCopy, FolderOpen, Link, LoaderCircle, Monitor, Send, Trash2, X } from 'lucide-react'

type ApiGet = <T>(path: string, params?: Record<string, string | number>) => Promise<T & { ok: boolean }>
type ApiPost = <T>(path: string, data?: Record<string, unknown>) => Promise<T & { ok: boolean }>
type Peer = { id: string; name: string; endpoint: string }
type Job = { id: string; peer_name: string; name: string; status: string; direction: string; sent: number; total: number; error: string }
type Snapshot = {
  device: { name: string }
  peers: Peer[]
  jobs: Job[]
  network: { endpoint: string; tunnel: { phase: string; ready: boolean; error: string; cloudflared_available: boolean } }
}

function bytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

export default function MachinesDialog({ apiGet, apiPost, notify, onClose, embedded = false }: {
  apiGet: ApiGet; apiPost: ApiPost; notify: (message: string) => void; onClose: () => void; embedded?: boolean
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [invitation, setInvitation] = useState('')
  const [expiresAt, setExpiresAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [join, setJoin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refreshing = useRef(false)
  const refresh = useCallback(async () => {
    if (refreshing.current) return
    refreshing.current = true
    try { setSnapshot(await apiGet<Snapshot>('/desktop/peers')) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取机器状态') }
    finally { refreshing.current = false }
  }, [apiGet])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { setNow(Date.now()); void refresh() }, 2000)
    return () => window.clearInterval(timer)
  }, [refresh])
  useEffect(() => {
    if (embedded) return
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [embedded, onClose])
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action(); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作未完成，请重试') }
    finally { setBusy(false) }
  }
  async function sendFiles(peer: Peer) {
    await run(async () => {
      const selected = await open({ multiple: true, directory: false })
      if (!selected) return
      await apiPost('/desktop/peers/send', { id: peer.id, paths: Array.isArray(selected) ? selected : [selected] })
      notify(`正在发送到 ${peer.name}`)
    })
  }
  const tunnel = snapshot?.network.tunnel
  const validInvitation = invitation && now < expiresAt
  const endpoint = snapshot?.network.endpoint || ''
  return <div className={embedded ? 'machines-page' : 'modal-backdrop'} onMouseDown={(event) => !embedded && event.target === event.currentTarget && onClose()}>
    <section className={embedded ? 'machines-content' : 'dialog dialog-wide machines-dialog'} role={embedded ? undefined : 'dialog'} aria-modal={embedded ? undefined : true} aria-label="机器共享">
      {!embedded && <header><div><h2>机器共享</h2><p>Mac 与 Windows 配对后，直接互传文件。</p></div><button className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></header>}
      <ConnectionPanel apiGet={apiGet} apiPost={apiPost} />
      <div className="machine-network"><strong>{snapshot?.device.name || '本机'}</strong><span>文件使用接收方当前的连接方式</span></div>
      {tunnel?.error && <p className="machine-error" role="status">{tunnel.error}</p>}
      {error && <p className="machine-error" role="alert">{error}</p>}
      <div className="machine-pair-grid">
        <section className="machine-panel"><h3>邀请一台电脑</h3><p>邀请仅使用一次，5 分钟内有效。跨网络请用固定公网、CF 或 P2P；P2P 需两端都选择直连。</p>
          <button className="button secondary" disabled={busy || !snapshot || endpoint.includes('127.0.0.1') || tunnel?.phase === 'starting'} onClick={() => void run(async () => { const result = await apiPost<{ invitation: string; expires_in: number }>('/desktop/peers/invite'); setInvitation(result.invitation); setExpiresAt(Date.now() + result.expires_in * 1000) })}><Link size={16} />生成邀请</button>
          {validInvitation && <div className="machine-invitation"><QRCodeSVG value={invitation} size={128} /><button className="button secondary" onClick={() => void run(async () => { await navigator.clipboard.writeText(invitation); notify('邀请已复制') })}><ClipboardCopy size={16} />复制邀请 · {Math.ceil((expiresAt - now) / 1000)} 秒</button></div>}
          {invitation && !validInvitation && <p>邀请已过期，请重新生成。</p>}
        </section>
        <section className="machine-panel"><h3>连接另一台电脑</h3><label className="form-field"><span>粘贴对方的配对邀请</span><textarea value={join} onChange={(event) => setJoin(event.target.value)} placeholder="shengjian://pair?…" spellCheck={false} autoComplete="off" /></label>
          <button className="button primary" disabled={busy || !join.trim()} onClick={() => void run(async () => { await apiPost('/desktop/peers/join', { invitation: join.trim() }); setJoin(''); notify('已配对，可以双向传文件') })}>{busy ? <LoaderCircle className="spin" size={16} /> : <Link size={16} />}配对</button>
        </section>
      </div>
      <section className="machine-peers"><h3>已配对的电脑</h3>
        {!snapshot?.peers.length && <p className="machine-empty">还没有配对电脑。Mac 和 Windows 都从“机器共享”添加对方。</p>}
        {snapshot?.peers.map((peer) => <article className="machine-peer" key={peer.id}><Monitor size={22} /><div><strong>{peer.name}</strong><small>已配对</small></div><button className="button primary" disabled={busy} onClick={() => void sendFiles(peer)}><Send size={16} />发送文件</button><button className="icon-button" title={`解除与 ${peer.name} 的配对`} disabled={busy} onClick={() => void run(async () => { await apiPost('/desktop/peers/remove', { id: peer.id }) })}><Trash2 size={17} /></button></article>)}
      </section>
      <section className="machine-jobs"><h3>传输任务</h3>
        {snapshot?.jobs.map((job) => <article className="machine-job" key={job.id}><div><strong>{job.name}</strong><small>{job.direction === 'send' ? '发送到' : '接收自'} {job.peer_name}</small></div>{job.status === 'complete' ? <span className="machine-complete"><Check size={16} />校验成功</span> : <span>{bytes(job.sent)} / {bytes(job.total)}</span>}{job.status !== 'complete' && <progress max={Math.max(job.total, 1)} value={job.sent} aria-label={`${job.name} 传输进度`} />}{job.status === 'error' && <p className="machine-error">{job.error}</p>}</article>)}
        {!snapshot?.jobs.length && <p className="machine-empty">传输完成后会校验完整文件。</p>}
      </section>
      <footer className="dialog-actions"><button className="button secondary" onClick={() => void run(async () => { await apiPost('/desktop/open-folder', { target: 'received' }) })}><FolderOpen size={17} />接收文件夹</button>{!embedded && <button className="button secondary" onClick={onClose}>完成</button>}</footer>
    </section>
  </div>
}
