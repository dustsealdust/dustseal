# dsh-cost-tuning

DeepSeek Harness 桌面版的降本与调优经验包：推理强度落点、desktop profile 手工 pnpm 装插件的硬性前缀、
插件挂载验证、慢 turn 取证、DSH_HOME 迁移教训。

使用方式：把 `skills/dsh-cost-tuning/` 放进你的 skills 目录，或在 Agent 里按需引用 `SKILL.md`。

## 内容边界

- 只记录可复用的机制与教训，不含本机绝对路径、账号、token 等敏感信息。
- 涉及 profile / preset 的配置改动，请在 GUI 完成；本包不提供脚本代改。
