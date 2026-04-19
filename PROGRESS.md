# Progress

Last updated: 2026-04-18

## Current Test
- Job 45: `Agents of Chaos` (arXiv 2602.20021) — 端到端验证改进后的 prompt + figure rendering
- 目标：coverage ≥ 0.8, figure_match ≥ 0.8

## Active Goal
- 收口当前 paper queue，先修正确性与可维护性，再继续做内容质量迭代。
- 所有完成态论文必须满足 metadata 强约束：`title / authors / institution / venue / framework_version`。
- 队列主界面改为版本驱动：主列表展示 `Paper / Version / Status / Topic / Actions`，不再展示提交日期。

## Current Facts
- `job 37` 已失败，不再阻塞 destructive cleanup。
- Prompt 已拆到 `paper_queue/prompts/`，当前运行链主入口：
  - metadata prompt: `paper_queue/prompts/metadata_v1.txt`
  - metadata agent prompt: `paper_queue/prompts/metadata_agent_v1.txt`
  - routing prompt: `paper_queue/prompts/routing_v1.txt`
  - structure prompt: `paper_queue/prompts/structure_analysis_v1.txt`
  - note prompt: `paper_queue/prompts/notes_v1.txt`
  - readability prompt: `paper_queue/prompts/readability_review_v1.txt`
- 本地 SwiftScholar 参考 PDF 已纳入仓库：
  - `/workspace/paper_reading/benchmarks/swiftscholar_pdfs`
  - 当前包含 `Autopoiesis / STELLAR / OpenAgentSafety / MegaScale-Infer / Agents of Chaos`
  - 后续结构、篇幅、图文顺序和图片数量对比优先基于这批本地 PDF，而不是在线页面抓取。

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
- [x] Evaluate 1: 回归现有坏样本，确认不再生成 `Untitled Paper`、`(Available in the text)`、串题结果。
- [x] Evaluate 2: 回归异步提交，确认页面立即出现 `submitting` 且不跳详情页。
- [x] Evaluate 3: 回归 completed-retry，确认仅非最新版 completed 显示 retry。
- [x] Implement 10: 清理旧版本 note，只保留最新版，并同步清掉旧 assets。
- [x] Implement 11: 清理仓库内 `xiaoba-skills/`，不再保留外部参考 skill 副本。
- [x] Implement 12: 迁移旧 assets 到 `paper/_assets/...` 并修复旧文档相对路径。
- [x] Implement 12.1: Obsidian taxonomy 大类目录改为连字符 slug，例如 `Agent-Harness-Evaluation / System-Performance / Kernels-Engineering`；展示名称仍保留为 taxonomy display name。
- [x] Implement 13: 增加独立 configuration file，把 agent 接口与运行参数配置化，而不是把 `claude-glm` 和相关调用参数硬编码在 runtime/workflow 中。
- [x] Implement 14: 在 note generation 之前增加 structure analysis 步骤，用独立 prompt 判断各章节 short / medium / long。
- [x] Implement 15: 成功写 note 后自动导出 review PDF 到 artifact 目录。
- [x] Implement 16: readability-review 接入运行链。成功写 note 后会导出 review PDF、抽取 PDF 文本，并调用配置化 agent 生成非阻塞审读结果。
- [x] Implement 17: 图像注入改为段落级锚点、按展示顺序编号、caption 清洗压缩；PDF 导出修复中文字体渲染。
- [x] Design 1: 统一论文标题层级术语——用户提交为“论文描述”；routing 首抽为“第二标题”；metadata 确认为“第三标题”；notes 前终确认为“第四标题”。
- [x] Design 2: Routing 阶段 Agent 化——agent 从论文描述抽取第二标题 + abstract，基于语义选择 notebook，替代 `_route_tokens` / `_overlap_score` 启发式。
- [x] Design 3: Metadata 阶段 Agent 化——agent 调 NotebookLM 接口，输出结构化 property，确保完整获取 institution / authors / venue，确认第三标题。
- [x] Design 4: Notes 前置阶段 Agent 化——agent 提取第四标题做最终确认，确定文件名短标题 slug 和 canonical topic folder。
- [x] Design 5: Figure semantic extraction——agent 理解图片语义后决定插入位置，替代单纯 `includegraphics` / section keyword 启发式。
- [x] Design 7: Lifecycle flow diagram——在 design doc 补充完整流程图，标注阶段输入/输出、agent 边界、标题层级演进、当前 per-query fresh invocation 交互模式。
- [x] Implement 18: 引入复杂评估系统基础设施：`paper_queue/evaluation.py`、`build_complex_benchmark_assets.py`、`evaluate_complex_benchmark.py`。
- [x] Implement 19: 引入 SwiftScholar 本地 PDF 快照与结构对比脚本。
- [x] Evaluate 6: 已对 `Autopoiesis` 跑通 baseline coverage / placement / length 三轮评估，并落盘到 `benchmarks/assets/autopoiesis/evaluation/latest.json`。
  - 当前 baseline 分数：
    - coverage_ratio = `0.62`
    - placement_ratio = `0.182`
    - interleaving_ratio = `0.782`
    - distribution_ratio = `0.143`
  - 当前差异结果：
    - major headings: SwiftScholar 7 vs current note 8
    - fine headings: SwiftScholar 45
    - images: SwiftScholar 6 vs current note 6
    - paragraphs/blocks: SwiftScholar 291 vs current note 15
- [ ] Evaluate 4: 跑一次 repo cleanup 后的 Git 状态与前端展示，确认没有悬空文件和错链。
  - 已完成一轮 `obsidian_sync` 链接校验：目录迁移到连字符路径后，现存 markdown 图片引用无悬空。
- [ ] Evaluate 8: 扩到 5 篇 benchmark，分别生成 SwiftScholar PDF 的结构/篇幅/图文顺序差异报告。
- [ ] Implement 20: Figure stitching optimization——多图拼接为一张大图，caption 分隔，减少图片阅读调用量。
- [ ] Implement 21: 用 `Autopoiesis` baseline 评估结果反推主流程改进项。
  - coverage 缺口最大的背景/问题定义/workflow 细节
  - placement_ratio 偏低的 figure section 对位
  - distribution_ratio 偏低的方法/结果篇幅不足
  - 已开始：`notes_v1.txt` 增加强制要求，要求背景/方法/实验/结果保留更多原文细节，不再只保留高层摘要
- [x] Implement 22: metadata recovery 强化为多证据汇聚链：HTML citation meta（多值）、arXiv API、LaTeX source、PDF frontmatter、OpenAlex，再用 agent 做最终 evidence fusion。
- [x] Evaluate 9: 对历史 institution 缺失样本做 metadata regression 回归，输出 `benchmarks/metadata_regression.latest.json`。
  - 当前回归集：
    - `AutoKernel`
    - `CUDA Agent`
    - `OpenAgentSafety`
    - `Autopoiesis`
  - 当前结果：4/4 通过
  - 产物：
    - `benchmarks/metadata_regression.json`
    - `benchmarks/metadata_regression.latest.json`
- [ ] Design 8: Future non-arXiv support——source acquisition 改为语义内容提交（无 URL 时给 NotebookLM 标题让其自搜）；figure extraction 跳过（无 LaTeX 源码包）；metadata fallback 补充策略。

## Queued Review Fixes
- [ ] 图片样式：
  - 不再写 `来源:`
  - 优先使用居中 caption 放图下
- [x] 可读性 review：
  - workflow 最后增加 markdown -> PDF 可读性检查
  - 用 `claude-glm` 基于渲染 PDF 抽取文本做非阻塞自动审读
- [x] Autopoiesis 回归：
  - 生成离线回归稿 `paper/System Performance/2026-arXiv-Autopoiesis-v4.md`
  - 图不再集中堆在 section 顶部
  - caption 截断与 PDF 中文乱码已修复
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
- [ ] 旧文档清理第二轮：
  - 已删除明显重复的 `agents-chaos-adversarial-testing` 与 `agents-chaos-red-teaming`
  - 仍需继续统一长文件名与历史坏命名
- [ ] institution 展示：
  - 默认第一机构
  - 并列主机构或关键企业合作时保留多项
  - metadata recovery 已能补出缺失 institution，但字符串规范化仍可继续细化（例如 `ByteDance Seed 2Institute...` 这类清洗质量）

## Version Log

| Framework Version | Change Summary | Status |
| --- | --- | --- |
| 0.1.0 | 初始 Git-only queue、taxonomy routing、figure extraction、benchmark evaluator | historical |
| 0.1.1 | job versioning fields、async submit、icon actions、completed-retry、metadata gate、new assets root | active |
| 0.1.1 | prompt registry + config file + agent backend config 化 | active |
| 0.1.1 | structure analysis 接入运行链 | active |
| 0.1.1 | review PDF 导出 + readability-review 接入运行链 | active |
| 0.1.1 | figure placement/caption 清洗 + PDF 中文字体修复 | active |
| 0.2.0 (planned) | Agent 职责重构 + 复杂评估系统扩到 5 篇基准 | planned |

## Open Blockers
- SwiftScholar PDF 已通过配置接入评估链，不再依赖在线页面抓取；当前 blocker 已转为“如何把 SwiftScholar PDF 的细粒度结构转成合理比较口径”。
- readability-review 已接入运行链，但当前只把 review 写入 artifact 与日志，尚未进入前端详情页的独立字段展示。
- agent backend 已通过 `paper_queue/config/defaults.json` 配置化，当前默认 backend 仍是 `claude-glm`。
- 已验证前端主列表不再显示 `Date`，改为 `Version`；`info / retry / delete` 已切成 icon-only。
- 已验证 completed-retry 只对旧版本完成项出现，最新版完成项不显示 retry。
- 已验证 assets 目录已经统一收口到 `paper/_assets/`，旧的 `paper/<topic>/_assets` 不再存在。
- 已验证 `obsidian_sync` 大类目录已切到连字符 slug，现存 note 与 `_assets` 的相对路径引用可解析。
- 当前 agent 交互模式为 per-query fresh invocation（每次独立进程调用，无持续会话，Python 变量传递状态）；未来是否改为持续会话需权衡 context window 成本 vs 语义连贯性。
