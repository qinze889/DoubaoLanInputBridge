(function (root) {
  const normalize = text => text.toLowerCase().replace(/[\s，。！？,.!?、：:]/g, "");
  function silence(text) { return /^(?:请)?(?:停一下|停止播报|停止说话|别说了|暂停播报)$/.test(normalize(text)); }
  function control(text) {
    return /^(?:请|帮我|麻烦)?(?:(?:取消|停止|终止)(?:当前|这个|刚才的|正在执行的)?(?:电脑)?任务|(?:查看|查询|汇报|报告|说一下)?(?:当前|这个|刚才的|现在的)?任务(?:进度|状态|结果|怎么样了|做到哪了|完成了吗|做完了吗)|进度怎么样了|现在进度怎么样了?|进度如何|做到哪里了|现在做到哪了|做到哪了|做完了吗|当前进度|汇报进度|汇报结果|取消刚才的任务|取消这个工作|查看电脑状态|电脑状态|电脑运行情况|电脑负载|电脑怎么样了|允许本次操作|允许这次操作|批准本次操作|拒绝本次操作|拒绝这次操作|不允许本次操作)$/.test(normalize(text));
  }
  function shouldRoute(text, selected, task) {
    if (selected) return true;
    const value = normalize(text);
    if (/^(?:请|麻烦)?(?:让电脑|用电脑|电脑帮我|让agent|用agent|让harness|用harness|帮我在电脑)/.test(value)) return true;
    if (/^(?:请|帮我)?(?:查看电脑状态|电脑状态|电脑运行情况|电脑负载|电脑怎么样了)$/.test(value)) return true;
    if (task && /^(?:请|帮我|麻烦)?(?:(?:取消|停止|终止)(?:当前|这个|刚才的|正在执行的)?(?:电脑)?任务|(?:查看|查询|汇报|报告|说一下)?(?:当前|这个|刚才的|现在的)?任务(?:进度|状态|结果|怎么样了|做到哪了|完成了吗|做完了吗)|进度怎么样了|做到哪了|做完了吗|当前进度|汇报进度|汇报结果|允许本次操作|允许这次操作|批准本次操作|拒绝本次操作|拒绝这次操作|不允许本次操作)$/.test(value)) return true;
    return Boolean(task && /^(?:请)?(?:继续|接着|再|改成|改为|补充|把刚才|在刚才)/.test(value));
  }
  const api = { shouldRoute, silence, control };
  if (typeof module !== "undefined") module.exports = api;
  root.ShengjianAgent = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
