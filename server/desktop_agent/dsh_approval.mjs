/** Own integration plugin; upstream DSH exposes the approval/request waterfall. */
export const name = "shengjian-approval";
export const inject = ["approval"];
export function apply(ctx) {
  const calls = new Map();
  ctx.on("session/event", (session, event) => {
    if (event.type !== "tool/call") return;
    calls.set(event.data.callId, {
      tool: event.data.name,
      arguments: String(event.data.arguments).slice(0, 12000),
    });
    if (calls.size > 128) calls.delete(calls.keys().next().value);
  });
  ctx.on("approval/request", async (req, next) => {
    const endpoint = process.env.SHENGJIAN_APPROVAL_URL,
      token = process.env.SHENGJIAN_APPROVAL_TOKEN;
    if (!endpoint || !token) return next();
    try {
      const preview = calls.get(req.callId);
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tool: req.toolName,
          reason: req.reason || "",
          preview: preview || null,
        }),
        signal: req.signal,
      });
      if (!response.ok) return "unavailable";
      const decision = await response.json();
      return decision.allow === true ? "allowed-once" : "rejected";
    } catch {
      return req.signal?.aborted ? "cancelled" : "unavailable";
    }
  });
}
