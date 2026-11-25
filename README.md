<!-- README_SYNC: source=working-tree; updated=2026-11-25 -->
<p align="center">
  简体中文 · <a href="./README_EN.md">English</a>
</p>

<div align="center">

# dyz-patent-copyright-skills

**面向专利代理师、企业 IP 与研发团队、软件著作权登记准备者和标准起草人的 Agent Skill 与纯标准库本地工具：只按你提供的材料起草与核对，逐项标明原文支持和缺口，所有产出均为等待专业人员审阅的内部候选。**

如果这套可追溯的做法对你有帮助，欢迎点一个 [Star](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers) 收藏，也让有同样需求的人更容易找到它。

[![Stars](https://img.shields.io/github/stars/duyunzhoudyz/dyz-patent-copyright-skills?style=flat&logo=github)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers)
[![CI](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/actions/workflows/ci.yml)
[![Issues](https://img.shields.io/github/issues/duyunzhoudyz/dyz-patent-copyright-skills?style=flat)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/issues)
[![Version](https://img.shields.io/badge/version-0.1.0a1-1f6feb?style=flat)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-unpublished%20candidate-d97706?style=flat)](RELEASE.md)
[![Python](https://img.shields.io/badge/python-3.11--3.14%20stdlib-3776AB?style=flat&logo=python&logoColor=white)](RELEASE.md)
[![Platform](https://img.shields.io/badge/platform-Windows%20verified%20%7C%20CI%203x4%20pending-0078D6?style=flat)](RELEASE.md)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0%20%7C%20Source%20Available-1f6feb?style=flat)](LICENSE)

[![Stargazers](https://bytecrank.com/nastyox/reporoster/php/stargazersSVG.php?user=duyunzhoudyz&repo=dyz-patent-copyright-skills)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers)

<p>
  <a href="#快速开始">快速开始</a> ·
  <a href="#可复现示例">可复现示例</a> ·
  <a href="#按任务选择-skill-入口">六个 Skill 入口</a> ·
  <a href="#本地-cli-与-mcp-工具">CLI 与 MCP</a> ·
  <a href="#验证状态与能力边界">验证状态与边界</a> ·
  <a href="#和同类-skill-的关系">同类对比</a>
</p>

</div>

> **候选版本与成熟度说明：** 当前代码版本为 `0.1.0a1`（首个公开试用候选，主分支 `main`，拟发布标签 `v0.1.0-alpha.1`，尚未打标签或创建 GitHub Release）。目录中的 11 个能力域、83 项入口全部维持 `synthetic_helper_only`，提供可核查的方法、合成示范与有限本地工具，不代表已完成专业能力、法律结论、执业替代或官方认证。发布范围与待补维护者事实见[发布说明](RELEASE.md)和 [release.json](release.json)，阶段变化见[变更记录](CHANGELOG.md)。

## 它解决什么问题

直接让大模型起草专利文本、软件著作权登记材料或技术标准条款，文字往往很流畅，隐患藏在表面看不出来的地方：顺手补一个原文没有的参数，把"只有……才"改写成"一旦……就"，把"应"软化成"宜"，或者把没检索过的事项写成"未发现"。句子读起来差别不大，保护范围、登记事实或条款强度已经变了。

| 常见做法 | 本项目的做法 |
| --- | --- |
| 一个通用提示词同时处理专利、软著和标准 | 专利、软件版权、技术标准三条业务独立判断，共享证据、版本与本地工具，由六个 Skill 入口分流 |
| 模型顺手补全参数、实验结果或文献出处 | 仅使用给定材料；缺失处标为缺口，未知、未检查、不适用分开记录 |
| 润色专利文本时改写限定方向或丢失原文依据 | 专利侧独立校验技术方案、权项范围与原始支持；专利终稿门禁 2.1 按原文核对，拦截必要条件与充分条件反转等改动 |
| 起草或修订标准时软化条款要求强度或引入循环定义 | 标准侧独立审查条款要求强度（"应/宜/可"）、规范引用与循环定义，不借用专利规则，也不代替试验或组织批准 |
| 交付物是一段聊天记录 | 生成可编辑的 Word 正文、附图、源行映射和独立内部说明，支持生成后回读校验 |
| 检查脚本跑完就标"通过" | 工具结果标记 `needs_review`，未执行项逐条记为 `not_performed`，专业签核另行留痕 |

**适合谁：** 专利代理师、企业 IP 与研发团队、软件著作权登记材料准备者和标准起草人，且已经在使用能读取本地文件的 Agent 宿主（如 Claude Code、Cursor、Codex、Trae），需要可追溯的内部工作稿。

**不适合谁：** 希望一键生成即可直接提交的申请文件，或者想用工具替代执业代理师、律师和标准化组织的专业判断。

## 可复现示例

以下示例于 2026-11-25 在 Windows、Python 3.14.6 本地实测复现，无需外部依赖或联网。

### 示例 1：专利终稿门禁拦截条件方向反转

专利终稿输出前会与原申请文本核对。下面两条候选终稿使用同一句原文：

| 原文 | 候选终稿 | 门禁结果 | 说明 |
| --- | --- | --- | --- |
| 只有记录已写入，才允许确认。 | 只有记录已写入，才允许确认。 | `checked` | 与原文限定关系一致 |
| 只有记录已写入，才允许确认。 | 一旦记录已写入，就允许确认。 | `blocked` | 必要条件被改成充分条件，触发阻断 |

可直接复制这条纯标准库单行命令在仓库根目录复现（预期输出 `ok: checked bad: blocked`）：

```powershell
python -B -X utf8 -c "from tools import patent_gate; from tools.core import sha256_bytes; s='只有记录已写入，才允许确认。'; orig=[{'id':'O1','version':'1','role':'original','text':s,'sha256':sha256_bytes(s.encode())}]; print('ok:', patent_gate.audit_final_text({'claims':s}, orig)['status'], 'bad:', patent_gate.audit_final_text({'claims':'一旦记录已写入，就允许确认。'}, orig)['status'])"
```

`blocked` 表示门禁未能在原文里核到支持，不等于实体法律认定；门禁只覆盖有限规则子集，详见[这一版做不到什么](#这一版做不到什么)。

### 示例 2：正文与内部说明分离的 Word 审阅包闭环

运行[快速开始](#快速开始)第 3 步会从仓库内的合成专利示范构建审阅包并回读校验，产出以下 7 份文件：

| 文件路径 | 作用 |
| --- | --- |
| `body/document.docx` | 可编辑的 Word 正文（不混入内部说明） |
| `body/GatewayFigures.svg` | 可编辑的矢量附图 |
| `body/source.txt` | 正文源文本 |
| `internal/source-map.json` | 段落与原文的源行映射 |
| `internal/notes.txt` | 内部撰写与审阅说明，与正文物理分离 |
| `internal/quality-review.json` | 质量检查与未执行项记录 |
| `manifest.json` | 审阅包清单、哈希与状态 |

<table>
  <tr>
    <td width="42%" valign="top"><img src="skills/dyz-patent/resources/cn-gateway-flow.png" alt="合成专利示范附图：系统关系与待确认批次处理流程"></td>
    <td valign="top"><img src="skills/dyz-software/resources/harbor-delivery-v1.3/gui-sorted.png" alt="软件版权合成示范所用演示软件 v1.3 界面截图"></td>
  </tr>
  <tr>
    <td>合成专利示范附图（仓库内自带合成资源）</td>
    <td>软件版权合成示范演示软件 v1.3 界面截图（仓库内自带合成资源）</td>
  </tr>
</table>

两张图均来自仓库自带的合成示范资源，不含真实案件或客户材料。

## 快速开始

环境要求为 **Python 3.11 至 3.14 标准库**，核心工具零 pip 依赖。下载完整源码树或可信的完整本地包后，保持 `tools/`、`skills/`、`references/` 的相对目录位置，在根目录执行以下命令。跨三业务与 MCP 接入的完整演练见[3 分钟快速上手剧本](skills/dyz-workbench/resources/quickstarts.md)。

### 第 1 步：核对 Python 版本与 83 项能力目录

```powershell
python --version
python -B -X utf8 -m tools help
python -B -X utf8 -m tools list
```

`python --version` 应显示 `3.11.x` 至 `3.14.x`；`help` 列出当前全部 CLI 子命令；`list` 输出 11 个能力域共 83 项 `synthetic_helper_only` 目录 JSON。

### 第 2 步：运行内建合成演练与离线连接器检查

```powershell
python -B -X utf8 -m tools demo --synthetic --root . --output synthetic-demo.json
python -B -X utf8 -m tools connector-status
```

`demo` 在根目录写入 `synthetic-demo.json` 并输出 `result_written`；`connector-status` 输出 `status: "offline_by_default"` 与 `network_requests: 0`。

### 第 3 步：生成并回读合成专利 Word 审阅包

```powershell
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack --verify
```

两条命令依次输出 `document_written_needs_review` 和 `document_verified_needs_review`。输出目标必须事先不存在且位于 `--root` 之内；放在仓库根目录时会被 Git 忽略。PDF 转换是显式可选项，需要本机已安装 LibreOffice，首次试用不依赖它。

### 第 4 步：预览多宿主安装计划与标准 MCP 配置片段

下面两条命令分别输出 JSON 格式的安装预演计划与 MCP（stdio）客户端配置片段，**不写盘、不改动任何全局宿主配置**。`--host` 均支持 `claude-code`、`cursor`、`codex`、`trae`、`generic` 五种配置档；其中 `tools.mcp_server --print-config --host codex` 输出 TOML 配置片段，其余宿主及 `tools.install --plan` 输出 JSON。

```powershell
python -B -X utf8 -m tools.install --target ./dyz-installed-preview --host claude-code --plan
python -B -X utf8 -m tools.mcp_server --print-config --host claude-code
```

如果只需要纯文本起草或核稿，也可以直接让支持读取本地文件的 Agent 加载 `skills/dyz-patent/SKILL.md`（或下表对应的业务入口），并给出类似"只按给定技术材料起草内部工作稿，逐项列出原文支持与缺口"的任务，不必先手写 JSON。

## 按任务选择 Skill 入口

| 你要做的事 | Skill 入口 | 可产出的内部候选 |
| --- | --- | --- |
| 从技术材料起草或修改专利稿 | [专利](skills/dyz-patent/SKILL.md) | 技术事实、给定文献比较、权项与说明书、附图、原文支持反查 |
| 处理审查通知、答复、保护策略与权利问题 | [程序与权利](skills/dyz-procedure/SKILL.md) | 通知分诊、答复与替换稿、支持与程序影响、策略交接 |
| 整理软件著作权登记与争议材料 | [软件版权](skills/dyz-software/SKILL.md) | 范围与贡献、源码选材、操作与设计说明、同版字段及缺件清单 |
| 起草或修订技术标准 | [技术标准](skills/dyz-standards/SKILL.md) | 范围、术语、条款、验证计划、编制说明、意见处理与修订影响 |
| 核对最终文件或定位导出缺陷 | [渲染与核稿](skills/dyz-rendering/SKILL.md) | 源与输出核对、正文与内部材料分离、显示和打印检查记录 |
| 续接项目或跨业务分流 | [共享工作台](skills/dyz-workbench/SKILL.md) | 已知事实、版本依赖、开放问题与给接收角色的交接便笺 |

可以直接从局部任务开始，例如"按给定原稿修正这一项，并列出受影响的正文与附图"。六个入口共享同一棵目录树（`tools/` 与 `references/`），不要把单个 Skill 目录单独复制出去当作自足安装包。

## 本地 CLI 与 MCP 工具

### CLI 子命令总览（`python -B -X utf8 -m tools <subcommand>`）

| 分组 | 子命令 | 用途与边界 |
| --- | --- | --- |
| 基础探索与合成演练 | `help`、`list`、`demo`、`run`、`preview` | 查看帮助、83 项目录、内建披露演练、单能力合成运行与固定快照 HTML 预览 |
| 专利与策略本地核验（新增） | `check-patent-ir`、`build-patent-pack`、`verify-patent-pack`、`check-jurisdiction`、`check-strategy` | 权项-事实 IR 与骨架、合成专利包构建与包外摘要哈希回验、US/EP 权项结构子集分析、不建议申请 / FTO / SEP 分轨核对 |
| 视觉、模板与治理（新增） | `check-visual-ledger`、`check-capture-manifest`、`inspect-template`、`check-trial-upgrade`、`connector-status` | 页面实看与跳过台账、截图清单与 PNG 辅助块清洗核验、只读 DOCX/DOTX 模板安全检查、试审包连续三案门控核对（不自动升级支持等级）、默认离线连接器策略查询 |
| 软件版权本地链 | `software-intake`、`discover-software`、`prepare-software`、`import-software-manual`、`build-software`、`export-software`、`software-batch` | 集中采集、获准清单候选发现、内部准备、新稿导入、DOCX/PDF 生成与分批状态索引；不自动外发 |
| 技术标准本地链 | `standard-intake`、`prepare-standard`、`migrate-standard-comments`、`standard-pdf` | 标准五文书 v2 采集、生成与回验、旧意见表显式迁移、按固定授权转 PDF 并取逐页证据 |

运行 `python -B -X utf8 -m tools help` 可查看总帮助与全部子命令，运行 `python -B -X utf8 -m tools help <topic>` 可查看指定子命令的参数帮助。

### 标准 MCP 服务端、多宿主安装器与 `HostToolBridge` 10 工具契约

| 入口模块 | 说明与常用命令 |
| --- | --- |
| `tools/mcp_server.py` | 纯标准库 JSON-RPC 2.0 `stdio` 服务端，自动识别 `Content-Length` 与 NDJSON 帧。启动时不能裸跑，必须显式传入 `--catalog-only` 仅暴露只读目录工具 `dyz_catalog`，或显式绑定已验证运行包、工作区、控制目录与包外清单哈希（`--package`、`--workspace`、`--control`、`--manifest-sha256`）后才暴露既有 10 项 `HostToolBridge` 工具。执行 `python -B -X utf8 -m tools.mcp_server --describe` 可查看全部 11 个工具定义。 |
| `HostToolBridge` 10 工具 | `case_read`、`case_write`、`case_info`、`case_copy`、`case_image`、`case_documents`、`case_docx_review`、`case_fidelity`、`case_standard_package`、`case_software`。启动期验证运行包清单及（可选）包外清单哈希；运行期仅允许只读读取清单所列文件与 `bundle-manifest.json` 并核对已加载哈希；工作区仅开放 `input/`、`work/`、`output/` 读取且写入限于 `work/` 与 `output/`，受路径边界与防符号链接/重解析点约束，调用契约见[本地文件工具说明](skills/dyz-workbench/resources/host-bridge.md)。 |
| `tools/install.py` | 跨平台本地安装与防篡改校验器，支持 `--plan` 预览不写盘、安装 309 源冻结包与宿主索引/MCP 配置样例，以及 `--verify` 核对包外哈希；从不改写全局宿主配置。 |
| 专业工程扩展与资源 | 专利门禁 2.1（`tools/patent_gate.py`）、原生 Word OMML 数学公式（`tools/omml.py`）、默认离线外联策略层（`tools/connectors/`）、[获准软件成品链与集中采集](skills/dyz-software/resources/tools.md#软件成品链与集中采集)、[标准五文书闭环与 v3 排版](skills/dyz-standards/resources/tools.md#五文书闭环与本地入口)、[文件装配](skills/dyz-rendering/resources/tools.md)、[编辑后 Word 回查](skills/dyz-rendering/resources/docx-readback.md)与[有限公开专利检索附录](skills/dyz-patent/resources/cn-gateway-search.md)。 |

## 架构与专业分工

```mermaid
flowchart LR
    input["输入材料<br/>技术交底 / 源码 / 标准草案"] --> skills["六个 Skill 入口<br/>分流、问诊与起草方法"]
    skills --> draft["内部候选<br/>正文与内部说明分离"]
    draft --> tools["本地工具<br/>门禁、装配与回读核验"]
    tools --> review["needs_review<br/>列出缺口与未检查项"]
    review --> signoff["专业人员审阅与签核<br/>不在本项目内完成"]
```

| 子系统 / 层 | 负责范围 | 不替代 |
| --- | --- | --- |
| 专利 | 检索、交底、可专利空间、权项、说明书与附图、核稿、审查答复、侵权与 FTO、组合管理 | 软件版权登记判断、技术标准共识与发布批准 |
| 软件著作权与软件版权 | 权属与版本、真实源码和文档、交存登记、补正变更、版权争议证据 | 专利性、保护范围与不侵权结论 |
| 技术标准 | 体系研究、立项、术语与条款、试验验证依据、意见处理、国际采用、送审交接与修订 | 专利必要性认定、标准化组织批准、产品认证 |
| 共享基础层 | 材料与证据、权限、术语与版本、差异、绘图与导出、审核记录、评测执行 | 任何专业判定；规则、通过条件与签核归各专业子系统 |

同一项目可以复用经授权的证据，但三条业务的状态、版本、公开范围和交付物保持独立。Skill 中的流程提示不是技术隔离；跨业务披露与外发审批设计见[跨子系统交接与披露审批](docs/disclosure-and-handoff.md)。

## 验证状态与能力边界

### 当前实测基线与未执行项

| 维度 | 当前状态 | 准确范围与说明 |
| --- | --- | --- |
| `release.json` 声明基线 | 既有支持口径 | `release.json` 当前声明的已验证支持基线为 Windows 下的 Python `3.11`、`3.13`、`3.14`（`verified_platforms: ["Windows"]`、`verified_python: ["3.11", "3.13", "3.14"]`），托管 CI 目标矩阵为 Windows / Ubuntu / macOS × Python `3.11`、`3.12`、`3.13`、`3.14`（`target_ci_platforms` / `target_ci_python`），与 `quickstarts.md`、`package-use.md` 保持一致。 |
| 本机四版本补充回归（2026-11-25） | 本地补充实测 | 本机 Windows 上 Python `3.11.15`、`3.12.13`、`3.13.14`、`3.14.6` 四版本均完成全仓 **2,139 / 2,139** 本地单元测试通过、`compileall` 退出 `0`、`evals/release_check.py` 退出 `0`（Git 源码候选 `415` 份，本地运行包白名单 `309` 源文件，6 入口，83 项 catalog）；属本地补充记录，尚未升级 `release.json` 声明。 |
| 托管 GitHub Actions CI | 待首次实跑 | `.github/workflows/ci.yml` 已配置 Windows / Ubuntu / macOS × Python 3.11 / 3.12 / 3.13 / 3.14 共 **12 组**矩阵（固定 Action SHA、`contents: read`、`persist-credentials: false`、并发取消），托管 Linux / macOS 与 Windows 工作流尚未在公开仓首次实跑。 |
| 明确未执行项 | 未执行 | 真实外联请求（`tools/connectors/` 默认离线，仅在显式披露授权（绑定主机、用途、规范化查询、分页范围与有效期）与硬预算限额下才允许只读外联，当前本机未执行真实联网请求）、跨平台 Office / LibreOffice / Poppler 实页视觉复核、付费模型真人盲测（`evals/benchmark_harness.py` 仅完成离线夹具协议自检）、人类执业人员专业签核，以及 `release.json` 三项真实维护者联系事实（`license_holder`、`commercial_contact`、`security_contact`）填写。 |

### 这一版做不到什么

- 工具结论不等于专业结论。`checked`、零 issues、Word 生成成功或 PDF 字面一致，均不证明文件可以正式提交、登记、认证或已获组织批准；83 项入口全部维持 `synthetic_helper_only`，需由具备资格的专业人员按具体案件组合独立复核。
- 专利门禁 2.1 与 US/EP 分析器只覆盖有限规则子集。从属权项继承链、结构锚点、有限英文条件关系、OA 双轨核验与美欧形式检查均非完整法律审查或等价语义判定；遇到 `blocked` 请保留原件，只交付标明"未完成检查"的内部工作稿。
- 默认离线，不执行真实外部办理动作，也不提供操作系统级隔离。可选外联连接器（`tools/connectors/`）默认离线，仅在显式披露授权（绑定主机、用途、规范化查询、分页范围与有效期）与硬预算限额下才允许只读外联，当前本机未执行真实联网请求。本项目没有正式提交、自动外发、签署或付款功能；正式办理、公开征求意见、签章、缴费及需执业资格的行为须另行确认授权与资格。
- 本地工具不等于模型离线。如果所选大模型运行在云端，输入材料仍会进入宿主的数据路径；加载未公开技术、源码或受限标准前，请先确认合规边界。
- 宿主发现与跨平台实页渲染须结合实际环境另验。`tools/mcp_server.py` 与 `tools/install.py` 不自动改写全局宿主配置；真实宿主模型往返稳定性与 Linux / macOS 下的 LibreOffice / Poppler 分页效果尚未完成跨平台实测。
- 合成入口只处理合成样例。真实案件不得改标为合成材料；真实软件与标准材料须走各自显式获准入口。

## 源码仓库与完整本地包

本仓库区分 **Git 源码候选（415 份，主分支 `main`）** 与 **完整本地运行包固定白名单（309 源文件，`bundle_source_files: 309`）**：

| 范围 | 文件数口径 | 包含内容 | 不包含 |
| --- | --- | --- | --- |
| Git 源码仓库 | `source_candidates: 415` | 六个 Skill 及其运行资源、`tools/`、获准 `references/`、白名单设计文档、`evals/` 测试与合成夹具、`.github/` CI 定义、`README_EN.md`、许可与发布元数据 | 过程施工台账、竞品研究快照、历史模型答卷、`outputs/`、`tmp/`、本地私有配置与私人案件 |
| 本地完整运行包 | `bundle_source_files: 309` | 六个入口、共享 `tools/`、实际运行资源、白名单文档与许可文件，外加 `bundle-manifest.json` | 源码仓库内的可运行测试、合成夹具、CI 定义与开发检查器（这些开发材料不随本地包分发）；`README_EN.md` 目前也只随源码仓库提供，未列入本地包白名单 |

只向接收方交付运行时所需内容时，可在根目录按固定白名单构建并绑定包外清单哈希（目标目录须不存在且父目录存在）：

```powershell
python -B -X utf8 -m tools.bundle --destination D:/dyz-local-bundle
$dyzManifestSha = (Get-FileHash -LiteralPath D:/dyz-local-bundle/bundle-manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
python -B -X utf8 -m tools.bundle --verify D:/dyz-local-bundle --manifest-sha256 $dyzManifestSha
```

构建输出 `bundle_created`，校验返回 JSON 中的 `"status": "matched"`。清单哈希应由构建者在包外独立保存并交给下载者核对，不能从待验包自身重新计算"预期值"；不带包外哈希的校验仅证明内部一致，两种校验均不认证来源、许可或专业质量。完整布局、按需加载、冻结与恢复说明见[完整包使用说明](skills/dyz-workbench/resources/package-use.md)。

仓库根与 `docs/` 在 `.gitignore` 中采用白名单管理，`.gitattributes` 关闭换行转换以保留源行映射和合成夹具绑定的原始字节。请勿将客户源码、未申请的交底书、证件、签章资料或受限标准全文放入公开仓库；私人案件资料应放在独立目录或被忽略的 `private/` 目录中。Git 忽略既不是加密也不是访问控制，推送前仍须核对实际跟踪清单。

## 和同类 Skill 的关系

已有不少公开 Skill 把其中某一环节做得很实用。下表依据 2026-11-02 读取的固定提交做静态源码观察，没有在相同输入、模型与环境下对照运行，也不是效果排名：

| 方向 | 代表项目（固定提交） | 源码观察中值得学习的点 | 本项目的侧重 |
| --- | --- | --- | --- |
| 专利 | [paper2patent](https://github.com/7toCR/paper2patent/tree/53d0a2d2cbd8db6de824dfed86aab1763caa7142)、[patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill/tree/0b95b547f78c2a0dd0e4e71eb43a88841c99c936) | 串联权项、附图、DOCX/PDF 与独立撰写说明；清晰的多任务路由 | 原文支持链、逐文献比较、修改影响追踪与程序交接 |
| 软件版权 | [SoftwareCopyright-Skill](https://github.com/Fokkyp/SoftwareCopyright-Skill/tree/1159f6d280783616e1247f768690eac97c1a3f6e)、[software-certificate-skill](https://github.com/IvanCodesDev/software-certificate-skill/tree/ee7d4636f35210767adc0b5689f8678c68e6f7e6) | 串联选材与文档生成；真实界面截图与版本变化后局部重建 | 表达、权利与许可分流、同版事实一致与版本失效追踪 |
| 技术标准 | [gbt-standard-docx-skill](https://github.com/zhangzhangco/gbt-standard-docx-skill/tree/a3af82bc790b0dcf9c2eb8c7123df46311da68da) | DOCX 模板、交叉引用与修改意见表工作流 | 条款与验证依据对应、意见处理与修订影响、公开前 IP 交接 |

口径边界：区分上游自述声明、固定提交源码观察、本机工具运行与同条件实测对照。本项目不以本地测试数量（2,139 项）、仓库星数或设计文档篇幅声称工程或专业写作能力全面领先。完整静态对比见[GitHub 横向比较](docs/github-skill-comparison-20261102.md)与[固定版本来源索引](docs/github-skill-comparison-20261102-sources.json)，上游许可与复用边界见[第三方说明](THIRD-PARTY-NOTICES.md)。本项目未引入任何上游实现代码。

## 文档、贡献与安全报告

### 核心设计文档

- [全球能力蓝图](docs/capability-blueprint.md)：11 个能力域、83 个顶层能力 ID、三专业分工与适配边界。
- [能力契约与覆盖矩阵](docs/capability-contracts.md)：输入、输出、责任与验收要求（规格覆盖不等于能力已实现）。
- [跨子系统交接与披露审批](docs/disclosure-and-handoff.md)：权限、版本、签核、外发与事件处置设计。
- [实施路线与质量门槛](docs/roadmap-and-quality.md)：长期目标、依赖与验证边界（计划不是当前支持）。
- [项目施工规范](docs/development-standards.md)：目录、技能、规则、代码与分层验证约定。
- [参考项目源码分析](docs/reference-analysis.md)：固定版本来源、许可与复用边界。

### 参与贡献与本地检查

欢迎通过 [Issues](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/issues) 和 Pull Requests 改进方法、文档、合成样例与本地工具，具体流程见[贡献指南](CONTRIBUTING.md)。拟合并的原创贡献须由有权贡献者明确同意[贡献许可](CONTRIBUTOR-LICENSE.md)（贡献者保留版权，同时授予项目方商业再许可所需权利）并附 `Signed-off-by`。在 [release.json](release.json) 填明真实授权接收主体前，可以提交讨论和供审阅的补丁，暂不合并需授予权利的外部补丁。

提交改动前，请在完整源码根目录运行与 `.github/workflows/ci.yml` 一致的三步检查（全量测试通常需数分钟）：

```powershell
python -B -X utf8 evals/release_check.py
python -B -X utf8 -m unittest discover -s evals -q
python -B -X utf8 -m compileall -q tools evals skills
```

### 安全与敏感问题报告

敏感安全问题请按[安全报告说明](SECURITY.md)处理。当前 `release.json` 中的 `security_contact` 尚未配置私密渠道，切勿在公开 Issue 或 PR 中附带复现载荷、客户材料、未公开技术或凭证。

## 许可与商业授权

项目原创内容采用 [PolyForm Noncommercial License 1.0.0](LICENSE) 加单独商业授权，属于 **Source Available（源码公开）** 模式。在遵守 [LICENSE](LICENSE) 通知保留义务的前提下，允许范围包括非商业用途、无预期商业应用的个人用途（其中个人用于研究、实验与测试限于增进公共知识，另含个人学习、业余项目等），以及许可证明示列明的非商业机构（慈善组织、教育机构、公共科研机构、公共安全或卫生机构、环境保护机构、政府机构）自身按条款开展的使用（按 [LICENSE](LICENSE) 原文不受资金来源或资助义务限制，但商业主体自身仍须另行获取商业许可）；完整边界以 [LICENSE](LICENSE) 正文为准，本说明不缩减其已授予权利。

个人身份不自动使商业用途免费。超出 [LICENSE](LICENSE) 允许范围的商业用途（包括企业内部研发与 IP 业务流程、代理所或律所收费服务、商业 SaaS 集成或商业再分发）均须事先取得书面商业授权，常见场景与授权路径见[商业授权说明](COMMERCIAL-LICENSE.md)。第三方研究材料与 EPO 有限公开数据继续适用其各自原许可，详见[第三方说明](THIRD-PARTY-NOTICES.md)。

真实授权主体与商业联系渠道待维护者在正式发布前填入 [release.json](release.json)，当前尚未设置。

---

如果这个项目帮你少走了弯路，欢迎点一个 [Star](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers) 收藏；发现缺陷或有改进建议，欢迎按贡献指南提交 [Issue](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/issues) 或 Pull Request。
