# 复杂评估系统设计

## 目标

旧版评估只做关键词命中和粗粒度结构检查，强度不够。新评估系统改成“基于原论文资产的持久化检查点 + 多轮 agent review”。

目标覆盖四类能力：

1. 内容覆盖率
2. 图 / 表 / 公式的放置与图文交错
3. 篇幅大小与章节分布
4. 多轮不同角度的自 review

## 评估资产

每篇 benchmark 论文在 `benchmarks/assets/<paper_id>/` 下持久化：

- `paper_meta.json`
- `source.pdf`
- `pdf_structure.json`
- `paragraph_info_points.json`
- `paragraph_batches/*.json`
- `evaluation/latest.json`

### 1. 原文段落信息点

先从 PDF 提取段落，再让 agent 对每一段生成：

- 一句简洁中文直译
- 至少一个可检查的重要细节信息点
- 一组关键词

这使得覆盖率可以按“信息点 0/1 命中”评估，而不是按粗糙关键词匹配。

### 2. 图 / 表 / 公式引用资产

从 PDF 段落里提取：

- `Figure/Fig./Table/Eq./Equation` 引用
- 引用所在 section
- 引用前后上下文

这样 placement review 不再只是看“有没有图”，而是看：

- 是否覆盖了这个对象
- 是否放到了合理的章节
- 是否和文字形成穿插

### 3. 篇幅分布资产

从 PDF 提取每个 section 的：

- 段落数
- 图数
- 表数
- 公式数

再对生成 note 做同样统计，比较分布是否相近。

## 评估流程

### Step 1: 构建 benchmark assets

脚本：

- `scripts/build_complex_benchmark_assets.py`

流程：

1. 下载原论文 PDF
2. 提取段落 / section / 引用 / 章节统计
3. 用 agent 为每批段落生成中文直译和信息点
4. 将结果持久化

### Step 2: 跑多角度评估

脚本：

- `scripts/evaluate_complex_benchmark.py`

当前分 3 个 review：

1. `coverage review`
2. `placement review`
3. `length distribution review`

每一轮都会把结果落到每篇论文自己的 `evaluation/latest.json`。

## Prompt 与流程边界

### 流程逻辑

这些是确定性流程：

- 下载 PDF
- PDF 提取
- 段落切分
- section 检测
- 图表公式引用检测
- 章节篇幅统计
- note 定位
- 评估结果持久化

### Prompt 逻辑

这些交给 agent：

- 段落直译与信息点抽取
- 信息点覆盖率逐条判断
- 图表公式放置与图文交错判断
- 篇幅分布合理性判断

## 多轮自 review

当前系统的多轮自 review 指：

1. coverage 视角
2. placement/interleaving 视角
3. length-distribution 视角

后续可以继续增加：

- terminology fidelity review
- author-claims vs personal-takeaways separation review
- readability / visual rhythm review

## 配置

所有评估相关参数在：

- `paper_queue/config/defaults.json`

当前新增字段：

- `evaluation.assets_dir`
- `evaluation.paragraph_batch_size`
- `evaluation.self_review_rounds`
- `evaluation.max_paragraph_chars`

评估 prompt：

- `benchmark_paragraph_points_v1.txt`
- `benchmark_coverage_review_v1.txt`
- `benchmark_placement_review_v1.txt`
- `benchmark_length_review_v1.txt`
