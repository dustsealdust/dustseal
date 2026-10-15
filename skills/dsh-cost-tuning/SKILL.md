---
name: dsh-cost-tuning
description: DeepSeek Harness 桌面版降本与性能调优经验：推理强度落点、desktop profile 手工装插件的 pnpm 硬性前缀、插件挂载验证、慢 turn 取证、DSH_HOME 迁移教训。
---

# DSH 降本与调优

适用：DeepSeek Harness 桌面版（Cordis loader + profile bundles）。目标是把成本压下去、把故障定位时间压下去。

## 0. 两条红线

- 改 DSH profile / 系统提示词 / preset 这类配置，优先走 GUI；不要用 shell 硬凑，信息不足就停下交回用户。
- 改 `cordis.patch.yml` 不等于改系统提示词。该文件只是 loader 补丁数组，**不含提示词文本**。「加人设」要动的是 agent preset 那一层。

## 1. 降本：推理强度固定到 low

在 `cordis.patch.yml` 三处一起压，避免任何一条 route 漏掉：

- `agent-default-model`: 顶层 `reasoningEffort: low`
- `llm-deepseek`: 顶层 `reasoningEffort: low`，并按模型列 `reasoningEfforts`
- `llm-pi-ai`: 每条 route 加 `reasoning: low`，各模型列 `reasoningEfforts`

改前留备份（如 `.bak-before-low` / `.bak-before-piai`），回滚就是换回备份。

## 2. desktop profile 手工 pnpm 装插件

profile 由 App 插件管理器/GUI 市场独占：外部 `@deepseek-ai/dsh` CLI 会拒绝管理 desktop profile，市场安装会整份重写 `package.json` 的 `dsh.profile.bundles` 与 `pnpm-lock.yaml`。所以要手工装时，命令必须带两个前缀：

```
pnpm add <pkg> \
  --store-dir <本机 pnpm store 绝对路径> \
  --virtual-store-dir <profile>\node_modules\.pnpm \
  --config.minimumReleaseAge=0
```

- 缺 store / virtual-store 前缀会报 `ERR_PNPM_UNEXPECTED_STORE` / `UNEXPECTED_VIRTUAL_STORE`（`node_modules` 里记录的还是旧路径）。
- `--config.minimumReleaseAge=0` 用于绕开锁文件里 24h 新鲜度封锁，`pnpm-workspace.yaml` 的 `minimumReleaseAgeExclude` 压不住它。
- 装完要同时写进 `dependencies` 和 `dsh.profile.bundles`。

## 3. 验证插件真的挂载了

**不要用 HTTP 状态码判断**：DSH 对任何 `/api/*` 都返回 401 `unauthorized`（通用鉴权，没带 token 探测不出来）。

可靠办法：改完 `bundles` 后看 `$DSH_HOME/storages/<插件单元>.json` 是否被新建/刷新，落盘时间即挂载时间。改 bundles 会触发自动重组合，无需重启。

## 4. 慢 turn 取证

会话日志：`$DSH_HOME/sessions/<cwd-slug>/<session-id>/session.v4.jsonl.zstd`，是**多帧 zstd**。先解 header 拿到第一帧长度，再循环顺移：

```js
let off = 0;
while (off < buf.length) {
  const r = zlib.zstdDecompressSync(buf.subarray(off), { info: true });
  off += r.engine.bytesWritten; // 一次性调用只会解出 ~185 字节 header
}
```

事件类型：`session` / `turn/start` / `step/start` / `step/end` / `tool/call` / `tool/result` / `assistant/message` / `turn/end`，均带 `time`(ms epoch)。可逐 step 计时、列工具名与命令，`turn/end` 的 `reason.kind` 给出终止原因（如 `aborted`）。

结论模板：一次被中止的 177s turn = 33 步 / 42 次 pwsh（每次 3–14s 串行），最大相邻事件间隔仅 11.6s —— 慢是「N 次串行小往返」叠加，不是一次长思考。**先测再下结论。**

## 5. DSH_HOME 迁移与磁盘

- 系统盘常年吃紧会直接导致 DSH 工具 `ENOSPC` 失败。把 `$DSH_HOME` 迁到数据盘，原路径留 Junction（`mklink /J` 不需要管理员）。
- 迁移后校验三件事：文件数一致、写入穿透正常、DSH 进程仍按原路径读 profile。
- **教训**：清理 DSH 数据要直接删数据盘上的真身目录，不要经 Junction 路径删。
- 手工 pnpm 的前缀路径要跟着 `DSH_HOME` 迁移一起核对。

## 6. 凭据与环境常识

- 模型走订阅时，凭据库里可能没有 `DEEPSEEK_API_KEY`（只有账号登录态），余额类插件会显示本地备用值，这是预期，不要提议补 key。
- 归档会话后「上下文洞察」里 token 记录消失是正常预期，不需刨源码排查。
