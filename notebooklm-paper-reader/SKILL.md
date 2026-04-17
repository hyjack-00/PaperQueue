---
name: notebooklm-paper-reader
description: Academic paper reading and analysis workflow using NotebookLM CLI. Upload papers from arXiv/PDF URLs, extract metadata, perform multi-dimensional analysis, generate Chinese notes, save to the Git-synced Obsidian repository, and optionally generate cross-paper insights and slides. Trigger: "read/analyze this paper", "upload paper", or any paper analysis request with a notebook name.
---

# NotebookLM Paper Reader

Streamlined workflow for reading and analyzing academic papers in NotebookLM with comprehensive analysis and cross-paper insights.

## Overview

This skill provides a complete paper analysis pipeline:
1. **Authentication** - One-time setup with `nlm login`
2. **Paper Upload** - Add papers from arXiv or PDF URLs
3. **Comprehensive Analysis** - Multi-dimensional analysis across 7 dimensions
4. **Chinese Notes** - Generate structured Chinese notes with icons
5. **Save to Obsidian** - Write notes directly into the MAIN vault with full frontmatter
6. **Cross-Paper Insights** *(Optional)* - Synthesize insights across multiple papers
7. **Presentation Slides** *(Optional)* - Generate slide decks

**Estimated Time**: 3-5 minutes for full analysis (depending on paper length)

## Workflow

### Step 1: Check Authentication Status

First, verify NotebookLM authentication using the `nlm` CLI.

**Step 1.1: Check Current Authentication Status**

Check if you're authenticated:

```bash
nlm login --check
```

- If authenticated: Proceed to Step 2
- If not authenticated: Proceed to Step 1.2

**Step 1.2: Authenticate (One-Time Setup)**

If authentication is required, use the nlm login command:

```bash
nlm login
```

**How it works:**

The `nlm login` command will automatically:

1. **Open Chrome browser** - Launches Chrome and navigates to NotebookLM
2. **Wait for user login** - Prompts you to sign in to your Google account if not already logged in
3. **Extract cookies automatically** - Retrieves authentication cookies from the active session
4. **Cache credentials** - Saves everything locally for future use

**Authentication with Profiles:**

For multiple Google accounts, use named profiles:

```bash
nlm login --profile work          # Create/use a work profile
nlm login --profile personal       # Create/use a personal profile
nlm login switch work              # Switch default profile
nlm login profile list             # List all profiles with email addresses
nlm login profile rename old new   # Rename a profile
nlm login profile delete work      # Delete a profile
```

Each profile gets its own isolated Chrome session, allowing you to stay logged into multiple Google accounts simultaneously.

**Authentication Expiration:**
- Session typically lasts **~20 minutes** of active use
- If operations fail, simply run `nlm login` again to refresh
- Cookies are cached and reused across sessions
- For persistent multi-account setup, use profiles

**Troubleshooting Authentication Failures:**

If `nlm login` fails or you encounter authentication errors:

1. **Check authentication status**:
   ```bash
   nlm login --check
   ```

2. **Re-authenticate**:
   ```bash
   nlm login
   ```

3. **Verify by listing notebooks**:
   ```bash
   nlm notebook list
   ```

**Important:** Always verify authentication works before proceeding to Step 2.

### Step 2: Upload Paper to Notebook

Once authenticated, upload the paper using the nlm CLI.

**Upload from URL:**

**Steps:**
1. User provides:
   - Paper URL (arXiv link or direct PDF URL)
   - Notebook name (e.g., "我的论文库", "CV论文阅读")

2. List all notebooks to find the target:
   ```bash
   nlm notebook list --json
   ```

3. Find the notebook ID matching the provided notebook name

4. Add the paper to the notebook:
   ```bash
   nlm source add <notebook-id> --url "<paper-url>" --wait
   ```

   The `--wait` flag ensures the source is fully processed before proceeding.

**Optional: Create an alias for easier access:**
```bash
nlm alias set myproject <notebook-id>
# Now you can use "myproject" instead of the UUID
nlm source add myproject --url "<paper-url>" --wait
```

**Note:** If the notebook name doesn't exist, ask the user if they want to create it:
```bash
nlm notebook create "我的论文库"
```

### Step 3: Analyze the Uploaded Paper

After uploading the paper, use the nlm CLI to perform comprehensive analysis.

**Step 3.0: Get Source Information**

First, retrieve the notebook sources to identify the newly uploaded paper:

```bash
nlm source list <notebook-id> --json
```

Identify the newly added source's ID from the response for subsequent queries.

#### 3.1 Extract Metadata

Use `nlm notebook query` to extract paper metadata:

```bash
nlm notebook query <notebook-id> """Extract the following metadata from this paper:
- Full paper title
- Conference or journal name (include "arXiv" if applicable)
- Publication year
- GitHub repository link (if available)
- Author affiliations/universities

Format the response as structured data."""
```

Extract and **completely output** the following fields in markdown format:

```markdown
## 论文元数据
- **paper**: [PDF or arXiv link as clickable markdown]
- **conference**: [Journal or conference name - include "arXiv" if applicable]
- **year**: [Publication year]
- **repo**: [GitHub/repo link as clickable markdown, or "未开源" if not available]
- **university**: [Author affiliation/institution]
```

**Important**: Output all metadata fields completely so they can be used for creating Obsidian notes with frontmatter.

#### 3.2 Comprehensive Paper Analysis

Use `nlm notebook query` to analyze the paper across multiple dimensions. Query each dimension systematically:

**Dimension 1: Research Background (研究背景)**
```bash
nlm notebook query <notebook-id> """What is the research background of this paper?
- What problem does this paper address?
- What is the motivation behind this work?
- What gaps exist in current research that this paper aims to fill?

Provide detailed information from the paper."""
```

**⏱️ Wait 5-10 seconds before next query to avoid rate limiting**

**Dimension 2: Contributions (贡献)**
```bash
nlm notebook query <notebook-id> """What are the main contributions of this paper?
- What is novel about the approach?
- What value does this work bring to the field?
- List specific technical and academic contributions.

Provide detailed information from the paper."""
```

**Dimension 3: Research Challenges (研究挑战)**
```bash
nlm notebook query <notebook-id> """What are the key research challenges identified in this paper?
- Why are these challenges difficult?
- What constraints or limitations exist in the problem space?

Provide detailed information from the paper."""
```

**⏱️ Wait 5-10 seconds before next query to avoid rate limiting**

**Dimension 4: Research Methods (研究方法)**
```bash
nlm notebook query <notebook-id> """What methodology does the paper propose?
- What is the technical approach?
- What models, algorithms, or frameworks are used?
- How is the method implemented?

Provide detailed technical information from the paper."""
```

**Dimension 5: Experimental Design (实验设计)**
```bash
nlm notebook query <notebook-id> """What is the experimental design in this paper?
- What datasets are used?
- What is the experimental setup?
- What metrics are used for evaluation?
- What are the baselines for comparison?

Provide detailed information from the paper."""
```

**⏱️ Wait 5-10 seconds before next query to avoid rate limiting**

**Dimension 6: Experimental Results and Conclusions (实验结果和实验结论)**
```bash
nlm notebook query <notebook-id> """What are the experimental results and conclusions?
- What are the key findings?
- How does the proposed method compare to baselines?
- Are the results statistically significant?
- What are the main conclusions?

Provide detailed information from the paper."""
```

**Dimension 7: Limitations and Future Work (局限性和未来)**
```bash
nlm notebook query <notebook-id> """What are the limitations and future work discussed?
- What are the acknowledged limitations?
- What directions for future work are suggested?
- What are potential improvements?

Provide detailed information from the paper."""
```

**⏱️ Wait 5-10 seconds before next query to avoid rate limiting**

#### 3.3 Critical Evaluation

Evaluate the paper critically:

- **Research Methods Assessment**:
  - Is the method theoretically sound?
  - Is it novel and innovative?
  - Is it clearly explained and reproducible?
  - Is it appropriate for the problem?

- **Experiments Assessment**:
  - Are datasets appropriate and representative?
  - Are baselines strong and relevant?
  - Are metrics suitable?
  - Are ablation studies provided?
  - Are results statistically significant?
  - Does it generalize to different settings?

- **Innovation Points**:
  - Identify where the innovation lies (new problem formulation, methodology, architecture, dataset, insights, or application)
  - Evaluate if innovation is substantial or incremental
  - Assess if claims are supported by evidence

**For detailed evaluation criteria and analysis framework, see [paper-analysis-template.md](references/paper-analysis-template.md)**

**⏱️ Wait 10-15 seconds before next section (longer query)**

#### 3.3b Advanced Critical Analysis (SRE Professor Mode) - Optional

For deeper, domain-specific critical analysis in Software Reliability Engineering (SRE) and SE4AI, you can invoke the SRE Professor role mode:

**Role Definition:**
> You are a tenured professor in Software Reliability Engineering (SRE) and SE4AI (Software Engineering for AI). Known for rigorous scholarship and sharp logic, with deep expertise in System Dependability, Failure Taxonomy, and Robustness Testing.

**Task**: Assist in reading and analyzing papers with critical thinking—not just summarizing, but conducting critical analysis.

**Analysis Framework:**

1. **Critical Review** - Search for experimental design flaws (Threats to Validity). Does the data have bias? Are baselines too weak? Are conclusions over-claimed?

2. **Conceptual Integrity** - Check consistency of definitions (e.g., Fault, Error, Failure boundaries). If authors contradict themselves, point it out explicitly.

3. **Comparative Lens** - When comparing multiple papers, contrast experimental setups, not just conclusions.

4. **Heuristic for Innovation** - Based on paper limitations, propose concrete "high-risk high-reward" improvements combining industrial deployment (Ops view) with research insights.

**Usage Example:**

```bash
nlm notebook query <notebook-id> """You are now a tenured professor in Software Reliability Engineering (SRE) and SE4AI (Software Engineering for AI), known for rigorous scholarship and sharp logic, with deep expertise in System Dependability, Failure Taxonomy, and Robustness Testing.

Please conduct a critical analysis of this paper using the following framework:

## Critical Review
- Search for experimental design flaws (Threats to Validity)
- Does the data have bias? Are baselines too weak?
- Are conclusions over-claimed (Overclaiming)?

## Conceptual Integrity
- Check consistency of definitions (e.g., Fault, Error, Failure boundaries)
- If authors contradict themselves, point it out explicitly

## Comparative Lens
- If comparing multiple papers, contrast experimental setups, not just conclusions

## Heuristic for Innovation
- Based on the paper's limitations, propose a concrete "high-risk high-reward" improvement
- Combine industrial deployment perspective (Ops view) with research insights

Please provide detailed critical analysis with specific examples from the paper."""
```

**⏱️ Wait 10-15 seconds before generating Chinese notes (longer query)**

#### 3.4 Generate Chinese Notes

Use `nlm notebook query` to generate comprehensive Chinese notes with icons for better readability:

```bash
nlm notebook query <notebook-id> """请基于这篇论文生成完整的中文笔记，包含以下结构，并在每个章节标题前添加相关的 emoji 图标：

## 📄 论文元数据
- 📝 **论文标题**：[完整标题]
- 🏆 **发表会议/期刊**：[会议或期刊名称，arXiv 请标注 arXiv]
- 📅 **发表年份**：[年份]
- 🏫 **作者单位**：[第一作者或主要机构]
- 💻 **开源代码**：[GitHub 链接，如无则写"未开源"]

## 💡 核心直觉
- **核心想法**：用最直白的语言解释作者的灵光一闪，这个论文最核心的洞察是什么

## 🎯 研究背景
- ❓ **研究问题**：[核心问题]
- 💡 **研究动机**：[为什么重要]
- ⚠️ **现有研究的不足**：[当前方法的缺陷或空白]

## ✨ 主要贡献
- 🌟 **核心创新点**：[1-3个最重要的创新]
- 🔧 **技术贡献**：[具体的技术贡献]
- 📚 **学术价值**：[对领域的意义]

## ⚡ 研究挑战
- 🎯 **关键挑战**：[主要技术难题]
- 🔥 **技术难点**：[具体难点]
- 🚧 **约束条件**：[限制条件]

## 🔬 研究方法
- 📋 **方法概述**：[整体方法论]
- 🛤️ **技术路线**：[具体实现路径]
- 🧠 **关键算法/模型**：[核心算法或模型架构]

## 🧪 实验设计
- 📊 **数据集**：[使用的数据集]
- 📏 **评估指标**：[评估标准]
- 🔄 **对比基线**：[与哪些方法对比]
- ⚙️ **实验设置**：[实验配置]

## 📈 实验结果与结论
- 🔍 **主要发现**：[关键实验结果]
- 📊 **性能对比**：[与基线的对比]
- 🎯 **核心结论**：[主要结论]

## 🔍 批判性评估
- ✅ **方法合理性**：[方法是否合理、创新]
- 🧪 **实验充分性**：[实验是否充分、可靠]
- 💎 **创新点分析**：[创新点在哪里]
- ⚠️ **局限性讨论**：[方法的局限性]

## 🚀 未来工作
- 📌 **作者提出的方向**：[论文中提到的未来方向]
- 💡 **潜在改进空间**：[可以改进的地方]

请用详细的中文回答，确保内容完整、结构清晰。在每个章节标题和小标题前使用相关的 emoji 图标。"""
```

**Icon Usage Guidelines**:
- 💡 核心直觉/创意
- 📄 论文元数据
- 🎯 研究背景/目标
- ✨ 贡献/创新
- ⚡ 挑战/难点
- 🔬 研究方法
- 🧪 实验
- 📊 数据/结果
- 📈 性能/分析
- 🔍 评估/分析
- ✅ 合理性确认
- 🚀 未来工作

**Important**:
- The response from `notebook_query` will contain the Chinese notes with icons
- Output the complete Chinese notes content directly to the user in markdown format
- Use the query response rather than calling `report_create` for more control over content structure
- Icons make notes more visually appealing and easier to navigate
- Proceed to Step 3.5 to save notes to the Git-synced Obsidian repository

### Queue / Agent Mode

When this skill is invoked by a queue service or agent wrapper:

- Treat the request as **non-interactive**
- Do **not** ask follow-up questions about directory creation or filename conflicts
- If NotebookLM authentication is invalid, stop immediately and return a machine-readable failure such as `AUTH_REQUIRED`
- If the notebook output directory does not exist, create it automatically
- If the target markdown filename already exists, create `-v2`, `-v3`, etc.
- Write the final markdown into the Git working tree under `/workspace/obsidian_sync/paper/{NotebookName}/`
- Let the queue service handle `git pull`, `git add`, `git commit`, and `git push`

### Step 3.5: Write Notes to Obsidian

After generating Chinese notes, save them to the Git-synced Obsidian repository with proper frontmatter and formatting.

**Step 3.5.1: Determine File Path**

Map the notebook name to Obsidian subdirectory:

1. **Base path**: `/workspace/obsidian_sync/paper/`
2. **Subdirectory**: Matches notebook name (user-defined)
3. **Full path format**: `{base_path}{notebook_name}/{filename}.md`

**Note**: Subdirectories are created on-demand based on notebook names. In queue mode, create them automatically.

**Step 3.5.2: Generate Filename**

Format: `{year}-{conference}-{sanitized_title}.md`

**Fields**:
- `year`: Publication year (e.g., "2026", "2023")
- `conference`: Conference or journal name (e.g., "NSDI", "SOSP", "ICLR", "arXiv")
- `sanitized_title`: Paper title with special chars removed/replaced

**Sanitize title for filename**:
- Replace special chars (`/`, `:`, `?`, `*`, `"`, `<`, `>`, `|`) with underscores or remove
- Keep alphanumeric, spaces, hyphens
- Limit to ~80 characters

**Examples**:
- `2026-NSDI-Who Watches the Watchers.md`
- `2023-SOSP-Acto Automatic End-to-End Testing.md`
- `2024-arXiv-Attention Is All You Need.md`
- `2026-ICLR-Agentic Operator Generation.md`

**Step 3.5.3: Construct Frontmatter**

Add complete YAML frontmatter at the top of the file:

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

**Frontmatter fields**:
- `title`: Full paper title
- `conference`: Conference or journal name (include "arXiv" if applicable)
- `year`: Publication year (number)
- `repo`: GitHub/repo link or "未开源"
- `university`: Author affiliation/institution
- `paper_url`: Original paper URL (arXiv or PDF link)
- `tags`: Array of tags (always include "paper", add conference tag, add topic-specific tags)
- `created_date`: ISO format date (YYYY-MM-DD)
- `notebook`: NotebookLM notebook name

**Step 3.5.4: Write Content Structure**

After frontmatter, write the complete Chinese notes with Obsidian Flavored Markdown:

1. **Preserve all emoji icons** from the Chinese notes
2. **Use Obsidian callouts** for emphasis where appropriate
3. **Format wikilinks** for cross-references (if other papers are mentioned)
4. **Ensure proper markdown structure**

**Step 3.5.5: Write File to Disk**

Write the file directly to the Git working tree using normal file I/O:

```bash
VAULT_BASE="/workspace/obsidian_sync"
FILE_DIR="$VAULT_BASE/paper/{NotebookName}"
mkdir -p "$FILE_DIR"

cat > "$FILE_DIR/{year}-{conference}-{sanitized_title}.md" << 'EOF'
---
[frontmatter content]
---

[Chinese notes content]
EOF
```

**Actions**:
1. Verify the subdirectory exists (create with `mkdir -p` if needed)
2. If file already exists:
   - interactive mode: ask whether to overwrite or create a new version
   - queue mode: automatically create a new version suffix (`-v2`, `-v3`, ...)
3. Write the file directly to disk
4. If running inside the queue service, let the queue handle Git sync and push after the file is written
5. Confirm success with the repo-relative file path

**See [obsidian-template.md](references/obsidian-template.md) for detailed Obsidian formatting guidelines**

### Step 4: Cross-Paper Analysis

Integrate insights from other papers in the same notebook to generate comprehensive research insights.

**Step 4.1: Get All Sources in Notebook**

```bash
nlm source list <notebook-id> --json
```

Identify all existing sources in the notebook to understand the context.

**Step 4.2: Identify Common Themes**

```bash
nlm notebook query <notebook-id> """Analyze all papers in this notebook and identify common themes:
- What research problems are shared across multiple papers?
- What common techniques or approaches are used?
- What datasets or benchmarks are frequently used?
- What are the recurring challenges?

Provide a comprehensive analysis of common themes."""
```

**⏱️ Wait 10-15 seconds before next cross-paper query**

**Step 4.3: Compare and Contrast Approaches**

```bash
nlm notebook query <notebook-id> """Compare the different approaches taken by papers in this notebook:
- How do different papers address similar problems?
- What are the strengths and weaknesses of each approach?
- Which methods are complementary and which are competing?
- Are there contradictory findings or conclusions?

Provide detailed comparisons."""
```

**⏱️ Wait 10-15 seconds before next cross-paper query**

**Step 4.4: Identify Research Gaps**

```bash
nlm notebook query <notebook-id> """Based on all papers in this notebook, identify research gaps:
- What problems are not adequately addressed by any paper?
- What combinations of approaches have not been explored?
- What datasets or scenarios are not covered?
- What theoretical questions remain unanswered?

List specific research gaps."""
```

**⏱️ Wait 10-15 seconds before final cross-paper query**

**Step 4.5: Generate Future Research Directions**

```bash
nlm notebook query <notebook-id> """Synthesize insights from all papers to propose future research directions:
1. Method Combinations:
   - How could methods from different papers be combined?
   - What hybrid approaches would be promising?

2. Cross-Domain Applications:
   - How could techniques from one paper be applied to problems addressed by another?
   - Are there opportunities to adapt methods to new domains?

3. Extensions and Improvements:
   - How could limitations of one paper be addressed by techniques from another?
   - What extensions would build on multiple papers' contributions?

4. Prioritization:
   - Which directions are most feasible?
   - Which would have the highest impact?
   - What are quick wins vs. long-term investments?

Provide specific, actionable research directions with rationale."""
```

**Step 4.6: Synthesize and Output Insights**

Based on the query responses, synthesize cross-paper insights and present:

- **Common Themes Summary**: What unifies the research in this notebook
- **Comparative Analysis**: Key differences and trade-offs between approaches
- **Research Gaps**: Important problems not yet addressed
- **Future Directions**: Prioritized list of promising research opportunities
- **Synthesis**: How different papers complement each other

**See [paper-analysis-template.md](references/paper-analysis-template.md) for detailed cross-paper analysis framework**

### Step 5: Generate Presentation Slides

Create a presentation for the paper:

**Step 5.1: Request User Confirmation**

Before generating slides, ask the user: "Would you like me to generate presentation slides for this paper?"

**Step 5.2: Generate Slide Deck**

After user confirmation, create the slide deck:

```bash
nlm slides create <notebook-id> --confirm
```

For more control over slide generation:

```bash
nlm slides create <notebook-id> \
  --format detailed_deck \
  --length default \
  --confirm
```

**Available options:**
- `--format`: `detailed_deck` (comprehensive) or `presenter_slides` (concise)
- `--length`: `short` or `default`

**Note**: The `nlm slides create` command generates slides based on all sources in the notebook. To focus on a specific paper, you may need to create a separate notebook with only that paper's source.

**Step 5.3: Monitor Slide Generation**

After initiating slide generation:

```bash
# Poll for completion
nlm studio status <notebook-id>
```

- Poll periodically every 30 seconds
- Wait for generation to complete (typically 1-3 minutes)
- Retrieve the final slide URL from the response
- Present the URL to the user

**Step 5.4: Output Results**

Once complete, provide:
- Direct link to the generated slide deck
- Brief summary of what's included
- Instructions on how to view/download

**Optional: Download the slides**

```bash
nlm download slides <notebook-id> <artifact-id> --output presentation.pdf
```

## Important Notes

- **Authentication**: Run `nlm login` to authenticate. It will open Chrome and extract authentication cookies automatically. Session typically lasts ~20 minutes.
- **Multiple Accounts**: Use `nlm login --profile <name>` for multiple Google accounts.
- **Upload Method**: URL-based upload using `nlm source add <notebook> --url <url> --wait`.
- **Notebook Selection**: If the specified notebook doesn't exist, create it with `nlm notebook create "Title"` or list with `nlm notebook list`.
- **Aliases**: Use `nlm alias set <name> <notebook-id>` to create shortcuts.
- **Query Intervals**: **CRITICAL** - Wait 5-10 seconds between dimension queries, 10-15 seconds between cross-paper queries.
- **Obsidian Output**: Notes are saved to the MAIN vault with full frontmatter. Subdirectory structure matches notebook names.
- **Slide Generation**: Always get user confirmation before generating slides (use `--confirm` flag).
- **Output Formats**: Use `--json` flag for programmatic processing, `--quiet` for IDs only.
- **Language**: Use Chinese queries for Chinese notes, English queries for English content.

## Resources

### references/

Documentation and frameworks referenced during analysis:

- **paper-analysis-template.md**: Complete framework for paper analysis including metadata extraction, analysis dimensions, evaluation criteria, innovation assessment, and cross-paper analysis methodology.
- **obsidian-template.md**: Obsidian Flavored Markdown template and guidelines for saving paper notes. Includes frontmatter structure, filename format, tag strategy, and content organization.
- **CLI_GUIDE.md**: Reference for NotebookLM CLI commands and usage.
