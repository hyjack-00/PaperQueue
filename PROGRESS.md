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
- 你提供了本地 SwiftScholar 参考 PDF：
  - `/workspace/paper_reading/benchmarks/swiftscholar_pdfs`
  - 当前包含 `Autopoiesis / STELLAR / OpenAgentSafety / MegaScale-Infer / Agents of Chaos`
  - 这批 PDF 现在应视为“本地参考基准资产”，优先于在线抓取页面；后续结构、篇幅、图文顺序和图片数量对比都应基于这批本地 PDF。

## Interleaved Todo
- [x] Implement 15: 新开独立 worktree 分支 `eval-system`，在隔离工作区实现复杂评估系统，不污染当前主工作区。
- [x] Implement 16: 新增复杂评估系统设计文档，明确原文 PDF 检查点、图表公式放置、篇幅分布、多轮 self-review 的持久化方案。
- [x] Implement 17: 新增评估配置层和 4 类 benchmark prompts，分别覆盖段落信息点抽取、coverage review、placement review、length review。
- [x] Implement 18: 新增 `paper_queue/evaluation.py`、`scripts/build_complex_benchmark_assets.py`、`scripts/evaluate_complex_benchmark.py`，替换旧的简单关键词评估思路。
- [x] Implement 19: 新增 SwiftScholar 页面快照和结构对比脚本，后续差异评估不再只看生成结果自身，而是显式对比参考页面结构。
- [x] Implement 20: 将 `/workspace/paper_reading/benchmarks/swiftscholar_pdfs` 纳入评估输入资产规划，作为 SwiftScholar 本地快照来源。
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
- [x] Evaluate 1: 回归现有坏样本，确认不再生成 `Untitled Paper`、`(Available in the text)`、串题结果。
- [x] Evaluate 2: 回归异步提交，确认页面立即出现 `submitting` 且不跳详情页。
- [x] Evaluate 3: 回归 completed-retry，确认仅非最新版 completed 显示 retry。
- [x] Implement 10: 清理旧版本 note，只保留最新版，并同步清掉旧 assets。
- [x] Implement 11: 清理仓库内 `xiaoba-skills/`，不再保留外部参考 skill 副本。
- [x] Implement 12: 迁移旧 assets 到 `paper/_assets/...` 并修复旧文档相对路径。
- [x] Implement 13: 增加独立 configuration file，把 agent 接口与运行参数配置化，而不是把 `claude-glm` 和相关调用参数硬编码在 runtime/workflow 中。
- [x] Implement 14: 在 note generation 之前增加 structure analysis 步骤，用独立 prompt 判断各章节 short / medium / long。
- [ ] Evaluate 4: 跑一次 repo cleanup 后的 Git 状态与前端展示，确认没有悬空文件和错链。
- [ ] Evaluate 5: 至少对 `Autopoiesis` 跑通一轮复杂 benchmark asset 构建，确认能产出原文段落信息点、引用资产、章节统计。
- [ ] Evaluate 6: 至少对 1 篇 note 跑通 coverage / placement / length 三轮 self-review，并落盘到 `benchmarks/assets/<paper_id>/evaluation/latest.json`。
- [x] Evaluate 6: 已对 `Autopoiesis` 跑通 baseline coverage / placement / length 三轮评估，并落盘到 `benchmarks/assets/autopoiesis/evaluation/latest.json`。
  - 当前 baseline 分数：
    - coverage_ratio = `0.62`
    - placement_ratio = `0.182`
    - interleaving_ratio = `0.782`
    - distribution_ratio = `0.143`
  - 结论：当前生成结果并非“完全没覆盖”，但方法/结果段仍然压缩过强，图位合理性和篇幅分布仍明显弱于目标。
- [ ] Evaluate 7: 对至少 1 篇 benchmark 同时产出 `swiftscholar_snapshot.json`，并生成“SwiftScholar vs 当前 note”的区分性差异报告。
- [ ] Evaluate 8: 接入 `benchmarks/swiftscholar_pdfs` 后，对 5 篇论文分别提取 SwiftScholar PDF 的标题层级、图片数量、图文顺序、章节篇幅统计，并生成与当前 note 的差异报告。
- [ ] Evaluate 8: 接入 `benchmarks/swiftscholar_pdfs` 后，对 5 篇论文分别提取 SwiftScholar PDF 的标题层级、图片数量、图文顺序、章节篇幅统计，并生成与当前 note 的差异报告。
  - 当前 `Autopoiesis` 已经能生成本地 `swiftscholar_snapshot.json`
  - 当前 `Autopoiesis` 的第一版差异结果：
    - major headings: SwiftScholar 7 vs current note 8
    - fine headings: SwiftScholar 45
    - images: SwiftScholar 6 vs current note 6
    - paragraphs/blocks: SwiftScholar 291 vs current note 15
  - 这说明当前主差异已经从“图片缺失”转移到“内容压缩过强、细粒度结构缺失”
- [ ] Implement 21: 用 `Autopoiesis` baseline 评估结果反推主流程改进项，优先处理：
- [ ] Implement 21: 用 `Autopoiesis` baseline 评估结果反推主流程改进项，优先处理：
  - coverage 缺口最大的背景/问题定义/workflow 细节
  - placement_ratio 偏低的 figure section 对位
  - distribution_ratio 偏低的方法/结果篇幅不足
  - 已开始：`notes_v1.txt` 增加强制要求，要求背景/方法/实验/结果保留更多原文细节，不再只保留高层摘要

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
- [x] 章节长度动态分配：
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
| 0.1.1 | prompt registry (`paper_queue/prompts/`) + config file (`paper_queue/config/defaults.json`) + agent backend config 化 | active |
| 0.1.1 | `structure_analysis_v1` 接入运行链，用结构分析结果控制 notes prompt 的章节篇幅提示 | active |

## Open Blockers
- 复杂评估系统刚进入独立 worktree 分支，尚未跑完整 benchmark；当前只是代码和数据模型已落地。
- `benchmarks/swiftscholar_pdfs` 当前位于主工作区 `/workspace/paper_reading`，还没有接入 `eval-system` worktree 的脚本路径；下一步需要把它纳入配置或做显式引用，不能再依赖被 403 拦住的在线页面抓取。
- `benchmarks/swiftscholar_pdfs` 已通过配置接入 `eval-system`，不再依赖在线页面抓取；当前 blocker 已转为“如何把 SwiftScholar PDF 的细粒度结构转成合理比较口径”，而不是资源不可得。
- `job 37` 已失败，不再阻塞 destructive cleanup。
- metadata prompt 和 note prompt 已拆到 `paper_queue/prompts/`；readability-review 仍未接入运行链。
- structure-analysis 已接入运行链；readability-review 仍未接入运行链。
- agent backend 已通过 `paper_queue/config/defaults.json` 配置化，当前默认 backend 仍是 `claude-glm`。
- 已验证前端主列表不再显示 `Date`，改为 `Version`；`info / retry / delete` 已切成 icon-only。
- 已验证 completed-retry 只对旧版本完成项出现，最新版完成项不显示 retry。
- 已验证 assets 目录已经统一收口到 `paper/_assets/`，旧的 `paper/<topic>/_assets` 不再存在。
- 已回归坏样本：
  - `job 40` 不再落出 `Untitled Paper` 文档，失败于 metadata gate
  - `job 41` 不再把 `CUDA Agent` 串成新的 `MegaScale-Infer` 产物，失败于 metadata gate
  - `job 42` 没有再写出 `(Available in the text)` 文档
- 已完成 Obsidian 仓库 cleanup：
  - 删除 `2026-arXiv-Untitled-Paper.md`
  - 删除 `2026-arXiv-Available-in-the-text.md`
  - 删除 `2025-arXiv-MegaScale-Infer-v2.md`
  - 删除旧版 `2026-arXiv-Autopoiesis.md`
  - 对应旧 assets 已同步删除
