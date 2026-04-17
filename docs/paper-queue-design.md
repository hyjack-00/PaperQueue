# Paper Queue 设计文档

最后更新：2026-04-17

## 1. 目标

这份文档要明确三件事：

1. `paper queue` 作为一个系统，哪些部分是确定性的流程。
2. 哪些部分是真正依赖 prompt 的语言任务。
3. 哪些部分是关键词 / 规则驱动，不能交给 `claude-glm` 或其他 Agent 自行发挥。

目标不是只解释“现在代码怎么跑”，而是把后续演进边界讲清楚：  
prompt 应该作为独立资产管理，workflow 负责生命周期编排，配置层负责 agent 接口与运行参数。

## 2. 当前单篇论文的生命周期

当前主入口在 [workflow.py](/workspace/paper_reading/paper_queue/workflow.py)。

一篇论文现在大致会经历下面这些阶段：

1. `submit`
   - 用户提交论文标题、arXiv 链接、PDF 链接，或者其他字符串输入。
   - 可选地指定 NotebookLM notebook。
   - 系统先把任务写入 SQLite 队列。

2. `routing`
   - 如果输入是 arXiv URL，系统先尝试从 arXiv 页面抓标题。
   - 如果用户手动指定 notebook，则直接使用。
   - 否则系统用关键词重叠去匹配现有 notebook 标题与 notebook summary。
   - 如果没有匹配上的 notebook，则按 topic hint 自动创建 notebook。

3. `source acquisition`
   - URL 输入：
     - 调用 `nlm source add <notebook> --url ... --wait`
     - 如果 `arxiv.org/abs/...` 失败，则 fallback 到 PDF URL
   - 标题 / query 输入：
     - 调用 `nlm research start ... --auto-import`
   - 然后解析最终导入的 source ID

4. `metadata`
   - 先向 NotebookLM 查询 metadata
   - 再用 HTML citation tags 做 fallback 补全
   - 最后做强校验

5. `notes`
   - 向 NotebookLM 查询中文阅读稿 markdown
   - 再做 heading normalization、bibliographic block normalization 等后处理

6. `taxonomy storage routing`
   - 把最终产物映射到 canonical topic folder，而不是直接跟 notebook 名绑定

7. `figure extraction`
   - 优先下载 arXiv source archive
   - fallback 到 PDF figure extraction
   - 把图片插回 markdown

8. `write + git sync`
   - 同步 Git repo
   - 写 markdown 和 assets
   - commit + push

9. `complete / fail`
   - 写结果、日志、输出路径
   - 标记为 `completed / failed / waiting_auth / blocked_git`

## 3. 确定性流程 vs Prompt 驱动步骤

### 3.1 确定性流程

这些应该留在 workflow / runtime / config 里，不应该写成 prompt：

- 队列状态机：
  - `queued -> running -> completed/failed/waiting_auth/blocked_git`
- Notebook 路由机制：
  - arXiv 标题提取
  - notebook list / notebook describe
  - 输入和 notebook 标题/summary 的 overlap scoring
  - notebook 自动创建
- Source import 机制：
  - `nlm source add`
  - `nlm research start`
  - arXiv abs -> PDF fallback
- Metadata 强校验：
  - 哪些字段是必填
  - 缺失时直接失败
  - source fingerprint 一致性检查
- Taxonomy 映射机制：
  - canonical topic lookup
  - 输出目录选择
- Figure extraction 机制：
  - source archive 下载
  - TeX figure 解析
  - PDF fallback
  - 图片导出
- Git 操作：
  - fetch / reset / add / commit / push
- 前端交互状态：
  - `submitting`
  - `retry`
  - `delete`
  - latest-version 判定

这些都属于系统流程，不应该让 Agent 自己决定。

### 3.2 Prompt 驱动步骤

这些才是真正应该拆成 prompt 文件的内容：

- metadata extraction prompt
- note generation prompt
- 后续要加的 readability-review prompt
- 后续要加的 structure-analysis prompt

目前前两个还直接写在 `workflow.py` 里，这是当前设计债务之一。

## 4. 当前 Prompt 清单

### 4.1 Metadata Prompt

当前位置：
- [workflow.py](/workspace/paper_reading/paper_queue/workflow.py)
- 函数：`_query_metadata()`

当前职责：
- 提取：
  - full paper title
  - conference / journal / accepted venue
  - publication year
  - author list
  - author affiliations
  - original paper URL
  - GitHub repo URL

当前输出假设：
- 简洁结构化文本，每个字段一行

当前问题：
- prompt 文本直接嵌在 workflow 代码里
- prompt 迭代和 workflow 逻辑耦合
- fallback 逻辑一部分靠 prompt，一部分靠代码，边界不清楚

### 4.2 Note Prompt

当前位置：
- [workflow.py](/workspace/paper_reading/paper_queue/workflow.py)
- 函数：`_query_notes()`

当前职责：
- 生成中文阅读稿 markdown
- 顶层结构固定为：
  - `TL;DR`
  - `论文基本信息`
  - `1. 整体概括`
  - `2. 背景与动机`
  - `3. 方法与系统设计`
  - `4. 实验设置`
  - `5. 结果与分析`
  - `6. 总结与思考`

当前 prompt 控制的要求：
- 保留关键英文术语
- 不编造事实
- 去掉 inline citation markers
- 结果段必须写数字和对比
- 总结段必须写局限性 / 风险 / 开放问题
- 按 archetype 强化重点：
  - `systems`
  - `evaluation`
  - `safety`
  - `tuning`
  - `retrieval`
  - `general`

当前问题：
- 结构要求、风格要求、领域偏好都揉在一个长字符串里
- 后面如果继续加“章节长短动态分配”“作者观点 vs 个人启发分离”，这个 inline prompt 会越来越难维护

## 5. 当前关键词 / 规则驱动部分

这些部分当前是 rule-based，不是 prompt-based。

### 5.1 Topic Taxonomy Routing

当前位置：
- `ROUTE_TOPIC_MAP`，在 [workflow.py](/workspace/paper_reading/paper_queue/workflow.py)

当前 canonical topics：
- `Kernels Engineering`
- `System Performance`
- `Agent Harness Evaluation`
- `Ops4LLM`
- `Automated Tuning`
- `LLM Memory, Context, and Retrieval`

当前行为：
- tokenize 输入 / 标题 / notebook summary
- 计算 overlap score
- 选择最匹配的 topic / notebook

这个部分应该继续保持确定性。

### 5.2 Figure Section Classification

当前位置：
- `_classify_figure_section()`，在 [workflow.py](/workspace/paper_reading/paper_queue/workflow.py)

当前行为：
- 根据 section text 和 caption 关键词把图分类到：
  - `background`
  - `method`
  - `experiment`
  - `results`
  - `conclusion`

这是 heuristic placement logic，不应该变成 prompt。

### 5.3 Metadata Fallback And Validation

当前位置：
- `_fallback_metadata()`
- `_validate_metadata()`

当前行为：
- fallback 到 HTML citation tags
- 拒绝 `Untitled Paper` 这种占位值
- 缺关键字段就失败

这个部分也应该保持确定性。

## 6. 目标边界设计

后续应该拆成三层：

### 6.1 Workflow Layer

继续保留在 `workflow.py` / `runtime.py` 中：

- job lifecycle orchestration
- queue state and logging
- notebook routing
- source import
- metadata fallback / validation
- figure extraction
- git write / push

workflow 层可以决定“调用哪个 prompt 文件”，但不应该再直接包含 prompt 正文。

### 6.2 Prompt Registry Layer

建议新增目录：

```text
paper_queue/prompts/
  metadata_v1.txt
  notes_v1.txt
  structure_analysis_v1.txt
  readability_review_v1.txt
```

职责：

- 只存 prompt 文本
- 支持独立版本化
- 支持独立 review
- 让 prompt diff 和 workflow diff 分开

### 6.3 Configuration Layer

后续还需要新增配置文件，例如：

```text
paper_queue/config/
  queue.yaml
  prompts.yaml
  agent.yaml
```

职责：

- 指定当前使用的 agent backend
  - 例如 `claude-glm`
  - 或后续其他 Agent 接口
- 指定当前使用的 prompt set / prompt version
- 指定超时、feature flags、retry policy 等参数

这层存在的原因是：

- prompt 不该硬编码在 workflow 里
- agent command 也不该硬编码在 runtime 里
- 系统应该能切换 backend，而不是默认永远绑死 `claude-glm`

## 7. 推荐的 Prompt 拆分

### Prompt A: `metadata_v1`

职责：
- 只做 bibliographic metadata extraction

允许做的事：
- 读 source 内容
- 返回结构化 metadata 字段

不允许做的事：
- 决定 taxonomy topic
- 决定 notebook 路由
- 决定文件命名
- 决定 retry 行为

### Prompt B: `structure_analysis_v1`

职责：
- 在生成正文前，先判断论文结构重点

建议输出：
- paper archetype
- 各章节长度建议：
  - background: short / medium / long
  - method: short / medium / long
  - experiments: short / medium / long
  - results: short / medium / long
  - conclusion: short / medium / long
- figure priorities

这一步是后续实现“章节长度动态分配”的关键。

### Prompt C: `notes_v1`

职责：
- 基于 metadata + structure analysis + source content 生成正文

不应该负责：
- notebook 路由
- taxonomy topic
- 文件命名
- git 行为

### Prompt D: `readability_review_v1`

职责：
- 审读渲染后的 markdown / PDF 可读性

目标：
- 检查是否连续堆图
- 检查图文是否交错
- 检查章节是否失衡

它应该只输出 review 结果，不直接改 workflow。

## 8. 推荐保留为规则配置的项目

这些内容不应该写进 prompt，而应该保留为显式配置或代码：

- canonical taxonomy list
- notebook overlap scoring threshold
- source import fallback order
- metadata required fields
- filename pattern
  - `<year>-<venue>-<short-title>[-vN].md`
- latest-version detection
- assets directory pattern
  - `paper/_assets/<topic>/<note-stem>/...`
- retry policy
  - failed retry
  - non-latest completed retry
- framework version bump policy
- agent backend choice
- prompt version selection

## 9. 后续推荐重构顺序

建议按这个顺序做：

1. 新增 `paper_queue/prompts/`
2. 把 metadata prompt 拆到 `metadata_v1.txt`
3. 把 notes prompt 拆到 `notes_v1.txt`
4. 新增 prompt loader
5. 用 prompt loader 替换 `workflow.py` 里的 inline string
6. 新增 `structure_analysis_v1.txt`
7. 把 structure analysis 接到 note generation 前
8. 新增 `readability_review_v1.txt`
9. 新增 configuration file
10. 把 `claude-glm` / agent command / prompt version / timeouts 都迁到配置层

## 10. 总结

当前真实情况是：

- queue lifecycle 大部分是确定性 workflow
- notebook routing 是关键词 / 规则驱动
- taxonomy routing 是关键词 / 规则驱动
- figure extraction 是确定性 + heuristic
- 真正属于 prompt 的，当前只有 metadata extraction 和 note generation 两块

所以当前核心问题不是“系统太依赖 prompt”。  
而是“真正依赖 prompt 的那几块被直接嵌在 workflow 代码里了，边界不清楚，也不方便独立 review 和演进”。

这份文档定义的目标就是：

- prompt 作为独立资产管理
- workflow 负责生命周期和编排
- configuration 负责 agent backend 与运行参数

这三层分开。
