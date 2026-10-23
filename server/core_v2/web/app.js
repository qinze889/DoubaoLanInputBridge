"use strict";
const base = "/shengjian/api/v2",
  $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("shengjian.session") || "",
  currentTask = "",
  cursor = 0,
  stream = null,
  refreshTimer = null,
  playback = null,
  capture = null,
  busy = false,
  messages = [],
  taskEpoch = 0;
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
  insufficient_credits: "测试额度不足，请联系管理员补充。",
  unauthorized: "登录已失效，请重新登录。",
  audio_busy: "语音来源正在处理其他请求，请稍后重试。",
  tts_login_required: "豆包登录态已失效，需要在服务器更新登录。",
  audio_rejected: "语音请求被拒绝，请稍后重试。",
  audio_result_unknown: "语音来源未确认结果，额度暂时预留，请勿反复重试。",
  model_result_unknown: "模型未确认结果，请查看任务状态后再操作。",
  model_provider_not_configured: "对话来源尚未配置。",
  model_discovery_failed: "暂时无法连接对话来源。",
  capability_not_granted: "请先在设备页开启这台电脑的任务能力。",
  rate_limited: "操作较频繁，请一分钟后重试。",
  usage_already_submitted: "这项请求已提交，请查看原结果。",
  utterance_too_long: "这段录音已达到 30 秒，请分句录制。",
  voice_connection_ended: "语音连接中断，请重新录音。",
};
function error(e) {
  const text = e.message || String(e);
  notice(errors[text] || text);
}
async function api(path, body, method = body === undefined ? "GET" : "POST") {
  const r = await fetch(base + path, {
    method,
    headers: {
      Authorization: "Bearer " + token,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let data = {};
    try {
      data = await r.json();
    } catch {}
    if (r.status === 401) logoutLocal();
    throw new Error(data.error || "服务暂时不可用 (" + r.status + ")");
  }
  return r;
}
async function json(path, body, method) {
  return (await api(path, body, method)).json();
}
function showPage(id) {
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== id));
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("selected", b.dataset.page === id));
}
function logoutLocal() {
  taskEpoch++;
  token = "";
  sessionStorage.removeItem("shengjian.session");
  if (stream) stream.close();
  clearInterval(refreshTimer);
  stopCapture(false);
  stopSpeech();
  $("auth").hidden = false;
  $("workspace").hidden = true;
  $("logout").hidden = true;
  $("device-config").textContent = "";
  messages = [];
  $("messages").replaceChildren();
}
async function enter() {
  await refresh();
  $("auth").hidden = true;
  $("workspace").hidden = false;
  $("logout").hidden = false;
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => refresh().catch(error), 10000);
}
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const form = new FormData(e.target),
      action = e.submitter.value;
    const body = {
      username: form.get("username"),
      password: form.get("password"),
    };
    if (action === "register") body.invite = form.get("invite");
    const data = await json("/auth/" + action, body);
    token = data.token;
    sessionStorage.setItem("shengjian.session", token);
    e.target.reset();
    await enter();
    notice();
  } catch (e) {
    error(e);
  }
});
$("logout").onclick = async () => {
  try {
    await json("/auth/logout", {});
  } finally {
    logoutLocal();
  }
};
document
  .querySelectorAll("nav button")
  .forEach((b) => (b.onclick = () => showPage(b.dataset.page)));
async function refresh() {
  const [me, devices, tasks] = await Promise.all([
    json("/me"),
    json("/devices"),
    json("/tasks"),
  ]);
  $("balance").textContent = `可用 ${me.balance} 积分 · 预留 ${me.reserved}`;
  const selected = $("destination").value;
  $("destination").replaceChildren(new Option("语音对话", "chat"));
  $("device-list").replaceChildren();
  devices.devices
    .filter((d) => !d.revoked)
    .forEach((d) => {
      if (d.grants.includes("tasks"))
        $("destination").add(
          new Option(d.name + (d.online ? " · 在线" : " · 离线"), d.id),
        );
      const card = el("article", undefined, "card");
      card.append(
        el("h2", d.name),
        el("p", d.online ? "在线" : "离线", "muted"),
      );
      const metrics = d.metrics || {};
      const readings = ["cpu_percent", "memory_percent", "disk_percent"]
        .filter((k) => typeof metrics[k] === "number")
        .map(
          (k) =>
            ({
              cpu_percent: "CPU",
              memory_percent: "内存",
              disk_percent: "磁盘",
            })[k] +
            ": " +
            metrics[k].toFixed(1) +
            "%",
        );
      if (readings.length) card.append(el("p", readings.join(" · "), "muted"));
      for (const capability of d.capabilities) {
        const label = el("label", undefined, "inline"),
          check = el("input");
        check.type = "checkbox";
        check.checked = d.grants.includes(capability);
        check.onchange = async () => {
          check.disabled = true;
          try {
            const grants = new Set(d.grants);
            if (check.checked) grants.add(capability);
            else grants.delete(capability);
            await json("/devices/" + d.id, { grants: [...grants] }, "PATCH");
            await refresh();
          } catch (e) {
            check.checked = !check.checked;
            error(e);
          } finally {
            check.disabled = false;
          }
        };
        label.append(
          check,
          document.createTextNode(
            {
              tasks: "执行任务",
              metrics: "状态监控",
              screen: "共享屏幕",
              input: "键鼠控制",
              files: "文件共享",
            }[capability],
          ),
        );
        card.append(label);
      }
      card.append(
        button("撤销设备", async () => {
          await json("/devices/" + d.id, undefined, "DELETE");
          await refresh();
        }),
      );
      $("device-list").append(card);
    });
  if ([...$("destination").options].some((o) => o.value === selected))
    $("destination").value = selected;
  $("task-list").replaceChildren();
  for (const task of tasks.tasks) {
    const b = button(
      (
        (typeof task.specification === "string"
          ? JSON.parse(task.specification)
          : task.specification
        )?.prompt || task.id
      ).slice(0, 56) +
        " · " +
        (labels[task.state] || task.state),
      () => openTask(task.id),
    );
    $("task-list").append(b);
  }
}
$("refresh").onclick = () => refresh().catch(error);
$("enroll").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const name = new FormData(e.target).get("name"),
      d = await json("/devices", { name, capabilities: ["tasks", "metrics"] });
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
async function openTask(id) {
  const epoch = ++taskEpoch;
  if (stream) stream.close();
  currentTask = id;
  cursor = 0;
  showPage("tasks");
  const d = await json("/tasks/" + id);
  $("task-detail").replaceChildren(
    el(
      "h2",
      (typeof d.task.specification === "string"
        ? JSON.parse(d.task.specification)
        : d.task.specification
      )?.prompt || "任务进度",
    ),
    el("p", labels[d.task.state] || d.task.state, "muted"),
    button("取消任务", async () => {
      await json("/tasks/" + id + "/cancel", {});
      notice("已请求取消，等待电脑确认。");
    }),
  );
  function connect() {
    if (currentTask !== id || epoch !== taskEpoch || !token) return;
    stream = new WebSocket(
      location.origin.replace(/^http/, "ws") +
        base +
        "/tasks/" +
        id +
        "/stream",
    );
    stream.onopen = () => stream.send(JSON.stringify({ token, after: cursor }));
    stream.onmessage = (e) => {
      if (epoch !== taskEpoch) return;
      const item = JSON.parse(e.data);
      if (!item.seq || item.seq <= cursor) return;
      cursor = item.seq;
      const event = item.body || item.event || item;
      const text =
        event.text ||
        (event.state ? labels[event.state] || event.state : event.type);
      $("task-detail").append(el("pre", text));
      if (event.type === "task.approval") {
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
        $("task-detail").append(actions);
      }
    };
    stream.onclose = () => {
      if (currentTask === id && epoch === taskEpoch && token)
        setTimeout(connect, 2000);
    };
  }
  connect();
}
function message(role, text) {
  $("messages").append(el("div", text, "message " + role));
  $("messages").scrollTop = $("messages").scrollHeight;
}
$("compose").onsubmit = async (e) => {
  e.preventDefault();
  if (busy) return;
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  busy = true;
  const submit = e.target.querySelector("[type=submit]");
  submit.disabled = true;
  stopSpeech();
  try {
    if ($("destination").value !== "chat") {
      const d = await json("/tasks", {
        device_id: $("destination").value,
        prompt,
        engine: $("engine").value,
        request_id: crypto.randomUUID(),
      });
      $("prompt").value = "";
      await openTask(d.task.id);
      await refresh();
    } else {
      message("user", prompt);
      const models = await json("/models"),
        model = models.data.find((m) => m.input_modalities.includes("text"));
      if (!model) throw new Error("尚未配置对话模型");
      const history = [...messages, { role: "user", content: prompt }].slice(
        -20,
      );
      const r = await api("/model/v1/chat/completions", {
        model: model.id,
        messages: history,
        max_tokens: 2048,
        stream: false,
      });
      const d = await r.json();
      if (d.error) throw new Error("模型响应未完成");
      const text = d.choices?.[0]?.message?.content;
      if (typeof text !== "string") throw new Error("没有收到文字回复");
      messages = [...history, { role: "assistant", content: text }];
      message("assistant", text);
      $("prompt").value = "";
      if ($("speak").checked) await speak(text);
    }
    await refresh();
  } catch (e) {
    error(e);
  } finally {
    busy = false;
    submit.disabled = false;
  }
};
let speechEpoch = 0;
function stopSpeech() {
  speechEpoch++;
  if (playback) {
    playback.pause();
    URL.revokeObjectURL(playback.src);
    playback = null;
  }
}
async function speak(text) {
  const epoch = ++speechEpoch;
  const r = await api("/voice/speech", {
    input: text.slice(0, 1000),
    request_id: crypto.randomUUID(),
  });
  const blob = await r.blob();
  if (epoch !== speechEpoch) return;
  playback = new Audio(URL.createObjectURL(blob));
  playback.onended = () => stopSpeech();
  try {
    await playback.play();
  } catch {
    notice(
      "点击停止播报旁的录音按钮可继续对话；浏览器可能需要先允许播放声音。",
    );
  }
}
$("stop-speech").onclick = stopSpeech;
async function stopCapture(finish = true) {
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
  $("record").textContent = "开始录音";
}
$("record").onclick = async () => {
  if (capture) {
    await stopCapture();
    return;
  }
  stopSpeech();
  let c = {};
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
    c.ws.onopen = () =>
      c.ws.send(JSON.stringify({ token, request_id: crypto.randomUUID() }));
    c.ws.onmessage = async (e) => {
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
          $("record").textContent = "结束录音";
          c.timer = setTimeout(() => stopCapture().catch(error), 29000);
          notice("正在录音，说完后点击结束录音。");
        }
        if (event.type === "asr.finished") c.ws.close();
      } catch (e) {
        error(e);
        await stopCapture(false);
        c.ws.close();
      }
    };
    c.ws.onclose = () => {
      if (capture === c) stopCapture(false).catch(error);
    };
  } catch (e) {
    error(e);
    await stopCapture(false);
  }
};
if (token) enter().catch(error);
