# Progress

Last updated: 2026-04-17

## Active Goal
- 收口当前 paper queue，先修正确性与可维护性，再继续做内容质量迭代。
- 所有完成态论文必须满足 metadata 强约束：`title / authors / institution / venue / framework_version`。
- 队列主界面改为版本驱动：主列表展示 `Paper / Version / Status / Topic / Actions`，不再展示提交日期。

## Current Facts
- `job 37` 仍在运行，当前阶段是 `research`；在它结束前不做会影响运行样本判断的 destructive cleanup。
- 旧 `PROGRESS.md` 已经过期，至少有三处不再准确：
  - `STELLAR` 已完成
  - 新坏样本出现：`Untitled Paper`、`(Available in the text)`、以及串题样本 `MegaScale-Infer-v2`
  - 前端仍然是同步提交并会跳详情页
- Prompt 设计主入口：
  - metadata prompt: `paper_queue/workflow.py::_query_metadata`
  - note prompt: `paper_queue/workflow.py::_query_notes`

## Interleaved Todo
- [x] Implement 0: 补一份设计文档，明确 paper queue 的 lifecycle、prompt 边界、关键词规则与目标 prompt 拆分方案。
- [x] Implement 1: 为 job 模型增加 `framework_version / canonical_paper_key / source_fingerprint / metadata_complete` 的持久化字段。
- [x] Implement 2: 主列表改为 `Paper / Version / Status / Topic / Actions`，不再显示提交日期。
- [x] Implement 3: Actions 改为 icon-only 按钮，使用内联 SVG 表达 `info / retry / delete`。
- [x] Implement 4: 首页提交改为异步，点击后立即出现本地 `submitting` 项，不跳详情页。
- [x] Implement 5: completed-retry 语义扩展为“非最新版 completed 允许重试并生成新 job”。
- [x] Implement 6: 生成链 frontmatter 写入 `framework_version` 与 `canonical_paper_key`。
- [x] Implement 7: 新输出路径切换到 `paper/_assets/<topic>/<note-stem>/...`。
- [x] Implement 8: metadata query 增强，并加 HTML citation fallback。
- [x] Implement 9: metadata gate 启用；缺 `title / authors / institution / venue` 不再允许完成落盘。
- [ ] Evaluate 1: 回归现有坏样本，确认不再生成 `Untitled Paper`、`(Available in the text)`、串题结果。
- [ ] Evaluate 2: 回归异步提交，确认页面立即出现 `submitting` 且不跳详情页。
- [ ] Evaluate 3: 回归 completed-retry，确认仅非最新版 completed 显示 retry。
- [ ] Implement 10: 清理旧版本 note，只保留最新版，并同步清掉旧 assets。
- [ ] Implement 11: 清理仓库内 `xiaoba-skills/`，不再保留外部参考 skill 副本。
- [ ] Implement 12: 迁移旧 assets 到 `paper/_assets/...` 并修复旧文档相对路径。
- [ ] Implement 13: 增加独立 configuration file，把 agent 接口与运行参数配置化，而不是把 `claude-glm` 和相关调用参数硬编码在 runtime/workflow 中。
- [ ] Evaluate 4: 跑一次 repo cleanup 后的 Git 状态与前端展示，确认没有悬空文件和错链。

## Queued Review Fixes
- [ ] 图片样式：
  - 不再写 `来源:`
  - 优先使用居中 caption 放图下
- [ ] 可读性 review：
  - workflow 最后增加 markdown -> PDF 可读性检查
  - 用 `claude-glm` 临时审读渲染后的 PDF
- [ ] 图文交错：
  - 避免同一段开头连续堆多张图
  - 优先按原文叙事顺序交错插入
- [ ] 章节长度动态分配：
  - 保持 6 个主标题
  - 先分析 paper structure，再决定各段 short / medium / long
- [ ] 作者原文与个人启发分离：
  - limitations / risks / future work 保留作者口径
  - personal takeaways 单独呈现
- [ ] venue / filename 规则：
  - 正式 venue 优先于 arXiv
  - 例如 `2026-ICLR-OpenAgentSafety`
- [ ] institution 展示：
  - 默认第一机构
  - 并列主机构或关键企业合作时保留多项

## Version Log

| Framework Version | Change Summary | Status |
| --- | --- | --- |
| 0.1.0 | 初始 Git-only queue、taxonomy routing、figure extraction、benchmark evaluator | historical |
| 0.1.1 | job versioning fields、async submit、icon actions、completed-retry、metadata gate、new assets root | active |

## Open Blockers
- `job 37` 结束前，不做旧版本 note / assets 的 destructive 清理。
- 旧坏样本已经存在于队列和 Obsidian repo 中，仍需在 cleanup 阶段统一处理。
- 当前 prompt 仍然直接嵌在 `paper_queue/workflow.py`；本轮先补 design doc，后续再按文档把 prompt 全量拆出到独立文件。
- 当前 agent 调用仍以 `claude-glm` 为默认硬编码路径；后续需要通过 configuration file 控制 agent command、prompt set、timeouts、feature flags 等参数。
