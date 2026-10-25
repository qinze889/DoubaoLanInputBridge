"use strict";
const base = "/shengjian/api/v2",
  $ = (id) => document.getElementById(id);
let token = "",
  currentTask = "",
  cursor = 0,
  stream = null,
  refreshTimer = null,
  playback = null,
  capture = null,
  live = null,
  busy = false,
  messages = [],
  taskEpoch = 0,
  composeEpoch = 0,
  replyController = null,
  voiceController = null;
let authEpoch = 0, legacyCaptureEpoch = 0, appSnapshot = null, taskViewId = "";
let agentMode = false, computerDevices = [];
let chatOwner="", harnessInterrupted=false;
let modelOwner="", modelSaving=false;
let reportEpoch = 0, agentAckPending = false, reportSpeaking = false;
const labels = {
  queued: "排队中",
  running: "执行中",
  awaiting_user: "等待你处理",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  unknown: "结果未知",
};
function notice(value = "") {
  $("notice").textContent = value;
  window.ShengjianProduct?.presentNotice(value);
}
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, handler) {
  const b = el("button", text);
  b.type = "button";
  b.addEventListener("click", () => Promise.resolve(handler()).catch(error));
  return b;
}
const errors = {
  insufficient_credits: "可用积分不足，请联系管理员补充。",
  invalid_credentials:"用户名或密码不正确，请再检查一下。",
  invalid_invitation:"邀请码不可用，请检查后重试，或申请新的邀请码。",
  username_unavailable:"这个用户名已被使用，请换一个。",
  microphone_denied:"麦克风权限未允许，请在浏览器设置中允许麦克风后重试。",
  microphone_missing:"没有找到可用麦克风，请连接麦克风后重试。",
  microphone_unavailable:"麦克风暂时不可用，请结束其他录音或通话后重试。",
  unauthorized: "登录已失效，请重新登录。",
  audio_busy: "语音来源正在处理其他请求，请稍后重试。",
  audio_context_closed:"声音通道已关闭，请重新开启语音。文字回复已保留。",
  audio_context_paused:"声音被系统暂停，请点击语音按钮恢复。",
  audio_context_invalid:"声音通道暂不可用，请重新开启语音。",
  voice_network_error:"语音网络连接中断，文字回复已保留。",
  voice_stream_invalid:"语音数据未完整到达，文字回复已保留。",
  tts_login_required: "豆包登录态已失效，需要在服务器更新登录。",
  audio_rejected: "语音请求被拒绝，请稍后重试。",
  audio_result_unknown: "语音来源未确认结果，额度暂时预留，请勿反复重试。",
  select_computer_for_chat: "请先启用电脑 Agent；有多台电脑时请在发送目标中选择一台。",
  chat_computer_offline: "会话绑定的电脑离线，请打开声笺并启用 Agent。",
  chat_agent_update_required: "电脑 Agent 需要更新后才能接收统一 Chat 对话。",
  model_result_unknown: "模型未确认结果，请查看任务状态后再操作。",
  chat_model_unavailable:"对话上游暂时中断，这轮没有自动重试。麦克风仍可使用，可以继续说；图片和电脑工作请先核对进度。",
  image_job_busy: "已有图片正在后台生成，请稍后查看结果。",
  image_model_not_available: "暂无可用生图模型，请在模型与连接中重新选择。",
  chat_model_not_verified: "这个模型尚未通过工具调用验证，请选择列表中的模型。",
  chat_model_not_available: "所选对话模型暂不可用，请在模型与连接中重新选择。",
  model_provider_not_configured: "对话来源尚未配置。",
  model_discovery_failed: "暂时无法连接对话来源。",
  capability_not_granted: "请在“我的”中开启这台电脑的任务权限。",
  conversation_not_found:"这段对话暂时不可用，请从历史中重新打开。",
  conversation_device_mismatch:"这段对话属于另一台电脑，请为新电脑开启新对话。",
  rate_limited: "操作较频繁，请一分钟后重试。",
  usage_already_submitted: "这项请求已提交，请查看原结果。",
  utterance_too_long: "这段录音已达到 30 秒，请分句录制。",
  voice_connection_ended: "语音连接中断，请重新录音。",
  voice_connection_slow:"语音连接等待过久或网络阻塞，请重试；尚未发送文字任务。",
  qr_expired: "二维码已使用或已过期，请在电脑上刷新后重新扫描。",
};
function error(e) {
  const text = ({NotAllowedError:"microphone_denied",NotFoundError:"microphone_missing",NotReadableError:"microphone_unavailable"})[e.name] || e.message || String(e);
  notice(errors[text] || text);
}
async function api(
  path,
  body,
  method = body === undefined ? "GET" : "POST",
  options = {},
) {
  const requestToken = token;
  const r = await fetch(base + path, {
    method,
    signal: options.signal,
    headers: {
      Authorization: "Bearer " + requestToken,
      ...(body !== undefined ? { "Content-Type": options.raw ? "image/jpeg" : "application/json" } : {}),
      ...(options.requestId ? { "X-Request-ID": options.requestId } : {}),
    },
    body: body === undefined ? undefined : options.raw ? body : JSON.stringify(body),
  });
  if (!r.ok) {
    let data = {};
    try {
      data = await r.json();
    } catch {}
    if (r.status === 401 && requestToken === token) logoutLocal();
    throw new Error(data.error || "服务暂时不可用 (" + r.status + ")");
  }
  return r;
}
async function json(path, body, method) {
  return (await api(path, body, method)).json();
}
function showPage(id,options={}) {
  if(!['conversation','create','life','tasks','devices'].includes(id))return;
  if(id!=="conversation"&&id!=="create")window.ShengjianVisual?.stopCamera();
  document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==id);
  for(const b of document.querySelectorAll('.app-nav button')){const selected=b.dataset.page===id;b.classList.toggle('selected',selected);if(selected)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
  window.ShengjianProduct?.navigated(id,options);
  if(id==='create')window.ShengjianImages?.open();
  if(id!=='create')window.ShengjianImages?.chat();
  if(id==='life')window.ShengjianLife?.refresh();
}
function modelName(id) { const names={'workbuddy/cn:deepseek-v4.1-flash':'DeepSeek V4.1 Flash','workbuddy/cn:deepseek-v4-flash':'DeepSeek V4 Flash','workbuddy/cn:deepseek-v4-pro':'DeepSeek V4 Pro'};return names[id] || id.replace('workbuddy/cn:', '').replaceAll('-', ' '); }
async function loadModels(owner) {
  const data=await json('/assistant/preferences');
  if(owner!==token || !token)return;
  const select=$('chat-model'); select.replaceChildren();
  for(const item of data.chat_models)select.add(new Option(modelName(item.id), item.id));
  if(data.chat_model && !data.chat_models.some(m=>m.id===data.chat_model))select.add(new Option('原模型暂不可用，请重新选择',data.chat_model));
  select.value=data.chat_model;select.disabled=!data.chat_models.length;
  $('current-model-name').textContent=data.chat_model?modelName(data.chat_model):'模型尚未配置';
  modelOwner=owner;
}
$('chat-model').onchange=async()=>{
  const owner=token, select=$('chat-model');modelSaving=true;select.disabled=true;
  try{const data=await json('/assistant/preferences',{chat_model:select.value},'PATCH');if(owner!==token)return;
    $('current-model-name').textContent=modelName(data.chat_model);$('model-note').textContent='已保存。下一轮对话和新工作使用此模型，正在执行的任务保持原模型。';
  }catch(e){if(owner===token){error(e);await loadModels(owner).catch(error);}}
  finally{if(owner===token){modelSaving=false;select.disabled=false;}}
};
for(const suggestion of document.querySelectorAll('[data-prompt]'))suggestion.onclick=()=>{$('prompt').value=suggestion.dataset.prompt;$('prompt').focus();};
function logoutLocal() {
  window.ShengjianProduct?.deactivate();appSnapshot=null;taskViewId="";
  for(const stop of backgroundWork.values())stop();
  replyController?.abort();replyController=null;
  window.ShengjianVisual?.deactivate();
  window.ShengjianLife?.deactivate();
  window.ShengjianImages?.deactivate();
  reportEpoch++;
  authEpoch++;
  taskEpoch++;
  composeEpoch++;
  busy = false;
  currentTask = "";
  cursor = 0;
  $("compose").querySelector("[type=submit]").disabled = false;
  $("prompt").value = "";
  $("device-list").replaceChildren();
  $("task-list").replaceChildren();
  $("task-detail").replaceChildren(
    el("p", "选择任务查看进度。手机切后台不会取消任务。", "muted"),
  );
  token = "";
  agentMode = false;
  computerDevices = [];
  modelOwner="";modelSaving=false;
  $("chat-model").replaceChildren(new Option("正在载入模型…",""));$("chat-model").disabled=true;
  $("current-model-name").textContent="选择模型";$("work-overview").replaceChildren();
  chatOwner="";harnessInterrupted=false;
  $("agent-mode").setAttribute("aria-pressed", "false");
  sessionStorage.removeItem("shengjian.session");
  if (stream) stream.close();
  clearInterval(refreshTimer);
  window.ShengjianPTT?.deactivate();
  stopLive();
  stopCapture(false);
  stopSpeech();
  $("auth").hidden = false;
  $("workspace").hidden = true;
  $("logout").hidden = true;
  $("profile-open").hidden=true;document.body.classList.remove("signed-in");
  $("device-config").textContent = "";
  $("voice-latency").textContent = "";
  $("voice-latency").hidden = true;
  messages = [];
  $("messages").replaceChildren();
}
async function enter() {
  const owner = token;
  await refresh();
  if (owner !== token || !token) return;
  if(!window.ShengjianProduct)await new Promise((resolve,reject)=>{let timer;const ready=()=>{clearTimeout(timer);resolve();};window.addEventListener('shengjian:product-ready',ready,{once:true});timer=setTimeout(()=>{window.removeEventListener('shengjian:product-ready',ready);reject(new Error('界面加载未完成，请刷新后继续。'));},10000);});
  if(owner!==token||!token)return;
  $("auth").hidden = true;
  $("workspace").hidden = false;
  $("logout").hidden = false;
  $("profile-open").hidden=false;document.body.classList.add("signed-in");
  window.ShengjianProduct?.entered();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => refresh().catch(error), 10000);
}
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const operation = ++authEpoch;
  window.ShengjianProduct?.authBusy(true);
  try {
    const form = new FormData(e.target),
      action = e.submitter?.value || e.target.querySelector(".auth-submit").value;
    const body = {
      username: String(form.get("username")||"").trim(),
      password: form.get("password"),
    };
    if (action === "register") body.invite = String(form.get("invite")||"").trim();
    const data = await json("/auth/" + action, body);
    if (operation !== authEpoch) return;
    token = data.token;
    // Persistent credential lives in the server's HttpOnly HTTPS cookie.
    sessionStorage.removeItem("shengjian.session");
    e.target.reset();
    await enter();
    notice();
  } catch (e) {
    error(e);
  } finally { window.ShengjianProduct?.authBusy(false); }
});
$("logout").onclick = async () => {
  const owner = token;
  try {
    await json("/auth/logout", {});
    if (owner === token) logoutLocal();
  } catch (failure) { error(failure); }
};
document
  .querySelectorAll("nav button")
  .forEach((b) => (b.onclick = () => showPage(b.dataset.page)));
async function refresh() {
  const owner = token;
  const [me, devices, tasks] = await Promise.all([
    json("/me"),
    json("/devices"),
    json("/tasks"),
  ]);
  if (owner !== token || !token) return;
  $("balance").textContent = me.unlimited?"无限额度":`可用 ${me.balance} 积分${me.reserved?" · 待结算 "+me.reserved:""}`;
  window.ShengjianVisual?.activate(me.user_id, {json, fetchImage:id=>api('/life/images/'+id)});
  window.ShengjianLife?.activate(me.user_id, { json, image: (blob, id) => api('/life/images', blob, 'POST', {raw: true, requestId: id}), fetchImage: id => api('/life/images/'+id) });
  window.ShengjianImages?.activate(me.user_id,{json, file:id=>api('/images/jobs/'+id+'/file'),preview:id=>api('/life/images/'+id)});
  window.ShengjianPTT?.activate(me.user_id);
  chatOwner=me.user_id;
  if(modelOwner!==owner && !modelSaving)await loadModels(owner).catch(e=>{$('model-note').textContent='模型列表暂未载入，可稍后刷新。';error(e);});
  if(owner!==token)return;
  computerDevices = devices.devices.filter(d => !d.revoked && d.grants.includes("tasks"));
  $("computer-status").textContent=computerDevices.some(d=>d.online)?"电脑已连接":"电脑未连接";
  $("computer-status").dataset.online=String(computerDevices.some(d=>d.online));
  const selected = $("destination").value;
  $("destination").replaceChildren(new Option("自动选择电脑", "chat"));
  for(const d of devices.devices)if(!d.revoked&&d.grants.includes('tasks'))$('destination').add(new Option(d.name+(d.online?' · 在线':' · 离线'),d.id));
  if ([...$("destination").options].some((o) => o.value === selected))
    $("destination").value = selected;
  if (live && $("destination").value !== live.destination)
    stopLive("目标设备已不可用，实时对话已暂停");
  appSnapshot={me,devices:devices.devices,tasks:tasks.tasks};
  window.ShengjianProduct?.update(appSnapshot);

}
$("refresh").onclick = () => refresh().catch(error);
$("enroll").onsubmit = async (e) => {
  e.preventDefault();
  const owner = token;
  try {
    const name = new FormData(e.target).get("name"),
      d = await json("/devices", { name, capabilities: ["tasks", "metrics"] });
    if (owner !== token || !token) return;
    $("device-config").textContent = JSON.stringify(
      {
        server: location.origin + base,
        token: d.token,
        device_id: d.id,
        workspace: "请替换为电脑上允许 Agent 工作的绝对目录",
      },
      null,
      2,
    );
    notice("设备密钥只显示这一次，请保存到电脑私有配置文件。");
    await refresh();
  } catch (e) {
    error(e);
  }
};
async function openTask(id, { reveal = true, conversation = false, announce = false } = {}) {
  const epoch = ++taskEpoch;
  if (stream) stream.close();
  currentTask = id;taskViewId=id;
  cursor = 0;
  if (reveal) showPage("tasks",{task:id});
  const d = await json("/tasks/" + id);
  if (epoch !== taskEpoch || !token) return;
  const terminal = new Set(["succeeded", "failed", "cancelled", "unknown"]);
  let taskTerminal=terminal.has(d.task.state);
  const stateLine = el("p", labels[d.task.state] || d.task.state, "state-badge");stateLine.dataset.state=d.task.state;
  const cancelButton = button("取消任务", async () => {
    const reply = await json("/tasks/" + id + "/cancel", {});
    notice(
      terminal.has(reply.task.state)
        ? "任务状态：" + labels[reply.task.state]
        : "已请求取消，等待电脑确认。",
    );
  });
  cancelButton.disabled = terminal.has(d.task.state);
  $("task-detail").replaceChildren(
    el(
      "h2",
      (typeof d.task.specification === "string"
        ? JSON.parse(d.task.specification)
        : d.task.specification
      )?.prompt || "任务进度",
    ),
    stateLine,
    cancelButton,
    button("停止播报", stopAgentSpeech),
  );
  window.ShengjianProduct?.taskOpened(id,reveal);
  let resultText = "",
    spoken = false;
  const reports = new Set();
  const approvals = new Map();
  function connect() {
    if (taskViewId !== id || epoch !== taskEpoch || !token) return;
    const connection = new WebSocket(
      location.origin.replace(/^http/, "ws") +
        base +
        "/tasks/" +
        id +
        "/stream",
    );
    stream = connection;
    connection.onopen = () => {
      if (epoch !== taskEpoch || !token) {
        connection.close();
        return;
      }
      connection.send(JSON.stringify({ token, after: cursor }));
    };
    connection.onmessage = (e) => {
      if (epoch !== taskEpoch) return;
      const item = JSON.parse(e.data);
      if (!item.seq || item.seq <= cursor) return;
      cursor = item.seq;
      const event = item.body || item.event || item;
      window.ShengjianProduct?.taskEvent(event);
      const text =
        event.text ||
        (event.state ? labels[event.state] || event.state : event.type);
      if (event.type === "task.state") {
        stateLine.textContent = labels[event.state] || event.state;stateLine.dataset.state=event.state;
        if (terminal.has(event.state)) {
          taskTerminal=true;
          cancelButton.disabled = true;
          for (const actions of approvals.values()) actions.remove();
        }
        if (conversation && !reports.has(event.state) && ["awaiting_user", "failed", "cancelled", "unknown"].includes(event.state)) {
          reports.add(event.state);
          agentReport(event.state === "awaiting_user" ? "电脑需要你确认本次操作。请查看任务卡片，可说允许本次操作或拒绝本次操作。" : "电脑任务" + labels[event.state] + "。");
        }
        if (event.state === "succeeded" && resultText && !spoken) {
          spoken = true;
          if (conversation) agentReport("电脑任务已完成。" + resultText);
          else if(announce&&$("speak").checked)speak(resultText).catch(error);

        }
      } else if(!window.ShengjianProduct)$("task-detail").append(el("pre", text));
      if (event.type === "task.result") resultText = event.text || "";
      if (event.type === "approval.decision")
        approvals.get(event.approval_id)?.remove();
      if (event.type === "task.approval") {
        stateLine.textContent = labels.awaiting_user;
        if (conversation && !reports.has(event.approval_id)) {
          reports.add(event.approval_id);
          agentReport("电脑需要你确认本次操作，请查看任务卡片。可说允许本次操作或拒绝本次操作。");
        }
        const actions = el("div", undefined, "actions");
        for (const allow of [true, false])
          actions.append(
            button(allow ? "允许本次操作" : "拒绝", async () => {
              await json("/tasks/" + id + "/approvals/" + event.approval_id, {
                allow,
              });
              actions.remove();
            }),
          );
        approvals.set(event.approval_id, actions);
        $("task-detail").append(actions);
      }
    };
    connection.onclose = () => {
      if (!taskTerminal && taskViewId === id && epoch === taskEpoch && token)
        setTimeout(connect, 2000);
    };
  }
  connect();
}
function message(role, text, images=[]) {
  window.ShengjianLife?.capture(role, text, images);
  const bubble=el("div", text, "message " + role);$("messages").append(bubble);
  window.ShengjianProduct?.messageAdded(bubble,role,text,images);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function agentReport(text) {
  message("assistant", text);
  const owner = token, epoch = reportEpoch, until = Date.now() + 30000;
  function play() {
    if (owner !== token || epoch !== reportEpoch || !$("speak").checked || Date.now() > until) return;
    if (live?.processing || live?.detector?.active || busy || playback || agentAckPending || reportSpeaking) return setTimeout(play, 250);
    reportSpeaking = true;
    speak(text.slice(0, 1800)).catch(failure => { if (owner === token && failure.name !== "AbortError") error(failure); }).finally(() => { reportSpeaking = false; });
  }
  play();
}
$("agent-mode").onclick = () => {
  notice("当前 Chat 已直接连接本机 DeepSeek Harness，聊天、看图和执行工作使用同一会话。停止播报不会取消已运行的工作。");
};
$("compose").onsubmit = (e) => {
  e.preventDefault();
  submitPrompt($("prompt").value.trim());
};
async function submitPrompt(prompt) {
  if (busy) return;
  if (!prompt) return;
  if (ShengjianAgent.silence(prompt)) {
    reportEpoch++;
    stopSpeech();
    notice("已停止播报，电脑任务继续运行。");
    $("prompt").value = "";
    return;
  }
  replyController?.abort();
  const owner = token,
    operation = ++composeEpoch;
  busy = true;
  notice();
  const submit = $("compose").querySelector("[type=submit]");
  submit.disabled = true;
  stopSpeech();
  const creating=document.body.dataset.activePage==='create';
  const imageIntent=creating?(window.ShengjianProduct?.creationIntent(prompt)||window.ShengjianImages?.intent(prompt)):null;
  try {
    if(creating&&await window.ShengjianProduct?.creationControl(prompt))return;
    if(imageIntent){
      const edited=imageIntent==='edit';
      const job=await window.ShengjianImages.generate(prompt,{edit:edited});
      if(owner!==token || operation!==composeEpoch)return;
      if(window.ShengjianProduct)window.ShengjianProduct.jobSubmitted(job,edited);
      else{message('user',prompt);message('assistant',edited?'修改已排队。':'图片已开始创作。');$('messages').append(button('查看图片与版本',()=>window.ShengjianImages.open()));}
      $('prompt').value='';
      if(live&&$('speak').checked)speak(edited?'已收到调整，会接着上一版修改。':'已经开始生成图片，你可以继续聊天。').catch(error);
      return;
    }
    const selected = $("destination").value;
    if ($("engine").value === "harness" || selected === "chat") {
      const visual=ShengjianAgent.control(prompt)?{images:[]}:(await window.ShengjianVisual?.snapshot(prompt) || {images:[]});
      if(owner!==token || operation!==composeEpoch)return;
      message("user",prompt,visual.images);
      await streamHarness(prompt,visual.images,owner,operation,selected);
      return;
    }
    if ((live || agentMode || selected === "chat") && ShengjianAgent.shouldRoute(prompt, agentMode || selected !== "chat", window.ShengjianVisual?.hasContext() && !/任务|电脑|agent|harness/i.test(prompt) ? null : currentTask)) {
      message("user", prompt);
      const data = await json("/assistant/turn", { text: prompt, request_id: crypto.randomUUID(), device_id: selected === "chat" ? null : selected, task_id: currentTask || null, engine: $("engine").value });
      if (owner !== token || operation !== composeEpoch) return;
      $("prompt").value = "";
      message("assistant", data.reply);
      if (data.task && (data.action === "task" || currentTask !== data.task.id)) {
        await openTask(data.task.id, { reveal: false, conversation: data.action === "task" });
        $("messages").append(button("查看任务与确认", () => showPage("tasks")));
      }
      busy = false;
      submit.disabled = false;
      if ($("speak").checked) {
        agentAckPending = true;
        speak(data.reply).catch(failure => { if (owner === token && failure.name !== "AbortError") error(failure); }).finally(() => { agentAckPending = false; });
      }
      await refresh();
    } else if (selected !== "chat") {
      window.ShengjianLife?.capture("user", prompt);
      const d = await json("/tasks", {
        device_id: $("destination").value,
        prompt,
        engine: $("engine").value,
        request_id: crypto.randomUUID(),
      });
      if (owner !== token || operation !== composeEpoch) return;
      $("prompt").value = "";
      await openTask(d.task.id,{announce:true});
      if (owner === token && operation === composeEpoch) await refresh();
    }
    if (owner === token && operation === composeEpoch) await refresh();
  } catch (e) {
    if(e.name==="AbortError")return;
    if (owner === token && operation === composeEpoch) {
      reportVoiceFailure("reply",e,live?.mode||"text");
      if (live && !imageIntent && e.message!=="chat_model_unavailable") stopLive("对话请求未完成，请确认后重新开启");
      error(e);
    }
  } finally {
    if (operation === composeEpoch) {
      busy = false;
      submit.disabled = false;
    }
  }
}
let speechEpoch = 0,
  playbackDone = null;
function stopSpeech() {
  speechEpoch++;
  voiceController?.abort();
  voiceController = null;
  if (playback) {
    playback.pause();
    URL.revokeObjectURL(playback.src);
    playback = null;
  }
  if (playbackDone) {
    playbackDone();
    playbackDone = null;
  }
}
async function speak(text,outputContext=null) {
  if (live?.capabilities?.streaming_audio) return speakStreaming(text);
  stopSpeech();
  const epoch = speechEpoch;
  const characters = Array.from(text);
  for (let offset = 0; offset < characters.length; offset += 1000) {
    if (epoch !== speechEpoch) return;
    const r = await api("/voice/speech", {
      input: characters.slice(offset, offset + 1000).join(""),
      request_id: crypto.randomUUID(),
    });
    const blob = await r.blob();
    if (epoch !== speechEpoch) return;
    let audio;
    // Reuse the AudioContext unlocked by the microphone button on mobile Safari.
    // A fresh HTMLAudioElement after a network round trip may require another tap.
    const context = outputContext || live?.context;
    if (context && typeof context.decodeAudioData === "function") {
      const buffer = await context.decodeAudioData(await blob.arrayBuffer());
      if (epoch !== speechEpoch || context.state === "closed") return;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      audio = {
        src: "",
        ended: false,
        play() {
          source.onended = () => {
            this.ended = true;
            this.onended?.();
            source.disconnect();
          };
          source.start();
          return Promise.resolve();
        },
        pause() {
          source.stop();
          this.onpause?.();
        },
      };
    } else audio = new Audio(URL.createObjectURL(blob));
    playback = audio;
    let failed = false;
    await new Promise((resolve) => {
      playbackDone = resolve;
      audio.onended = resolve;
      audio.onpause = () => {
        if (!audio.ended && epoch === speechEpoch) speechEpoch++;
        resolve();
      };
      audio.onerror = () => {
        failed = true;
        resolve();
      };
      audio.play().catch(() => {
        failed = true;
        if (epoch === speechEpoch)
          notice("浏览器暂停了声音播放，请先允许播放声音后重试。");
        resolve();
      });
    });
    if (playback === audio) {
      playbackDone = null;
      playback = null;
    }
    URL.revokeObjectURL(audio.src);
    if (failed) return;
  }
}

async function streamAudio(text, epoch, player) {
  if (epoch !== speechEpoch || !text.trim()) return;
  const controller = new AbortController();
  voiceController = controller;
  let audioDone = false;
  const segmentStart = Math.max(player.next, player.context.currentTime);
  try {
    const response = await api(
      "/voice/speech/stream",
      { input: text, request_id: crypto.randomUUID() },
      "POST",
      { signal: controller.signal },
    );
    await readEvents(
      response,
      "ndjson",
      async (event) => {
        if (event.type === "error") throw new Error(event.error);
        if (event.type === "audio.chunk" && epoch === speechEpoch)
          await player.push(event.data);
        if (event.type === "audio.finished") audioDone = true;
      },
      controller.signal,
    );
    if (!audioDone) throw new Error("audio_result_unknown");
    if (epoch === speechEpoch) player.mark(text, segmentStart);
  } catch(failure) {
    if(controller.signal.aborted)throw failure;
    if(failure.name==='TypeError')throw new Error('voice_network_error');
    if(['SyntaxError','InvalidCharacterError'].includes(failure.name))throw new Error('voice_stream_invalid');
    throw failure;
  } finally {
    if (voiceController === controller) voiceController = null;
  }
}
function speechPipeline(turn = null) {
  const epoch = speechEpoch,
    session = live;
  const player = new PCMPlayback(session.context, () => {
    if (live === session && epoch === speechEpoch) {
      playback = player;
      if (!session.metrics?.first_audio_ms && session.replyStart) {
        session.metrics = {
          ...session.metrics,
          first_audio_ms: Math.round(performance.now() - session.replyStart),
        };
      }
      const speechEnd = turn?.speechEnd;
      if (Number.isFinite(speechEnd) && !turn.latencyShown) {
        turn.latencyShown = true;
        const seconds = Math.max(
          0,
          player.firstScheduled -
            speechEnd +
            (session.context.outputLatency || session.context.baseLatency || 0),
        );
        $("voice-latency").textContent =
          "本轮首音约 " + seconds.toFixed(2) + " 秒";
        $("voice-latency").title =
          "根据本机采集和播放时钟估算；实际听感受音频设备与网络影响。";
        $("voice-latency").hidden = false;
      }
      liveState(session.mode==="hold"?"正在播报 · 按住说话即可打断":"正在播报 · 开口即可打断");
    }
  });
  player.echo = session.echo || null;
  if (turn) turn.player = player;
  // Register before the first audio arrives so pending synthesis can also be stopped.
  playback = player;
  let chain = Promise.resolve(),
    failure = null, consecutiveFailures=0, reportedFailure=false;
  const sentences = new VoiceSentences((text) => {
    chain = chain
      .then(async () => {
        if (epoch === speechEpoch && !failure) {
          await streamAudio(text, epoch, player);
          consecutiveFailures=0;
        }
      })
      .catch((e) => {
        if (epoch === speechEpoch) {
          consecutiveFailures++;
          const fatal=/^(?:unauthorized|audio_busy|audio_rejected|insufficient_credits|tts_login_required|streaming_voice_not_configured|invalid_audio_format|audio_context_)/.test(e.message||'');
          if(fatal||consecutiveFailures>=2)failure=e;
          reportVoiceFailure("playback",e,session.mode||"live");
          // Valid audio already queued must finish even if a later segment fails.
          // Do not retry a paid segment whose synthesis result is uncertain.
          if(!reportedFailure){error(e);reportedFailure=true;}
          liveState(failure?"语音连接未恢复，完整文字继续显示。":"有一小段播报中断，后续继续；完整文字会保留。");
        }
      });
  });
  player.onStop = () => sentences.cancel();
  return {
    push: (text) => sentences.push(text),
    async done() {
      sentences.flush();
      await chain;
      if (epoch === speechEpoch){
        try{await player.drain();}catch(e){if(epoch===speechEpoch){reportVoiceFailure('playback',e,session.mode||'live');player.pause();error(e);}}
      }
      if (playback === player) playback = null;
    },
  };
}
async function speakStreaming(text) {
  stopSpeech();
  const speech = speechPipeline();
  speech.push(text);
  await speech.done();
}
const backgroundWork=new Map();
function watchBackgroundWork(id,owner,after=0,hasWork=false){
 if(backgroundWork.has(id)||owner!==token)return;
 if(backgroundWork.size>=32)backgroundWork.values().next().value();
 let socket,cursor=after,closed=false,result="";
 const stop=()=>{closed=true;socket?.close();backgroundWork.delete(id);};
 backgroundWork.set(id,stop);
 function connect(){
  if(closed||owner!==token)return stop();
  socket=new WebSocket(location.origin.replace(/^http/,"ws")+base+"/tasks/"+id+"/stream");
  socket.onopen=()=>{if(owner!==token)return stop();socket.send(JSON.stringify({token:owner,after:cursor}));};
  socket.onmessage=e=>{
   if(owner!==token)return stop();
   const item=JSON.parse(e.data);if(!item.seq||item.seq<=cursor)return;cursor=item.seq;
   if(item.type==="task.log"){try{const l=JSON.parse(item.text);if(l.type==="tool_call"&&!["see_user_image","media_models","create_image","edit_image","view_conversation_image","image_job_status"].includes(l.tool))hasWork=true;}catch{}}
   if(item.type==="task.result")result=item.text||"";
   if(item.type==="task.state"&&["succeeded","failed","cancelled","unknown"].includes(item.state)){
    stop();if(!hasWork&&item.state==="succeeded")return;if(window.ShengjianProduct?.taskReportElsewhere(id,item.state))return;agentReport(item.state==="succeeded"?"后台工作已完成。"+result.slice(0,600):"后台工作"+(labels[item.state]||item.state)+"。");
   }
  };
  socket.onclose=()=>{if(!closed)setTimeout(connect,2000);};
 }
 connect();
}
async function streamHarness(prompt,images,owner,operation,selected) {
  const terminal=new Set(["succeeded","failed","cancelled","unknown"]);
  const key="shengjian.chat."+chatOwner+"."+selected;
  let conversation=window.ShengjianProduct?.conversationFor(selected)||sessionStorage.getItem(key);
  if(!conversation){conversation=crypto.randomUUID().replaceAll("-","");sessionStorage.setItem(key,conversation);}
  const interrupted=harnessInterrupted;harnessInterrupted=false;
  const pendingKey='shengjian.pending-turn.'+chatOwner+'.'+conversation;let pending;
  try{pending=JSON.parse(sessionStorage.getItem(pendingKey)||'null');}catch{}
  if(!pending||pending.text!==prompt||pending.conversation_id!==conversation||pending.device_id!==(selected==='chat'?null:selected)||JSON.stringify(pending.life_images)!==JSON.stringify(images)){
    pending={text:prompt,request_id:crypto.randomUUID(),conversation_id:conversation,device_id:selected==='chat'?null:selected,task_id:currentTask||null,life_images:images,interrupted};sessionStorage.setItem(pendingKey,JSON.stringify(pending));
  }
  const data=await json('/assistant/chat',pending);sessionStorage.removeItem(pendingKey);
  window.ShengjianProduct?.turnAccepted(conversation,data);

  if(owner!==token || operation!==composeEpoch)return;
  if($("prompt").value.trim()===prompt)$("prompt").value="";
  if(data.action!=="chat") {
    message("assistant",data.reply);
    if($("speak").checked)await speak(data.reply);
    return;
  }
  const id=data.task.id;
  busy=false;$("compose").querySelector("[type=submit]").disabled=false;
  currentTask=id;
  const workLink=button("查看工作进展",()=>openTask(id));workLink.className="work-turn-link";workLink.hidden=!data.task.is_work;$("messages").append(workLink);
  const controller=new AbortController();replyController=controller;
  const session=live;
  if(session)session.replyStart=performance.now();
  const turn={history:[...messages,{role:"user",content:prompt}],images,text:"",voiced:$("speak").checked,complete:false,speechEnd:session?.utterance?.speechEnd,harness:true};
  if(session)session.replyTurn=turn;
  const speech=session && turn.voiced?speechPipeline(turn):null;
  const node=el("div",data.queued_behind?"补充已排队，当前工作继续运行。可随时询问进度或取消任务。":"正在思考…","message assistant");turn.node=node;node.dataset.chatTask=id;$("messages").append(node);window.ShengjianConversationMedia?.poll();
  let cursor=0, socket, result="", settled=false, modelFailed=false, approvalSeen=new Set();
  try {
    await new Promise((resolve,reject)=>{
      const finish=(failure)=>{if(settled)return;settled=true;socket?.close();controller.signal.removeEventListener("abort",abort);failure?reject(failure):resolve();};
      const abort=()=>{harnessInterrupted=true;if(owner===token)watchBackgroundWork(id,owner,cursor,turn.work);finish(new DOMException("Interrupted","AbortError"));};
      controller.signal.addEventListener("abort",abort,{once:true});
      function connect(){
        if(settled || controller.signal.aborted)return;
        socket=new WebSocket(location.origin.replace(/^http/,"ws")+base+"/tasks/"+id+"/stream");
        socket.onopen=()=>{if(settled){socket.close();return;}socket.send(JSON.stringify({token:owner,after:cursor}));};
        socket.onmessage=e=>{
          if(settled || owner!==token || operation!==composeEpoch)return;
          const item=JSON.parse(e.data);if(!item.seq||item.seq<=cursor)return;cursor=item.seq;
          if(item.type==="model.failure")modelFailed=true;
          if(item.type==="task.log"){try{const log=JSON.parse(item.text);if(log.type==="tool_call"&&!["see_user_image","media_models","create_image","edit_image","view_conversation_image","image_job_status"].includes(log.tool)){turn.work=true;workLink.hidden=false;window.ShengjianProduct?.workStarted(id,prompt);}}catch{}}
          if(item.type==="task.delta"){
            if(!turn.text && session)session.metrics={...session.metrics,first_token_ms:Math.round(performance.now()-session.replyStart)};
            turn.text+=item.text||"";node.textContent=turn.text;window.ShengjianProduct?.revealReply(node);speech?.push(item.text||"");
          } else if(item.type==="task.result")result=item.text||"";
          else if(item.type==="task.approval" && !approvalSeen.has(item.approval_id)){
            workLink.hidden=false;turn.work=true;window.ShengjianProduct?.workStarted(id,prompt);approvalSeen.add(item.approval_id);notice("电脑需要确认，请打开本轮工作卡片；也可说允许本次操作或拒绝本次操作。");
            // Keep listening while the owned work waits; a new spoken control goes through the same task API.
            busy=false;$("compose").querySelector("[type=submit]").disabled=false;
          } else if(item.type==="task.state" && terminal.has(item.state)) {
            if(item.state!=="succeeded")return finish(new Error(item.state==="failed"&&modelFailed?"chat_model_unavailable":"本轮"+(labels[item.state]||item.state)+"，请查看工作记录；不会自动重试操作。"));
            if(!turn.text){turn.text=result;node.textContent=result;window.ShengjianProduct?.revealReply(node);speech?.push(result);}
            finish();
          }
          $("messages").scrollTop=$("messages").scrollHeight;window.ShengjianProduct?.scrollConversation();
        };
        socket.onclose=()=>{if(!settled)setTimeout(connect,1000);};
      }
      connect();
    });
    if(owner!==token || operation!==composeEpoch)return;
    if(!turn.text)throw new Error("本机未返回对话结果，请查看工作记录。");
    messages=[...turn.history,{role:"assistant",content:result||turn.text}].slice(-200);
    window.ShengjianLife?.capture("assistant",result||turn.text,images);turn.lifeRecorded=true;
    if(speech)await speech.done();else if(turn.voiced)await speak(result||turn.text);
    turn.complete=true;window.ShengjianProduct?.messageAdded(node,"assistant",result||turn.text,images);
    await refresh();
  } catch(failure) {
    if(failure.message==="chat_model_unavailable"&&speech)await speech.done();
    throw failure;
  } finally {socket?.close();if(replyController===controller)replyController=null;}
}
function stopAgentSpeech() { reportEpoch++; stopSpeech(); }
$("stop-speech").onclick = stopAgentSpeech;
async function stopCapture(finish = true) {
  if(!finish)legacyCaptureEpoch++;
  const c = capture;
  if (!c) return;
  capture = null;
  clearTimeout(c.timer);
  if (c.processor) c.processor.disconnect();
  if (c.source) c.source.disconnect();
  if (c.media) c.media.getTracks().forEach((t) => t.stop());
  if (c.context) await c.context.close();
  if (c.ws?.readyState === WebSocket.OPEN) {
    if (finish) c.ws.send(JSON.stringify({ type: "finish" }));
    else c.ws.close();
  }
  $("record").textContent = "录音转文字";
}
$("record").onclick = async () => {
  stopLive();
  if (capture) {
    await stopCapture();
    return;
  }
  stopSpeech();
  let c = { owner: token,epoch:++legacyCaptureEpoch };
  capture = c;
  try {
    c.media = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        channelCount: 1,
      },
    });
    if (capture !== c) {
      c.media.getTracks().forEach((t) => t.stop());
      return;
    }
    c.ws = new WebSocket(
      location.origin.replace(/^http/, "ws") + base + "/voice/asr",
    );
    c.ws.onopen = () => {
      if (c.owner !== token || capture !== c) {
        c.ws.close();
        return;
      }
      c.ws.send(
        JSON.stringify({ token: c.owner, request_id: crypto.randomUUID() }),
      );
    };
    c.ws.onmessage = async (e) => {
      if (c.owner !== token || c.epoch !== legacyCaptureEpoch) {
        c.ws.close();
        return;
      }
      try {
        const event = JSON.parse(e.data);
        if (event.type === "error") throw new Error(event.error);
        if (event.type === "asr.final") {
          $("prompt").value = event.text;
          notice("识别完成，可编辑文字后发送。");
        }
        if (event.type === "asr.ready") {
          if (capture !== c) {
            c.ws.close();
            return;
          }
          c.context = new AudioContext();
          await c.context.resume();
          if(capture!==c||c.owner!==token||c.epoch!==legacyCaptureEpoch){c.media.getTracks().forEach(t=>t.stop());c.context.close().catch(()=>{});c.ws.close();return;}
          c.resampler = new PCMResampler(c.context.sampleRate);
          c.source = c.context.createMediaStreamSource(c.media);
          c.processor = c.context.createScriptProcessor(2048, 1, 1);
          c.processor.onaudioprocess = (event) => {
            if (capture !== c || c.ws.readyState !== WebSocket.OPEN) return;
            const pcm = c.resampler.push(event.inputBuffer.getChannelData(0));
            if (c.ws.bufferedAmount > 128000) {
              notice("网络发送较慢，录音已停止，请检查连接后重试。");
              stopCapture(false).catch(error);
              return;
            }
            for (let i = 0; i < pcm.length; i += 3200)
              c.ws.send(pcm.slice(i, i + 3200).buffer);
          };
          c.source.connect(c.processor);
          c.processor.connect(c.context.destination);
          $("record").textContent = "结束转文字";
          c.timer = setTimeout(() => stopCapture().catch(error), 29000);
          notice("正在录音，说完后点击结束录音。");
        }
        if (event.type === "asr.finished") c.ws.close();
      } catch (e) {
        reportVoiceFailure("dictation",e,"dictation");
        error(e);
        if(capture===c)await stopCapture(false);
        c.ws.close();
      }
    };
    c.ws.onerror=()=>{if(capture===c&&c.owner===token){const failure=new Error("voice_connection_ended");reportVoiceFailure("dictation",failure,"dictation");error(failure);stopCapture(false).catch(error);}};
    c.ws.onclose = () => {
      if (capture === c) stopCapture(false).catch(error);
    };
  } catch (e) {
    if(capture===c){reportVoiceFailure("dictation",e,"dictation");error(e);await stopCapture(false);}
  }
};
function liveState(text) {
  $("live-state").textContent = text;
  if($("image-voice-state"))$("image-voice-state").textContent="画室语音 · "+text;
}
function interruptReply(session = live) {
  reportEpoch++;
  const turn = session?.replyTurn;
  if (turn && !turn.complete && !turn.interrupted) {
    turn.interrupted = true;
    if(turn.harness)harnessInterrupted=true;
    const heard = turn.voiced ? turn.player?.heard() || "" : turn.text;
    if (!turn.lifeRecorded && heard) { window.ShengjianLife?.capture('assistant', heard+'（已打断）',turn.images || []); turn.lifeRecorded = true; }
    messages = [
      ...turn.history,
      {
        role: "assistant",
        content:
          (heard || "") +
          "（用户打断了回复，后续内容未播出。请接着用户的新话继续。）",
      },
    ];
    if (turn.node) turn.node.dataset.interrupted = "true";
  }
  replyController?.abort();
  replyController = null;
  stopSpeech();
  // Discard late model/TTS results; never replay or cancel a computer task here.
  if ($("destination").value === "chat" || turn?.harness) {
    composeEpoch++;
    busy = false;
    $("compose").querySelector("[type=submit]").disabled = false;
  }
}
function stopLive(reason = "实时对话已结束", preserveCamera = false, preserveReply = false) {
  if(!preserveCamera)window.ShengjianVisual?.stopCamera();
  const session = live;
  live = null;
  if (session) {
    session.closed = true;
    if(!session.speakEdited&&session.speakBefore!==undefined)$("speak").checked=session.speakBefore;
    clearTimeout(session.timeout);
    clearTimeout(session.manualTimer);
    session.utterance?.flow?.close();
    session.waitingFor?.flow?.close();
    if(session.manualGesture)session.manualGesture.held=false;
    window.ShengjianPTT?.reset();
    session.ws?.close();
    session.sockets?.forEach((socket) => socket.close());
    $("live-transcript").textContent = "";
    $("live-transcript").hidden = true;
    session.processor?.disconnect();
    session.processor?.port?.close();
    session.source?.disconnect();
    session.media?.getTracks().forEach((track) => track.stop());
    session.context?.close().catch(() => {});
    stopSpeech();
    // Ignore results from a conversation that the user ended.
    if (!preserveReply && session.owner === token && (session.destination === "chat" || session.replyTurn?.harness))
      interruptReply(session);
  }
  $("realtime").textContent = "开始实时对话";
  $("realtime").setAttribute("aria-pressed", "false");
  $("record").disabled = false;
  $("destination").disabled = false;
  $("engine").disabled = false;
  $("live-state").hidden = !session;
  if (session) liveState(reason);
}
function liveFailure(session, failure) {
  if (live !== session) return;
  stopLive("实时对话已暂停，请重新开启");
  reportVoiceFailure("asr",failure,session.mode||"live");
  error(failure);
}
function startUtterance(session, chunks) {
  if (live !== session) return;
  const previous = session.utterance;
  if (session.waitingFor && previous && !previous.ws) {
    previous.ended = false;
    for (const chunk of chunks) sendLivePCM(session, chunk, previous);
    liveState("正在听，请继续说…");
    return;
  }
  const continuing =
    previous &&
    !previous.final &&
    previous.ended &&
    previous.ws &&
    !session.waitingFor;
  if (continuing) session.waitingFor = previous;
  else if (previous && !previous.final) {
    previous.abandoned = true;
    previous.flow?.close();
    previous.ws?.close();
  }
  if(playback&&session.mode==='live')reportVoiceFailure('capture',new Error(session.echo?.last.correlation>.5?'barge_in_echo_related':'barge_in_voice_detected'),'live');
  interruptReply();
  session.processing = true;
  session.firstPartial = false;
  $("live-transcript").textContent = "";
  $("live-transcript").hidden = false;
  session.utteranceStart = performance.now();
  $("voice-latency").hidden = true;
  const utterance = {
    pending: [...chunks],
    ended: false,
    ready: false,
    final: false,
    prefix: "",
    ws: null,
  };
  session.utterance = utterance;
  for(const chunk of utterance.pending)ensureVoiceFlow(session,utterance).push(chunk);
  utterance.pending=[];
  if (continuing) {
    clearTimeout(session.timeout);
    session.timeout = setTimeout(
      () => liveFailure(session, new Error("voice_connection_ended")),
      8000,
    );
    liveState("正在听，请继续说…");
    return;
  }
  openLiveASR(session, utterance);
}
function openLiveASR(session, utterance) {
  if (live !== session || session.utterance !== utterance) return;
  liveState(session.mode==="hold"?"按住说话中 · 松开发送，上滑取消":"正在听，停顿后自动发送…");
  const socket = new WebSocket(
    location.origin.replace(/^http/, "ws") +
      base +
      (session.capabilities?.asr_path || "/voice/asr"),
  );
  session.ws = socket;
  utterance.ws = socket;
  session.sockets ||= new Set();
  session.sockets.add(socket);
  clearTimeout(session.timeout);
  session.timeout = setTimeout(
    () => liveFailure(session, new Error("voice_connection_ended")),
    110000,
  );
  socket.onopen = () => {
    if (live !== session || session.owner !== token) return socket.close();
    socket.send(
      JSON.stringify({ token: session.owner, request_id: crypto.randomUUID() }),
    );
    utterance.authSent = true;
    if(session.capabilities?.early_audio)ensureVoiceFlow(session,utterance).early();
  };
  socket.onmessage = async (event) => {
    if (
      live !== session ||
      utterance.abandoned ||
      utterance.final ||
      (session.utterance !== utterance && session.waitingFor !== utterance) ||
      session.owner !== token
    )
      return;
    try {
      const reply = JSON.parse(event.data);
      if (reply.type === "error") throw new Error(reply.error);
      if (reply.type === "asr.ready") {
        utterance.ready = true;
        const pending=utterance.pending;utterance.pending=[];
        for(const chunk of pending)sendLivePCM(session,chunk,utterance);
        utterance.flow?.ready();
        if (utterance.ended) finishLivePCM(session, utterance);
      }
      if (reply.type === "asr.partial" && session.utterance === utterance) {
        $("live-transcript").textContent =
          (utterance.prefix ? utterance.prefix + " " : "") + (reply.text || "");
        if (!session.firstPartial) {
          session.firstPartial = true;
          session.metrics = {
            first_partial_ms: Math.round(
              performance.now() - session.utteranceStart,
            ),
          };
        }
      }
      if (reply.type === "asr.final" && !utterance.final) {
        $("live-transcript").textContent = reply.text || "";
        utterance.final = true;
        clearTimeout(session.timeout);
        socket.close();
        const recognized = reply.text?.trim() || "";
        if (session.waitingFor === utterance) {
          session.waitingFor = null;
          const next = session.utterance;
          next.prefix = [utterance.prefix, recognized]
            .filter(Boolean)
            .join(" ");
          openLiveASR(session, next);
          return;
        }
        const text = [utterance.prefix, recognized].filter(Boolean).join(" ");
        $("live-transcript").textContent = text;
        if (text) {
          $("prompt").value = text;
          liveState(
            session.destination === "chat"
              ? "正在回复，可随时开口打断…"
              : "正在发送电脑任务…",
          );
          const submitted=submitPrompt(text);
          if(session.mode==="hold"){ $("destination").disabled=false;$("engine").disabled=false;$("record").disabled=false; }
          await submitted;
        }
        if (live === session && session.utterance === utterance) {
          session.processing = false;
          // The detector may already hold the next speaker's onset. Do not reset it here.
          liveState(session.mode==="hold"?"按住说话，松开后发送；按住可打断播报。":"正在聆听，请继续说…");
          if(session.mode==="hold")window.ShengjianPTT?.ready();
        }
      }
    } catch (failure) {
      liveFailure(session, failure);
    }
  };
  socket.onerror = () => {
    if (
      (session.utterance === utterance || session.waitingFor === utterance) &&
      !utterance.abandoned && !utterance.final
    )
      liveFailure(session, new Error("voice_connection_ended"));
  };
  socket.onclose = () => {
    session.sockets?.delete(socket);
    utterance.flow?.close();
    if (
      !utterance.final &&
      !utterance.abandoned &&
      (session.utterance === utterance || session.waitingFor === utterance)
    )
      liveFailure(session, new Error("voice_connection_ended"));
  };
}
function ensureVoiceFlow(session,u) {
  if(u.flow)return u.flow;
  u.flow=new VoicePCMFlow(pcm=>{
    if(live!==session||u.abandoned)throw new Error("voice_connection_ended");
    if(u.ws?.readyState!==WebSocket.OPEN||u.ws.bufferedAmount>128000)throw new Error("voice_connection_slow");
    if(!u.ready)u.earlySamples=(u.earlySamples||0)+pcm.length;
    u.ws.send(pcm.buffer);
  },()=>{if(live===session&&!u.abandoned&&u.ws?.readyState===WebSocket.OPEN){u.finishSent=true;u.ws.send(JSON.stringify({type:"finish"}));}},failure=>liveFailure(session,failure));
  return u.flow;
}
function finishLivePCM(session,u=session.utterance) {
  if(live!==session||!u||u.finishSent||!u.ws)return;
  const flow=ensureVoiceFlow(session,u);if(u.ready)flow.ready();flow.end();
}
function sendLivePCM(session,pcm,u=session.utterance) {
  if(live!==session||!u||u.abandoned)return;
  const flow=ensureVoiceFlow(session,u);flow.push(pcm);if(u.ready)flow.ready();
}
$("realtime").onclick = async () => {
  if (live && live.mode!=="hold") return stopLive();
  if(live)stopLive("切换到实时对话",true);
  if (busy && $("destination").value !== "chat") {
    notice("正在提交电脑任务，请稍后开启实时对话。");
    return;
  }
  await stopCapture(false);
  interruptReply();
  const session = {
    owner: token,
    destination: $("destination").value,
    processing: false,
    mode:"live",
    speakBefore:$("speak").checked,
  };
  live = session;
  $("realtime").textContent = "结束实时对话";
  $("realtime").setAttribute("aria-pressed", "true");
  $("record").disabled = true;
  $("destination").disabled = true;
  $("engine").disabled = true;
  $("speak").checked = true;
  $("live-state").hidden = false;
  liveState("正在开启麦克风…");
  try {
    session.context = new AudioContext();
    const resumed = session.context.resume();resumed.catch(()=>{});
    session.media = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    if (live !== session) {
      session.media.getTracks().forEach((track) => track.stop());
      return;
    }
    await resumed;
    const [capabilities, models] = await Promise.all([
      json("/voice/capabilities"),
      session.destination === "chat" ? json("/models") : Promise.resolve(null),
    ]);
    session.capabilities = capabilities;
    session.models = models;
    if (live !== session) return;
    const resampler = new PCMResampler(session.context.sampleRate);
    session.echo = new PlaybackEchoGuard();
    session.detector = new VoiceEndpoint({
      start: (chunks) => startUtterance(session, chunks),
      data: (pcm) => sendLivePCM(session, pcm),
      end: ({ trailingSilence = 0 } = {}) => {
        session.utterance.speechEnd =
          (session.sampleTime ?? session.context.currentTime) - trailingSilence;
        session.utterance.ended = true;
        finishLivePCM(session);
        liveState("正在识别…");
      },
    });
    session.source = session.context.createMediaStreamSource(session.media);
    const acceptSamples = (samples, time = session.context.currentTime) => {
      if (live !== session) return;
      session.sampleTime = time;
      if (
        !session.capabilities?.partial_results &&
        session.processing &&
        !session.detector.active &&
        !playback
      )
        return;
      session.detector.push(
        session.echo.process(resampler.push(samples), time),
      );
    };
    if (
      session.context.audioWorklet &&
      typeof AudioWorkletNode === "function"
    ) {
      await session.context.audioWorklet.addModule(
        base + "/console/capture-worklet.js",
      );
      if (live !== session) return;
      session.processor = new AudioWorkletNode(
        session.context,
        "shengjian-capture",
        { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] },
      );
      session.processor.port.onmessage = (event) =>
        acceptSamples(event.data.samples, event.data.time);
    } else {
      session.processor = session.context.createScriptProcessor(512, 1, 1);
      session.processor.onaudioprocess = (event) =>
        acceptSamples(event.inputBuffer.getChannelData(0));
    }
    session.source.connect(session.processor);
    session.processor.connect(session.context.destination);
    session.media
      .getTracks()
      .forEach((track) =>
        track.addEventListener("ended", () =>
          liveFailure(session, new Error("麦克风已断开，请重新开启实时对话。")),
        ),
      );
    session.context.onstatechange = () => recoverAudioContext(session);
    liveState(
      session.capabilities.partial_results
        ? "正在聆听 · 实时识别，可随时打断"
        : "正在聆听，请直接说…",
    );
  } catch (failure) {
    liveFailure(session, failure);
  }
};
$('speak').addEventListener('change',()=>{if(live)live.speakEdited=true;});
function reportVoiceFailure(stage,failure,mode='live') {
  if(!token||failure?.name==='AbortError')return;
  const names={NotAllowedError:stage==='playback'?'audio_playback_denied':'microphone_denied',NotFoundError:'microphone_missing',NotReadableError:'microphone_unavailable',AbortError:'client_aborted',InvalidStateError:'audio_context_invalid',NotSupportedError:'audio_format_unsupported',EncodingError:'audio_decode_failed',NetworkError:'voice_network_error',TypeError:'voice_type_error',SyntaxError:'voice_stream_invalid'};
  const raw=failure?.message||'';
  const code=/^[a-z][a-z0-9_]{2,80}$/.test(raw)?raw:(names[failure?.name]||'client_voice_failure');
  void json('/voice/client-events',{stage,code,mode}).catch(()=>{});
}
function recoverAudioContext(session){
  if(live!==session||session.closed||session.audioRecovery||document.hidden||!['suspended','interrupted'].includes(session.context.state))return;
  let timer;
  session.audioRecovery=Promise.race([session.context.resume(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('audio_context_paused')),1800);})])
   .then(()=>{if(live===session&&session.context.state!=='running')throw new Error('audio_context_paused');})
   .catch(failure=>{if(live===session){reportVoiceFailure('playback',failure,session.mode||'live');stopLive('音频被系统暂停，请点击语音按钮恢复。',false,true);notice('音频被系统暂停，文字回复继续。请点击语音按钮恢复。');}})
   .finally(()=>{clearTimeout(timer);session.audioRecovery=null;});
}
function detachManualMicrophone(session) {
  clearTimeout(session.manualTimer);session.manualTimer=null;
  session.processor?.disconnect();session.processor?.port?.close();session.processor=null;
  session.source?.disconnect();session.source=null;
  const media=session.media;session.media=null;session.manualRecording=false;
  media?.getTracks().forEach(track=>track.stop());
}
function endManualVoice(gesture,cancel=false) {
  gesture.held=false;
  if(gesture.ended)return;gesture.ended=true;
  const session=live;
  if(!session||session.mode!=='hold'||session.manualGesture!==gesture)return;
  const u=session.utterance;
  detachManualMicrophone(session);
  if(!gesture.ready||!u){$('destination').disabled=false;$('engine').disabled=false;$('record').disabled=false;liveState('已结束，未发送。按住并等麦克风就绪后说话。');window.ShengjianPTT?.ready();return;}
  if(cancel||gesture.cancelled||(u.samples||0)<2400){
    u.abandoned=true;u.flow?.close();u.ws?.close();clearTimeout(session.timeout);session.processing=false;$('destination').disabled=false;$('engine').disabled=false;$('record').disabled=false;
    liveState(cancel||gesture.cancelled?'已取消，未发送。':'说话时间太短，未发送。');window.ShengjianPTT?.ready();return;
  }
  u.speechEnd=session.context.currentTime;u.ended=true;finishLivePCM(session,u);
  liveState('正在识别，完成后自动发送…');window.ShengjianPTT?.recognizing();
}
async function startManualVoice(gesture) {
  if(!token)throw new Error('请先登录');
  if(live&&(live.mode!=='hold'||live.context?.state==='closed'))stopLive('切换到按键说话',true);
  let session=live;
  if(!session){session={owner:token,mode:'hold',destination:$('destination').value,processing:false,context:new AudioContext(),sockets:new Set(),speakBefore:$('speak').checked};live=session;}
  session.manualGesture=gesture;session.destination=$('destination').value;
  $('destination').disabled=true;$('engine').disabled=true;$('record').disabled=true;
  // Resume in the press gesture before awaiting microphone permission or network.
  const resumed=session.context.resume();resumed.catch(()=>{});
  await stopCapture(false);
  if(!gesture.held)return;
  interruptReply(session);
  if(session.utterance){session.utterance.abandoned=true;session.utterance.flow?.close();session.utterance.ws?.close();}
  session.utterance=null;session.waitingFor=null;
  clearTimeout(session.timeout);
  $('live-state').hidden=false;$('speak').checked=true;
  liveState('正在开启麦克风，准备好后说话…');
  try {
    const media=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
    if(live!==session||session.owner!==token||session.manualGesture!==gesture||!gesture.held){media.getTracks().forEach(t=>t.stop());return;}
    session.media=media;
    await resumed;
    session.capabilities ||= await json('/voice/capabilities');
    if(live!==session||session.owner!==token||session.manualGesture!==gesture||!gesture.held){if(session.media===media)detachManualMicrophone(session);else media.getTracks().forEach(t=>t.stop());return;}
    startUtterance(session,[]);
    const resampler=new PCMResampler(session.context.sampleRate);
    const accept=(samples)=>{
      if(live!==session||!gesture.held||!session.manualRecording)return;
      const pcm=resampler.push(samples);session.utterance.samples=(session.utterance.samples||0)+pcm.length;
      sendLivePCM(session,pcm);
    };
    session.source=session.context.createMediaStreamSource(media);
    if(session.context.audioWorklet&&typeof AudioWorkletNode==='function'){
      await session.context.audioWorklet.addModule(base+'/console/capture-worklet.js');
      if(live!==session||session.manualGesture!==gesture||!gesture.held){if(session.media===media)detachManualMicrophone(session);else media.getTracks().forEach(t=>t.stop());return;}
      session.processor=new AudioWorkletNode(session.context,'shengjian-capture',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]});
      session.processor.port.onmessage=e=>accept(e.data.samples);
    }else{
      session.processor=session.context.createScriptProcessor(512,1,1);
      session.processor.onaudioprocess=e=>accept(e.inputBuffer.getChannelData(0));
    }
    session.manualRecording=true;gesture.ready=true;
    session.source.connect(session.processor);session.processor.connect(session.context.destination);
    media.getTracks().forEach(track=>track.addEventListener('ended',()=>{if(live===session&&session.manualRecording){reportVoiceFailure('capture',new Error('hold_microphone_ended'),'hold');gesture.cancelled=true;endManualVoice(gesture,true);}}));
    session.context.onstatechange=()=>recoverAudioContext(session);
    session.manualTimer=setTimeout(()=>{if(gesture.held){endManualVoice(gesture);notice('已达到单次录音上限，已结束录音并发送。');}},29000);
    liveState('正在录音 · 松开发送，上滑取消');window.ShengjianPTT?.recording();
  }catch(failure){
    if(live!==session||session.manualGesture!==gesture)return;
    detachManualMicrophone(session);session.utterance?.flow?.close();if(session.utterance)session.utterance.abandoned=true;session.ws?.close();clearTimeout(session.timeout);session.processing=false;
    $('destination').disabled=false;$('engine').disabled=false;$('record').disabled=false;
    reportVoiceFailure('capture',failure,'hold');error(failure);liveState('麦克风未就绪，按住重试。');window.ShengjianPTT?.ready();
  }
}

window.addEventListener("offline", () =>
  stopLive(live?.mode==='hold'?"网络已断开，联网后按住重试。":"网络已断开，联网后重新开启语音。"),
);
document.addEventListener("visibilitychange", () => {
  if (document.hidden)
    stopLive(live?.mode==='hold'?"麦克风已暂停，返回后按住说话。":"麦克风已暂停，返回后重新开启语音。");
});
window.addEventListener("pagehide", () => stopLive());
let restoringLogin=false, lastSessionRenewal=0, pendingLoginTicket="";
async function restoreLogin() {
  if(restoringLogin)return;
  restoringLogin=true;
  pendingLoginTicket=new URLSearchParams(location.hash.slice(1)).get("login") || pendingLoginTicket;
  const ticket=pendingLoginTicket;
  if (ticket) history.replaceState(null, "", location.pathname + location.search);
  const operation = ++authEpoch;
  try {
    // An old QR URL must never discard a valid remembered browser session.
    if(!token){
      const data=await json('/auth/session',{});
      if(operation!==authEpoch)return;
      if(data.authenticated)token=data.token;
    }
    if(!token && ticket){
      const data=await json('/auth/qr/redeem',{ticket});
      if(operation!==authEpoch)return;
      token=data.token;sessionStorage.removeItem('shengjian.session');
    }
    if(token){pendingLoginTicket="";await enter();lastSessionRenewal=Date.now();}
  } catch(failure){if(failure.message==="qr_expired")pendingLoginTicket="";if(operation===authEpoch)error(failure);}
  finally{restoringLogin=false;}
}
window.addEventListener('online',()=>{if(!token)restoreLogin();else refresh().catch(error);});
window.addEventListener('pageshow',()=>{if(!token)restoreLogin();});
setInterval(async()=>{
 if(!token || document.hidden || Date.now()-lastSessionRenewal<6*3600000)return;
 try{const owner=token;const d=await json('/auth/session',{});if(owner===token&&d.authenticated)lastSessionRenewal=Date.now();}catch{}
},60000);
window.addEventListener("hashchange", restoreLogin);
restoreLogin();

window.addEventListener('shengjian:visual-change',event=>{if(event.detail?.origin==='image-edit')return;interruptReply();const content='用户已结束看图，当前没有提供图片或摄像头画面。可以回顾历史对话，但不能声称看到当前环境。';messages=messages.filter(m=>m.role!=='system'||m.content!==content);if(!window.ShengjianVisual?.hasContext())messages=[...messages,{role:'system',content}];});
window.ShengjianConversation={async openVisual(start=false){if(agentMode)$('agent-mode').click();$('destination').value='chat';showPage('conversation');if(start&&!live){if(window.ShengjianPTT?.mode()==='hold'){$('live-state').hidden=false;liveState('按住说话，松开后发送这张图片的问题。');}else await $('realtime').onclick();}}};
