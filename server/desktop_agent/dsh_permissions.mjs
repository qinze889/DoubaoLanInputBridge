// An explicit device-owner setting, applied through DSH's durable preset API.
export const name = 'shengjian-permissions';
export const inject = ['permissionPresets', 'sessions'];
export function apply(ctx, config) {
  if (!['workspace-write', 'danger-full-access'].includes(config.mode)) throw new Error('invalid_permission_mode');
  const applyMode = session => ctx.permissionPresets.set(session, config.mode);
  ctx.on('session/created', applyMode);
  for (const session of ctx.sessions.list()) applyMode(session);
}
