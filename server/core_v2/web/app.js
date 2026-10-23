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
  live = null,
  busy = false,
  messages = [],
  taskEpoch = 0,
  composeEpoch = 0,
  replyController = null,
  voiceController = null;
let authEpoch = 0;
let agentMode = false, computerDevices = [];
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
  qr_expired: "二维码已使用或已过期，请在电脑上刷新后重新扫描。",
};
function error(e) {
  const text = e.message || String(e);
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
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
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
function showPage(id) {
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== id));
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("selected", b.dataset.page === id));
}
function logoutLocal() {
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
  $("agent-mode").setAttribute("aria-pressed", "false");
  sessionStorage.removeItem("shengjian.session");
  if (stream) stream.close();
  clearInterval(refreshTimer);
  stopLive();
  stopCapture(false);
  stopSpeech();
  $("auth").hidden = false;
  $("workspace").hidden = true;
  $("logout").hidden = true;
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
  $("auth").hidden = true;
  $("workspace").hidden = false;
  $("logout").hidden = false;
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => refresh().catch(error), 10000);
}
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const operation = ++authEpoch;
  try {
    const form = new FormData(e.target),
      action = e.submitter.value;
    const body = {
      username: form.get("username"),
      password: form.get("password"),
    };
    if (action === "register") body.invite = form.get("invite");
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
  }
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
  $("balance").textContent = `可用 ${me.balance} 积分 · 预留 ${me.reserved}`;
  computerDevices = devices.devices.filter(d => !d.revoked && d.grants.includes("tasks"));
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
  if (live && $("destination").value !== live.destination)
    stopLive("目标设备已不可用，实时对话已暂停");
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
async function openTask(id, { reveal = true, conversation = false } = {}) {
  const epoch = ++taskEpoch;
  if (stream) stream.close();
  currentTask = id;
  cursor = 0;
  if (reveal) showPage("tasks");
  const d = await json("/tasks/" + id);
  if (epoch !== taskEpoch || !token) return;
  const terminal = new Set(["succeeded", "failed", "cancelled", "unknown"]);
  const stateLine = el("p", labels[d.task.state] || d.task.state, "muted");
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
  let resultText = "",
    spoken = false;
  const reports = new Set();
  const approvals = new Map();
  function connect() {
    if (currentTask !== id || epoch !== taskEpoch || !token) return;
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
      const text =
        event.text ||
        (event.state ? labels[event.state] || event.state : event.type);
      if (event.type === "task.state") {
        stateLine.textContent = labels[event.state] || event.state;
        if (terminal.has(event.state)) {
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
          else if ($("speak").checked) speak(resultText).catch(error);
        }
      } else $("task-detail").append(el("pre", text));
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
  if (live) stopLive();
  agentMode = !agentMode;
  if (agentMode) {
    const selected = computerDevices.find(d => d.id === $("destination").value) || computerDevices.find(d => d.online);
    if (selected) $("destination").value = selected.id;
    else notice("请在电脑声笺的“电脑 Agent”页启用 DeepSeek Harness，再回来刷新。");
  } else $("destination").value = "chat";
  $("agent-mode").setAttribute("aria-pressed", String(agentMode));
  $("voice-note").textContent = agentMode ? "直接说出电脑任务；可说“汇报进度”“取消当前任务”“查看电脑状态”。停止播报不会取消任务。" : "开启实时对话即可连续交谈，随时开口打断。也可说“让电脑帮我…”派任务。";
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
  const owner = token,
    operation = ++composeEpoch;
  busy = true;
  notice();
  const submit = $("compose").querySelector("[type=submit]");
  submit.disabled = true;
  stopSpeech();
  try {
    const selected = $("destination").value;
    if ((live || agentMode || selected === "chat") && ShengjianAgent.shouldRoute(prompt, agentMode || selected !== "chat", currentTask)) {
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
      const d = await json("/tasks", {
        device_id: $("destination").value,
        prompt,
        engine: $("engine").value,
        request_id: crypto.randomUUID(),
      });
      if (owner !== token || operation !== composeEpoch) return;
      $("prompt").value = "";
      await openTask(d.task.id);
      if (owner === token && operation === composeEpoch) await refresh();
    } else {
      message("user", prompt);
      const models = live?.models || (await json("/models")),
        model = models.data.find((m) => m.input_modalities.includes("text"));
      if (owner !== token || operation !== composeEpoch) return;
      if (!model) throw new Error("尚未配置对话模型");
      const history = [...messages, { role: "user", content: prompt }].slice(
        -20,
      );
      if (live?.capabilities?.streaming_audio) {
        await streamChat(history, model.id, owner, operation);
        return;
      }
      const r = await api("/model/v1/chat/completions", {
        model: model.id,
        messages:
          live && $("destination").value === "chat"
            ? [
                {
                  role: "system",
                  content:
                    "你正在进行中文实时语音对话。回答自然、简短，通常两三句话；除非用户要求详细解释，不要列长清单。",
                },
                ...history,
              ]
            : history,
        max_tokens: live ? 512 : 2048,
        stream: false,
      });
      const d = await r.json();
      if (owner !== token || operation !== composeEpoch) return;
      if (d.error) throw new Error("模型响应未完成");
      const text = d.choices?.[0]?.message?.content;
      if (typeof text !== "string") throw new Error("没有收到文字回复");
      messages = [...history, { role: "assistant", content: text }];
      message("assistant", text);
      if (owner !== token || operation !== composeEpoch) return;
      $("prompt").value = "";
      if ($("speak").checked) await speak(text);
    }
    if (owner === token && operation === composeEpoch) await refresh();
  } catch (e) {
    if (owner === token && operation === composeEpoch) {
      if (live) stopLive("对话请求未完成，请确认后重新开启");
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
async function speak(text) {
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
    const context = live?.context;
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
      liveState("正在播报 · 开口即可打断");
    }
  });
  player.echo = session.echo || null;
  if (turn) turn.player = player;
  // Register before the first audio arrives so pending synthesis can also be stopped.
  playback = player;
  let chain = Promise.resolve(),
    failure = null;
  const sentences = new VoiceSentences((text) => {
    chain = chain
      .then(async () => {
        if (epoch === speechEpoch) await streamAudio(text, epoch, player);
      })
      .catch((e) => {
        if (epoch === speechEpoch) {
          failure = e;
          replyController?.abort();
        }
      });
  });
  player.onStop = () => sentences.cancel();
  return {
    push: (text) => sentences.push(text),
    async done() {
      sentences.flush();
      await chain;
      if (failure) throw failure;
      if (epoch === speechEpoch) await player.drain();
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
async function streamChat(history, model, owner, operation) {
  const controller = new AbortController();
  replyController = controller;
  const session = live;
  session.replyStart = performance.now();
  const turn = {
    history,
    text: "",
    voiced: $("speak").checked,
    complete: false,
    speechEnd: session.utterance?.speechEnd,
  };
  session.replyTurn = turn;
  const speech = turn.voiced ? speechPipeline(turn) : null;
  const node = el("div", "", "message assistant");
  $("messages").append(node);
  turn.node = node;
  let text = "",
    complete = false;
  messages = history;
  try {
    const response = await api(
      "/model/v1/chat/completions",
      {
        model,
        messages: [
          {
            role: "system",
            content:
              "你正在进行中文实时语音对话。回答自然简短，通常两三句话，先直接回答。避免 Markdown 和长列表。",
          },
          ...history,
        ],
        max_tokens: 512,
        reasoning_effort: session.capabilities.reasoning_effort || undefined,
        stream: true,
      },
      "POST",
      { signal: controller.signal },
    );
    await readEvents(
      response,
      "sse",
      (event) => {
        if (owner !== token || operation !== composeEpoch) return;
        if (event.error) throw new Error("model_result_unknown");
        if (event.done) {
          complete = true;
          return;
        }
        const delta = event.choices?.[0]?.delta?.content;
        if (typeof delta !== "string" || !delta) return;
        if (!text)
          session.metrics = {
            ...session.metrics,
            first_token_ms: Math.round(performance.now() - session.replyStart),
          };
        text += delta;
        turn.text = text;
        node.textContent = text;
        messages = [...history, { role: "assistant", content: text }];
        $("messages").scrollTop = $("messages").scrollHeight;
        speech?.push(delta);
      },
      controller.signal,
    );
    if (owner !== token || operation !== composeEpoch) return;
    if (!complete || !text) throw new Error("model_result_unknown");
    $("prompt").value = "";
    await speech?.done();
    turn.complete = true;
    if (owner === token && operation === composeEpoch) await refresh();
  } finally {
    if (replyController === controller) replyController = null;
  }
}
function stopAgentSpeech() { reportEpoch++; stopSpeech(); }
$("stop-speech").onclick = stopAgentSpeech;
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
  stopLive();
  if (capture) {
    await stopCapture();
    return;
  }
  stopSpeech();
  let c = { owner: token };
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
      if (c.owner !== token) {
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
function liveState(text) {
  $("live-state").textContent = text;
}
function interruptReply(session = live) {
  reportEpoch++;
  const turn = session?.replyTurn;
  if (turn && !turn.complete && !turn.interrupted) {
    turn.interrupted = true;
    const heard = turn.voiced ? turn.player?.heard() || "" : turn.text;
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
  if ($("destination").value === "chat") {
    composeEpoch++;
    busy = false;
    $("compose").querySelector("[type=submit]").disabled = false;
  }
}
function stopLive(reason = "实时对话已结束") {
  const session = live;
  live = null;
  if (session) {
    session.closed = true;
    clearTimeout(session.timeout);
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
    if (session.owner === token && session.destination === "chat")
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
    previous.ws?.close();
  }
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
  if (continuing) {
    clearTimeout(session.timeout);
    session.timeout = setTimeout(
      () => liveFailure(session, new Error("voice_connection_ended")),
      1800,
    );
    liveState("正在听，请继续说…");
    return;
  }
  openLiveASR(session, utterance);
}
function openLiveASR(session, utterance) {
  if (live !== session || session.utterance !== utterance) return;
  liveState("正在听，停顿后自动发送…");
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
    if (session.capabilities?.early_audio) {
      const pending = utterance.pending;
      utterance.pending = [];
      for (const chunk of pending) sendLivePCM(session, chunk, utterance);
      if (utterance.ended) finishLivePCM(session, utterance);
    }
  };
  socket.onmessage = async (event) => {
    if (
      live !== session ||
      (session.utterance !== utterance && session.waitingFor !== utterance) ||
      session.owner !== token
    )
      return;
    try {
      const reply = JSON.parse(event.data);
      if (reply.type === "error") throw new Error(reply.error);
      if (reply.type === "asr.ready") {
        utterance.ready = true;
        for (const chunk of utterance.pending)
          sendLivePCM(session, chunk, utterance);
        utterance.pending = [];
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
          await submitPrompt(text);
        }
        if (live === session && session.utterance === utterance) {
          session.processing = false;
          // The detector may already hold the next speaker's onset. Do not reset it here.
          liveState("正在聆听，请继续说…");
        }
      }
    } catch (failure) {
      liveFailure(session, failure);
    }
  };
  socket.onerror = () => {
    if (
      (session.utterance === utterance || session.waitingFor === utterance) &&
      !utterance.abandoned
    )
      liveFailure(session, new Error("voice_connection_ended"));
  };
  socket.onclose = () => {
    session.sockets?.delete(socket);
    if (
      !utterance.final &&
      !utterance.abandoned &&
      (session.utterance === utterance || session.waitingFor === utterance)
    )
      liveFailure(session, new Error("voice_connection_ended"));
  };
}
function finishLivePCM(session, u = session.utterance) {
  if (
    live !== session ||
    u.finishSent ||
    !u.ws ||
    u.ws.readyState !== WebSocket.OPEN
  )
    return;
  if (u.ready || (session.capabilities?.early_audio && u.authSent)) {
    u.finishSent = true;
    u.ws.send(JSON.stringify({ type: "finish" }));
  }
}
function sendLivePCM(session, pcm, u = session.utterance) {
  if (live !== session) return;
  if (!u.ready && !(session.capabilities?.early_audio && u.authSent)) {
    u.pending.push(pcm.slice());
    if (u.pending.reduce((n, chunk) => n + chunk.length, 0) > 28000)
      liveFailure(session, new Error("识别衔接等待过久，请检查网络后重试。"));
    return;
  }
  if (!u.ready) {
    u.earlySamples = (u.earlySamples || 0) + pcm.length;
    if (u.earlySamples > 28000)
      return liveFailure(
        session,
        new Error("语音连接建立过慢，请检查网络后重试。"),
      );
  }
  if (u.ws.readyState !== WebSocket.OPEN || u.ws.bufferedAmount > 128000)
    return liveFailure(session, new Error("网络发送较慢，请检查连接后重试。"));
  for (let i = 0; i < pcm.length; i += 3200)
    u.ws.send(pcm.slice(i, i + 3200).buffer);
}
$("realtime").onclick = async () => {
  if (live) return stopLive();
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
    const resumed = session.context.resume();
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
    session.context.onstatechange = () => {
      if (session.context.state === "suspended")
        liveFailure(
          session,
          new Error("音频已被系统暂停，请返回页面重新开启。"),
        );
    };
    liveState(
      session.capabilities.partial_results
        ? "正在聆听 · 实时识别，可随时打断"
        : "正在聆听，请直接说…",
    );
  } catch (failure) {
    liveFailure(session, failure);
  }
};
window.addEventListener("offline", () =>
  stopLive("网络已断开，重连后请重新开启实时对话"),
);
document.addEventListener("visibilitychange", () => {
  if (document.hidden)
    stopLive("已暂停麦克风，返回后请重新开启实时对话。电脑任务继续运行。");
});
window.addEventListener("pagehide", () => stopLive());
async function restoreLogin() {
  const ticket = new URLSearchParams(location.hash.slice(1)).get("login");
  if (ticket) history.replaceState(null, "", location.pathname + location.search);
  if (ticket && token) logoutLocal();
  const operation = ++authEpoch;
  try {
    if (ticket) {
      const data = await json("/auth/qr/redeem", { ticket });
      if (operation !== authEpoch) return;
      token = data.token;
      sessionStorage.removeItem("shengjian.session");
    } else if (!token) {
      const data = await json("/auth/session", {});
      if (operation !== authEpoch) return;
      if (data.authenticated) token = data.token;
    }
    if (token) await enter();
  } catch (failure) { if (operation === authEpoch) error(failure); }
}
window.addEventListener("hashchange", restoreLogin);
restoreLogin();
