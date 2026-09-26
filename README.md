# FormatAI — 文档格式 AI 智能排版 Agent

> 上传格式模板 + 内容文件 → AI Agent 自动分析模板格式、匹配内容段落、套用格式 → 生成可直接提交的 .docx

---

## 一、项目简介

FormatAI 是一个**论文/报告格式自动排版工具**。用户只需提供两个文件：

1. **格式模板**（`.docx`）—— 老师给的、或学校规定的格式样例文件
2. **内容文件**（`.docx` 或 `.md`）—— 你写好内容但格式还没调的草稿

Agent 会自动把模板的格式（字体、字号、行距、缩进、对齐等）套用到你的内容上，生成一份格式规范的文档。**不写新内容，不改原文。**

### 解决什么问题

写论文/报告时，手动调格式耗时且容易出错——字体选错、行距不对、标题层级混乱、缩进不一致……FormatAI 让这个过程全自动，2 分钟完成原本 2 小时的工作。

---

## 二、大模型充当什么角色

本项目采用 **LangGraph Agent 架构**，大模型（LLM）在其中扮演**核心决策者**的角色，但**不直接操作文件**。整个流程可以理解为：

```
确定性工具负责"读"和"写"  →  LLM 负责"判断"和"匹配"  →  确定性工具负责"生成"
```

### LLM 的具体职责

LLM 只在 **`match_styles` 节点**被调用一次，负责完成**语义理解与格式匹配**这件确定性算法做不好的事：

| 输入 | LLM 推理 | 输出 |
|------|---------|------|
| 模板的格式模板列表（每个模板的字体/字号/行距/缩进等属性 + 示例文本） | 理解每个格式模板的语义角色（标题？正文？列表？） | 每个内容段落 → 对应格式模板的映射 |
| 内容文档的段落列表（文本 + 语义角色 + 当前样式） | 判断每个段落属于哪种格式类型 | 置信度评分 + 推理依据 |

**为什么这一步必须用 LLM？**

格式匹配本质上是语义理解任务，不是简单的规则匹配：

- "一、项目背景" 是标题还是正文？需要理解中文编号体系
- "租客：注册/登录……" 是列表项还是正文？需要理解内容结构
- 第 3 段和第 7 段看起来都是正文，该用同一个格式模板吗？需要一致性判断
- 模板里哪个格式模板对应"标题"？需要根据示例文本推断

这些判断对人类很直观，但对传统算法需要大量硬编码规则且容易误判。LLM 凭借语言理解能力，一次调用就能完成高质量的语义匹配。

### LLM 不做什么

- **不解析文件**——模板解析、内容解析由确定性工具完成（lxml 读 OOXML XML）
- **不生成文档**——.docx 生成由确定性工具完成（直接操作 XML）
- **不校验格式**——校验由确定性 schema validator 完成
- **不改写文本**——原文内容一字不动，只改格式

### 为什么这样设计

```
┌─────────────────────────────────────────────────────────────┐
│                    确定性 + 智能性的分层                       │
│                                                             │
│   模板解析 (确定性)    内容解析 (确定性)    格式校验 (确定性)  │
│       │                    │                   ↑            │
│       ▼                    ▼                   │            │
│      ┌─────────────────────────────────┐        │            │
│      │     LLM 语义匹配 (智能)          │        │            │
│      │  "这段话是标题还是正文？"         │────────┘            │
│      │  "该用哪个格式模板？"            │   (不通过则重试)      │
│      └─────────────────────────────────┘                     │
│                      │                                      │
│                      ▼                                      │
│              文档生成 (确定性)                                │
│         把格式模板的 XML 直接写入段落                         │
└─────────────────────────────────────────────────────────────┘
```

这种分层的好处是：
- **可复现**：同样的输入，LLM 匹配结果可能微调，但格式应用逻辑 100% 确定
- **可调试**：每个节点的输出都存入 state，出问题能定位到具体环节
- **可替换**：换更强的模型只影响匹配质量，不影响格式准确性

---

## 三、Agent 架构

项目基于 **LangGraph** 构建，使用 `StateGraph` 编排 7 个节点，支持条件路由、文档类型自动识别和失败自愈重试。

### 流程图

```
START
  │
  ▼
parse_template ──── 解析模板 .docx，提取格式模板（format profiles）
  │                 工具: docx_parser (读 styles.xml + document.xml)
  ▼
analyze_content ─── 解析内容 .docx，提取段落结构 + 语义角色
  │                 工具: content_analyzer (mammoth + python-docx)
  ▼
classify_document ─ 识别文档类型（copy / text_flow / table_form）
  │                 工具: document_classifier (结构指纹比对)
  │
  ├── copy ─────────→ generate_docx（原样输出内容，跳过 LLM）──→ output ──→ END
  │
  └── 其余 ─────────→ match_styles ──→ verify_formatting
                          │
                          ├── 通过 ──────────→ generate_docx ──→ output ──→ END
                          │
                          └── 不通过 ─────────→ (retry < 3?) ──→ 回到 match_styles (带错误反馈)
                                                  └── (retry ≥ 3?) ──→ handle_error ──→ END
```

### 节点说明

| 节点 | 职责 | 是否调用 LLM |
|------|------|:---:|
| `parse_template` | 读取模板的 `styles.xml` 和 `document.xml`，提取样式定义 + 段落直接格式，分组为格式模板 | 否 |
| `analyze_content` | 解析内容文档，提取每个段落的文本、语义角色、当前样式 | 否 |
| `classify_document` | 用结构指纹判断文档类型（copy / text_flow / table_form），决定走哪条生成路径 | 否 |
| `match_styles` | 将内容段落匹配到格式模板，输出 `profile_id` 映射 | **是** |
| `verify_formatting` | 校验映射的覆盖率、格式模板存在性、一致性；不通过则带反馈重试 | 否 |
| `generate_docx` | 将格式模板的格式 XML 直接应用到内容段落，生成 .docx（copy 模式下原样输出内容） | 否 |
| `output` | 生成 HTML 预览 | 否 |

### 文档类型自动识别

上传的文件对会先由 `classify_document` 节点用**结构指纹**（表格数量、列结构、顶层段落数、样式集合）分类，决定后续处理策略：

| 模式 | 判断依据 | 处理策略 |
|------|---------|---------|
| `copy` | 表格数相等、列结构一致、顶层段落数近似、样式高度重合（即"内容 = 模板 + 填值"） | 直接原样输出内容文件，跳过 LLM |
| `text_flow` | 双方基本无表格，线性段落流 | 现有 LLM 匹配 → 校验 → 生成 |
| `table_form` | 内容/模板以表格为主，且内容 ≠ 模板 | 当前走 restyle 路径（表格感知重排为后续规划） |

为什么需要 `copy` 模式：像《实习实践手册》这类表格型模板，用户上传的"内容"往往就是"模板填好值"的同一份文件——格式本就正确。若仍走 LLM 匹配重排，会把封面/顶层段落的 `pStyle` 剥掉、拍平成有损的直接格式，而真正的表格内容又因流水线只遍历顶层段落而漏掉，导致输出"混乱"。`copy` 模式识别出这种退化场景后直接原样返回，从根源上避免。

---

## 四、核心技术：格式模板提取

这是本项目最关键的技术创新，解决了"模板格式套用不上"的根本问题。

### 问题背景

中文文档（尤其是论文模板）有一个特点：**格式常常写在段落的"直接格式"上，而不是样式定义里**。

- `styles.xml` 里的 `Normal` 样式可能只有 Word 默认值（Calibri 11pt）
- 但模板正文实际显示的是宋体 12pt、行距 20pt、左缩进 44pt
- 这些真实格式藏在 `document.xml` 段落的直接格式属性中

如果只读 `styles.xml`，会得到错误的格式信息——这正是很多排版工具失败的原因。

### 解决方案

`docx_parser.py` 同时读取 `styles.xml` 和 `document.xml`，对每个模板段落计算**有效格式**（effective format）：

```
有效格式 = 样式定义（styles.xml）⊕ 直接格式（document.xml，覆盖样式）
```

然后将格式相同的段落分组为**格式模板**（format profiles）：

| profile_id | role | 字体 | 字号 | 行距 | 缩进 | 对齐 |
|---|---|---|---|---|---|---|
| profile_0 | title | 默认 | 默认 | - | - | 居中 |
| profile_1 | heading | 宋体 | 14pt | - | 36pt | - |
| profile_2 | body | 宋体 | 12pt | 20pt(固定) | 44pt | - |
| profile_3 | list_item | 宋体 | 12pt | - | 22pt | - |

每个格式模板同时保存可直接应用的 `pPr_xml` 和 `rPr_xml`，生成时直接写入输出段落。

### 格式应用原则

生成文档时遵循 OOXML 格式优先级规则：

1. **清除内容文档的所有直接格式**——避免原格式覆盖模板格式
2. **移除 `numPr`**——避免出现多余的项目符号
3. **保留 `b/i/u`**——加粗、斜体、下划线是语义标记，不是格式
4. **从模板复制** `styles.xml`、`theme1.xml`、`fontTable.xml`、`sectPr`——保证字体定义、主题色、页面布局一致

---

## 五、项目结构

```
d:\Layout\
├── app/
│   ├── main.py                      # FastAPI 入口
│   ├── config.py                    # 配置（API Key、模型、路径等）
│   ├── api/
│   │   ├── router.py                # API 路由（上传/处理/状态/下载）
│   │   ├── modify.py                # API 路由（自然语言格式修改）
│   │   ├── job_manager.py           # 作业管理（内存存储）
│   │   └── schemas.py               # 请求/响应模型
│   ├── agent/
│   │   ├── graph.py                 # LangGraph 图编排 + 条件路由
│   │   ├── state.py                 # AgentState 状态定义
│   │   ├── nodes/
│   │   │   ├── parse_template.py    # 节点1：解析模板
│   │   │   ├── analyze_content.py   # 节点2：分析内容
│   │   │   ├── classify_document.py # 节点2.5：文档类型识别
│   │   │   ├── match_styles.py      # 节点3：LLM 格式匹配 ★
│   │   │   ├── verify_formatting.py # 节点4：格式校验
│   │   │   ├── generate_docx.py     # 节点5：生成文档
│   │   │   └── output.py            # 节点6：生成预览
│   │   ├── tools/
│   │   │   ├── docx_parser.py       # 工具：解析 .docx 模板（含格式模板提取）
│   │   │   ├── pdf_parser.py        # 工具：解析 PDF 模板
│   │   │   ├── content_analyzer.py  # 工具：分析内容文档
│   │   │   ├── document_classifier.py # 工具：文档类型识别（结构指纹）
│   │   │   ├── docx_generator.py    # 工具：生成 .docx（含格式应用 + copy 模式）
│   │   │   ├── schema_validator.py  # 工具：校验映射结果
│   │   │   ├── preview_builder.py   # 工具：生成 HTML 预览
│   │   │   ├── docx_modifier.py     # 工具：按自然语言指令修改已有 .docx
│   │   │   ├── docx_snapshot.py     # 工具：读取 .docx 当前格式快照
│   │   │   └── format_instructor.py # 工具：将自然语言转为格式指令
│   │   └── prompts/
│   │       ├── system.py            # System Prompt
│   │       ├── match_styles.py      # 匹配节点的 Prompt 构建
│   │       └── format_instruction.py # 格式修改指令的 Prompt 构建
│   └── static/
│       ├── index.html               # 前端主页面
│       ├── modify.html              # 前端格式修改页
│       ├── style.css
│       └── app.js
├── uploads/                         # 上传文件暂存
├── output/                          # 输出文件
├── requirements.txt
└── README.md
```

---

## 六、技术栈

| 层 | 技术 | 用途 |
|----|------|------|
| **Agent 框架** | LangGraph | StateGraph 状态图 + 条件路由 + 失败重试 |
| **LLM** | DeepSeek / OpenAI 兼容协议 | 语义匹配（支持 DeepSeek、智谱、通义千问等） |
| **Web 服务** | FastAPI + Uvicorn | 异步 API、文件上传、后台任务 |
| **前端** | 原生 HTML/CSS/JS | 纯展示层，零框架 |
| **.docx 解析** | lxml + zipfile | 直接读 OOXML XML，绕过 python-docx 的有损 API |
| **内容解析** | mammoth + python-docx | HTML 语义结构 + 段落属性 |
| **PDF 解析** | PyMuPDF | PDF 模板格式推断 |

---

## 七、快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 AI API

创建 `.env` 文件：

```env
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

支持的服务商：

| 服务商 | BASE_URL | MODEL |
|--------|----------|-------|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

### 3. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000`

---

## 八、使用流程

| 步骤 | 操作 | 后台 Agent 在做什么 |
|------|------|-------------------|
| ① 上传 | 拖入格式模板 + 内容文件 | 文件暂存到 `uploads/` |
| ② 排版 | 点击「开始智能排版」 | parse → analyze → match → verify ⇄ retry → generate |
| ③ 下载 | 预览 + 下载 .docx | 输出到 `output/` |

### API 接口

| 方法 | 路由 | 用途 |
|------|------|------|
| `GET` | `/api/config-status` | 查看 AI 配置状态 |
| `POST` | `/api/upload` | 上传模板 + 内容文件 |
| `POST` | `/api/process` | 启动 Agent |
| `GET` | `/api/job/{id}/status` | 轮询运行状态 |
| `GET` | `/api/job/{id}/preview` | 获取 HTML 预览 |
| `GET` | `/api/job/{id}/download` | 下载 .docx |
| `DELETE` | `/api/job/{id}` | 清理作业 |

---

## 九、限制说明

- 模板支持 `.docx`（推荐）和 `.pdf`（只能推断格式，效果较差）
- 内容文件支持 `.docx` 和 `.md`（Markdown，自动识别标题/列表/引用/代码块及加粗斜体）
- 不处理需要登录才能访问的网站内容
- 不支持图片/视频格式的提取与转换
- 文件大小限制 10MB
