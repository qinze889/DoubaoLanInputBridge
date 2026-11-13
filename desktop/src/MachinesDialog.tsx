import { useCallback, useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { QRCodeSVG } from 'qrcode.react'
import { Check, ClipboardCopy, FolderOpen, Link, LoaderCircle, Monitor, Plus, QrCode, Send, Trash2, Wifi, X } from 'lucide-react'

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
  if (value < 1024) return value + ' B'
  if (value < 1024 ** 2) return (value / 1024).toFixed(1) + ' KB'
  return (value / (1024 ** 2)).toFixed(1) + ' MB'
}

export default function MachinesDialog({ apiGet, apiPost, notify, onClose, embedded = false }: {
  apiGet: ApiGet; apiPost: ApiPost; notify: (message: string) => void; onClose: () => void; embedded?: boolean
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [invitation, setInvitation] = useState('')
  const [expiresAt, setExpiresAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [join, setJoin] = useState('')
  const [dialog, setDialog] = useState<'invite' | 'join' | null>(null)
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
    if (!dialog) return
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) setDialog(null) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [dialog, busy])

  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action(); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作未完成，请重试') }
    finally { setBusy(false) }
  }

  function invite() {
    void run(async () => {
      const result = await apiPost<{ invitation: string; expires_in: number }>('/desktop/peers/invite')
      setInvitation(result.invitation)
      setExpiresAt(Date.now() + result.expires_in * 1000)
      setDialog('invite')
    })
  }

  function addMachine() {
    setError('')
    setDialog('join')
  }

  function pair() {
    void run(async () => {
      await apiPost('/desktop/peers/join', { invitation: join.trim() })
      setJoin('')
      setDialog(null)
      notify('机器已配对，可以互传文件')
    })
  }

  async function sendFiles(peer: Peer) {
    const selected = await open({ multiple: true, directory: false })
    if (!selected) return
    await run(async () => {
      await apiPost('/desktop/peers/send', { id: peer.id, paths: Array.isArray(selected) ? selected : [selected] })
      notify('正在发送到 ' + peer.name)
    })
  }

  const validInvitation = Boolean(invitation) && now < expiresAt
  const modeReady = snapshot?.network.tunnel.ready ?? false
  const endpoint = snapshot?.network.endpoint || ''
  const networkStatus = modeReady ? '连接已就绪' : '请先在连接设备页开启连接'

  return <div className={embedded ? 'machines-page' : 'modal-backdrop'}>
    <section className={embedded ? 'machines-content' : 'dialog dialog-wide machines-dialog'} role={embedded ? undefined : 'dialog'} aria-modal={embedded ? undefined : true} aria-label="机器共享">
      {!embedded && <header><div><h2>机器共享</h2><p>Mac 与 Windows 配对后，直接互传文件。</p></div><button className="icon-button" aria-label="关闭" onClick={onClose}><X size={19} /></button></header>}

      <div className="machines-actions">
        <button className="button secondary" onClick={invite} disabled={busy || !snapshot || !endpoint || endpoint.includes('127.0.0.1') || snapshot.network.tunnel.phase === 'starting'}><QrCode size={16} />邀请机器</button>
        <button className="button primary" onClick={addMachine} disabled={busy}><Plus size={16} />添加机器</button>
      </div>

      <div className="machine-connection-note">
        <Wifi size={16} />
        <div><strong>{snapshot?.device.name || '本机'}</strong><span>{networkStatus} · 文件使用接收方当前连接方式</span></div>
        <button className="text-button" onClick={onClose}>连接设置</button>
      </div>

      {(snapshot?.network.tunnel.error || error) && <p className="machine-error" role="alert">{error || snapshot?.network.tunnel.error}</p>}

      <section className="machine-peers" aria-label="已配对机器">
        {!snapshot?.peers.length && <div className="machine-empty-card"><Monitor size={44} strokeWidth={1.25} /><strong>让 Mac 或 Windows 加入</strong><p>选择可达的连接方式，复制配对邀请到另一台机器即可。</p><button className="button primary" disabled={busy || !snapshot || !endpoint || endpoint.includes('127.0.0.1')} onClick={invite}><QrCode size={16} />生成一次性邀请</button></div>}
        {snapshot?.peers.map(peer => <article className="machine-peer" key={peer.id}>
          <span className="symbol-tile"><Monitor size={22} /></span>
          <div className="machine-peer-info"><strong>{peer.name}</strong><small>{peer.endpoint ? (() => { try { return new URL(peer.endpoint).host } catch { return '已配对设备' } })() : '已配对设备'}</small><span className="machine-trust"><Check size={12} />已配对 · 独立机器凭据</span></div>
          <button className="button primary" disabled={busy} onClick={() => void sendFiles(peer).catch(reason => setError(reason instanceof Error ? reason.message : '无法选择文件'))}><Send size={16} />发送文件</button>
          <button className="icon-button" title={'移除与 ' + peer.name + ' 的配对'} aria-label={'移除与 ' + peer.name + ' 的配对'} disabled={busy} onClick={() => void run(async () => { await apiPost('/desktop/peers/remove', { id: peer.id }) })}><Trash2 size={17} /></button>
        </article>)}
      </section>

      <section className="machine-jobs" aria-label="传输任务">
        <div className="machine-section-heading"><h3>传输任务</h3><button className="text-button" onClick={() => void run(async () => { await apiPost('/desktop/open-folder', { target: 'received' }) })}><FolderOpen size={15} />打开接收目录</button></div>
        {!snapshot?.jobs.length && <p className="machine-empty-label">收到和发出的文件会显示在这里。</p>}
        {snapshot?.jobs.map(job => <article className="machine-job" key={job.id}>
          <span className={'symbol-tile ' + (job.status === 'complete' ? 'complete' : job.status === 'error' ? 'failed' : '')}>{job.status === 'complete' ? <Check size={21} /> : <Send size={21} />}</span>
          <div className="machine-job-info"><strong>{job.name}</strong><small>{job.direction === 'send' ? '发送至 ' : '来自 '}{job.peer_name}</small></div>
          <span className={job.status === 'complete' ? 'machine-complete' : ''}>{job.status === 'complete' ? '校验完成' : job.status === 'error' ? '传输失败' : bytes(job.sent) + ' / ' + bytes(job.total)}</span>
          {job.status !== 'complete' && <progress max={Math.max(job.total, 1)} value={job.sent} aria-label={job.name + ' 传输进度'} />}
          {job.error && <p className="machine-error">{job.error}</p>}
        </article>)}
      </section>
      <p className="machine-helper">配对邀请 5 分钟内有效，仅可使用一次。临时域名变化后可能需要重新配对。</p>
    </section>

    {dialog && <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setDialog(null) }}>
      <section className="dialog machine-modal" role="dialog" aria-modal="true" aria-label={dialog === 'invite' ? '邀请另一台机器' : '添加另一台机器'}>
        <header><div><h2>{dialog === 'invite' ? '邀请另一台机器' : '添加另一台机器'}</h2><p>{dialog === 'invite' ? '在另一台机器中选择“添加机器”，粘贴这个邀请。' : '在另一台机器生成邀请，再粘贴到这里。'}</p></div><button className="icon-button" disabled={busy} title="关闭" onClick={() => setDialog(null)}><X size={19} /></button></header>
        {dialog === 'invite' ? <div className="machine-invitation">
          {validInvitation ? <><QRCodeSVG value={invitation} size={210} /><p>一次性邀请 · {Math.ceil((expiresAt - now) / 1000)} 秒后过期</p><button className="button primary" onClick={() => void navigator.clipboard.writeText(invitation).then(() => notify('配对邀请已复制')).catch(() => setError('复制失败，请重试'))}><ClipboardCopy size={16} />复制配对邀请</button></> : <><p>邀请已过期，请重新生成。</p><button className="button primary" onClick={invite} disabled={busy}><QrCode size={16} />重新生成邀请</button></>}
        </div> : <div className="machine-join">
          <label className="form-field"><span>配对邀请</span><textarea autoFocus value={join} onChange={event => setJoin(event.target.value)} placeholder="shengjian://pair?…" spellCheck={false} autoComplete="off" /></label>
          <footer className="dialog-actions"><button className="button secondary" disabled={busy} onClick={() => setDialog(null)}>取消</button><button className="button primary" disabled={busy || !join.trim()} onClick={pair}>{busy ? <LoaderCircle size={16} className="spin" /> : <Link size={16} />}配对</button></footer>
        </div>}
        {error && <p className="machine-error" role="alert">{error}</p>}
      </section>
    </div>}
  </div>
}
