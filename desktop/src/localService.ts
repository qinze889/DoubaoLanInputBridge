export type ServiceIdentity = { service: string; protocol: number; port: number; pid: number; instance_id: string }
export type RuntimeInfo = { running: boolean; port: number | null; key: string; identity?: ServiceIdentity | null; error?: string }
const mismatch = () => new Error('本机连接身份不匹配，已停止发送数据。请重新连接声笺。')

export async function verifyLocalService(runtime: RuntimeInfo) {
  const identity = runtime.identity
  if (!runtime.running || !runtime.key || !identity || identity.service !== 'shengjian.bridge' || identity.protocol !== 1
    || !Number.isInteger(identity.pid) || identity.pid < 1 || identity.port !== runtime.port || identity.port < 1 || identity.port > 65535
    || !/^[a-f0-9]{32}$/.test(identity.instance_id)) throw mismatch()
  const origin = `http://127.0.0.1:${identity.port}`
  const challenge = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
  let response: Response
  try {
    response = await fetch(`${origin}/health`, { headers: { 'X-Shengjian-Challenge': challenge }, redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(3000) })
  } catch { throw new Error('本机服务暂时无法连接，请稍后重试。') }
  if (!response.ok || !response.headers.get('Content-Type')?.startsWith('application/json')) throw mismatch()
  const raw = await response.text()
  if (raw.length > 16384) throw mismatch()
  let value
  try { value = JSON.parse(raw) } catch { throw mismatch() }
  if (!value || typeof value !== 'object' || value.ok !== true || value.service !== identity.service || value.protocol !== 1 || value.pid !== identity.pid
    || value.port !== identity.port || value.instance_id !== identity.instance_id || typeof value.proof !== 'string' || !/^[a-f0-9]{64}$/.test(value.proof)) throw mismatch()
  const message = `shengjian-local-v1\n${challenge}\n${identity.instance_id}\n${identity.pid}\n${identity.port}`
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(runtime.key), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify'])
  const proof = Uint8Array.from(value.proof.match(/../g) as string[], x => parseInt(x, 16))
  if (!await crypto.subtle.verify('HMAC', key, proof, new TextEncoder().encode(message))) throw mismatch()
  return { identity, origin }
}

export async function requestLocal<T>(runtime: RuntimeInfo, path: string, body?: Record<string, unknown>, params: Record<string, string | number> = {}) {
  if (!path.startsWith('/desktop/')) throw mismatch()
  const { identity, origin } = await verifyLocalService(runtime)
  const headers: Record<string, string> = { 'X-Shengjian-Instance': identity.instance_id }
  let url = `${origin}${path}`
  const options: RequestInit = { headers, redirect: 'error', cache: 'no-store' }
  if (body) {
    headers['Content-Type'] = 'application/json'; options.method = 'POST'
    options.body = JSON.stringify({ ...body, key: runtime.key })
  } else {
    const search = new URLSearchParams({ key: runtime.key })
    Object.entries(params).forEach(([name, value]) => search.set(name, String(value)))
    url += `?${search}`
  }
  const response = await fetch(url, options)
  if (response.headers.get('X-Shengjian-Instance') !== identity.instance_id) throw mismatch()
  const payload = await response.json()
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`)
  return payload as T & { ok: boolean }
}
