# Obsidian Paper Notes Template

This template defines the structure for saving paper notes to the Git-synced Obsidian repository.

## File Path Structure

### Base Path
```
/workspace/obsidian_sync/paper/
```

### Subdirectories
The subdirectory matches the NotebookLM notebook name. Subdirectories are created on-demand based on user's notebook names.

### Full Path Format
```
{base_path}{notebook_name}/{filename}.md
```

## Filename Format

### Format
```
{short_conf}{year}-{sanitized_title}.md
```

### Conference Identifier Mapping
- "arXiv" → "arXiv"
- "ICLR 2026" → "ICLR26"
- "NeurIPS 2025" → "NeurIPS25"
- "CVPR 2024" → "CVPR24"
- "ACL 2025" → "ACL25"
- Generic format: first word + year (e.g., "Conference26")

### Filename Sanitization Rules
- Remove or replace special characters: `/`, `:`, `?`, `*`, `"`, `<`, `>`, `|` → `_`
- Convert multiple consecutive spaces to single space
- Trim leading/trailing spaces
- Limit to ~80 characters (excluding extension)
- Keep alphanumeric, spaces, and hyphens

### Examples
- `ICLR26-Agentic Operator Generation.md`
- `arXiv26-Attention Is All You Need.md`
- `NeurIPS25-Deep Reinforcement Learning.md`

## Frontmatter Template

```yaml
---
title: "Full Paper Title"
conference: "Conference Name"
year: 2026
repo: "https://github.com/..." or "未开源"
university: "Author Affiliation"
paper_url: "https://arxiv.org/abs/..."
tags: ["paper", "conference/year", "topic-tags"]
created_date: 2026-02-12
notebook: "NotebookName"
---
```

## Frontmatter Field Details

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `title` | string | Full paper title | "Agentic Operator Generation for ML ASICs" |
| `conference` | string | Conference/journal name | "ICLR", "arXiv", "NeurIPS" |
| `year` | number | Publication year | 2026 |
| `repo` | string | GitHub link or "未开源" | "https://github.com/example/repo" |
| `university` | string | Author affiliation | "Meta" |
| `paper_url` | string | arXiv or PDF link | "https://www.arxiv.org/abs/2512.10977" |
| `tags` | array | Tags for search/filtering | ["paper", "ICLR26", "agent", "ASIC"] |
| `created_date` | string | ISO format date | "2026-02-12" |
| `notebook` | string | NotebookLM notebook name | "MyPapers" |

## Tag Strategy

### Required Tags
- Always include `"paper"`

### Conference Tags
- Format: `{Conference}{Year}`
- Examples: `"ICLR26"`, `"NeurIPS25"`, `"arXiv26"`

### Topic Tags
Extract from title and content:
- Technologies: `"agent"`, `"LLM"`, `"transformer"`, `"GAN"`
- Domains: `"interpretability"`, `"optimization"`, `"RL"`
- Tasks: `"classification"`, `"generation"`, `"detection"`

## Content Structure

After frontmatter, the content should follow the Chinese notes structure with icons:

```markdown
---
title: "Full Paper Title"
conference: "Conference Name"
year: 2026
repo: "https://github.com/..." or "未开源"
university: "Author Affiliation"
paper_url: "https://arxiv.org/abs/..."
tags: ["paper", "conference/year", "topic-tags"]
created_date: 2026-02-12
notebook: "NotebookName"
---

## 📄 论文元数据
- 📝 **论文标题**: Full Paper Title
- 🏆 **发表会议/期刊**: Conference Name 2026
- 📅 **发表年份**: 2026
- 🏫 **作者单位**: Author Affiliation
- 💻 **开源代码**: [GitHub](https://github.com/...) or "未开源"

## 💡 核心直觉
{作者的灵光一闪，用最直白的语言解释核心想法}

## 🎯 研究背景
- ❓ **研究问题**: [核心问题]
- 💡 **研究动机**: [为什么重要]
- ⚠️ **现有研究的不足**: [当前方法的缺陷或空白]

## ✨ 主要贡献
- 🌟 **核心创新点**: [1-3个最重要的创新]
- 🔧 **技术贡献**: [具体的技术贡献]
- 📚 **学术价值**: [对领域的意义]

## ⚡ 研究挑战
- 🎯 **关键挑战**: [主要技术难题]
- 🔥 **技术难点**: [具体难点]
- 🚧 **约束条件**: [限制条件]

## 🔬 研究方法
- 📋 **方法概述**: [整体方法论]
- 🛤️ **技术路线**: [具体实现路径]
- 🧠 **关键算法/模型**: [核心算法或模型架构]

## 🧪 实验设计
- 📊 **数据集**: [使用的数据集]
- 📏 **评估指标**: [评估标准]
- 🔄 **对比基线**: [与哪些方法对比]
- ⚙️ **实验设置**: [实验配置]

## 📈 实验结果与结论
- 🔍 **主要发现**: [关键实验结果]
- 📊 **性能对比**: [与基线的对比]
- 🎯 **核心结论**: [主要结论]

## 🔍 批判性评估
- ✅ **方法合理性**: [方法是否合理、创新]
- 🧪 **实验充分性**: [实验是否充分、可靠]
- 💎 **创新点分析**: [创新点在哪里]
- ⚠️ **局限性讨论**: [方法的局限性]

## 🚀 未来工作
- 📌 **作者提出的方向**: [论文中提到的未来方向]
- 💡 **潜在改进空间**: [可以改进的地方]
```

**Content Structure** (笔记内容结构):
1. 📄 论文元数据 - Paper metadata
2. 💡 核心直觉 - Core insight in plain language
3. 🎯 研究背景 - Research background
4. ✨ 主要贡献 - Main contributions
5. ⚡ 研究挑战 - Research challenges
6. 🔬 研究方法 - Research methods
7. 🧪 实验设计 - Experimental design
8. 📈 实验结果与结论 - Results and conclusions
9. 🔍 批判性评估 - Critical evaluation
10. 🚀 未来工作 - Future work

## Obsidian Flavored Markdown Features

### Callouts
Use for emphasis where appropriate:
```markdown
> [!INFO] Important Note
> This is a key insight from the paper.

> [!WARNING] Limitation
> The method has constraints on X.
```

### Wikilinks
Format for cross-references to other papers:
```markdown
See also [[ICLR26-Another Paper]] for related work.
```

### Tags
Inline tags can be added throughout:
```markdown
This method uses #reinforcement_learning and #transformers.
```

### Embeds
Embed other notes or resources:
```markdown
![[Related Analysis Note]]
![[diagram.png]]
```

## Error Handling

### Subdirectory Does Not Exist
- Interactive mode: prompt before creating a new directory
- Queue mode: create directory automatically with `mkdir -p`

### File Already Exists
- Check if file exists before writing
- Interactive mode: prompt whether to overwrite or version
- Queue mode: automatically create a new version (`-v2`, `-v3`, etc.)

## Writing Files

Write files directly to the Git working tree using bash heredoc:

```bash
VAULT_BASE="/workspace/obsidian_sync"
mkdir -p "$VAULT_BASE/paper/{NotebookName}"

cat > "$VAULT_BASE/paper/{NotebookName}/{filename}.md" << 'EOF'
[Complete file content with frontmatter and notes]
EOF
```

If the file is being produced by the queue service, let the queue handle `git pull`, `git add`, `git commit`, and `git push` after writing.
