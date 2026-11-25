<!-- README_SYNC: source=working-tree; updated=2026-11-25 -->
<p>简体中文 · <a href="./README_EN.md">English</a></p>

# dyz-patent-copyright-skills

**面向专利、软件著作权和技术标准工作的一套 Agent Skill 与本地工具：让 AI 只按你给的材料起草和核对，逐项列出原文支持与缺口，产出一律是等待专业审阅的内部候选。**

如果这套做法对你有用，欢迎点一个 [Star](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers) 收藏，也方便有同样需求的人找到它。

[![Stars](https://img.shields.io/github/stars/duyunzhoudyz/dyz-patent-copyright-skills?style=flat&logo=github)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers)
[![CI](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/actions/workflows/ci.yml)
[![Issues](https://img.shields.io/github/issues/duyunzhoudyz/dyz-patent-copyright-skills)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/issues)
[![Version](https://img.shields.io/badge/version-0.1.0a1-blue)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-unpublished%20candidate-orange)](RELEASE.md)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.13%20%7C%203.14%20(CI%20target%203.11--3.14)-3776AB)
![Platform](https://img.shields.io/badge/platform-Windows%20verified%20%7C%20Linux%2FmacOS%20CI%20pending-0078D6)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)

[![Stargazers](https://bytecrank.com/nastyox/reporoster/php/stargazersSVG.php?user=duyunzhoudyz&repo=dyz-patent-copyright-skills)](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers)

> **当前状态：** `0.1.0a1` 是尚未正式发布的候选版本（没有打标签，也没有建 Release），拟发布标签 `v0.1.0-alpha.1`。目录中 11 个能力域、83 项入口的支持等级全部是 `synthetic_helper_only`：方法、合成示范和有限检查已经可用，不代表完整的专业能力，也不代表正式办理能够通过。发布范围和待补信息见[发布说明](RELEASE.md)，版本变化见[变更记录](CHANGELOG.md)。

## 它解决什么问题

直接让大模型写专利、软著材料或标准条款，文字通常很顺，问题藏在看不出来的地方：补了一个原文没有的参数，把“只有……才”润色成“一旦……就”，把“应”改成“宜”，或者把没查过的事写成“未发现”。读起来差不多，保护范围、登记事实或要求强度已经变了。

这个项目把这些风险拆成能检查的做法：

| 常见做法 | 这里的做法 |
| --- | --- |
| 一个通用提示词同时处理专利、软著和标准 | 三条业务各自判断，证据、版本和工具共享，由六个 Skill 入口分流 |
| 模型顺手补上参数、实验或来源 | 只用给定材料；缺的列为缺口，未知、未检查、不适用分开记录 |
| 润色时悄悄改了限定关系或要求强度 | 专利终稿门禁按原文核对，改变限定关系的句子会被阻断 |
| 交付物是一段聊天文本 | 可编辑的 Word、源行映射和独立的内部说明，生成后可以回读校验 |
| 检查脚本跑完就写“通过” | 结果标 `needs_review`，没做的逐项写 `not_performed`，专业签核另行记录 |

**适合：** 专利代理师、企业 IP 与研发团队、软件登记材料准备者和标准起草人——已经在用能读取本地文件的 Agent，需要可追溯的内部工作稿。
**不适合：** 想要一键生成即可提交的申请文件，或者想用它替代代理师、律师和标准化组织的判断。

## 一个可以复现的例子

以下结果于 2026-11-17 在 Windows、Python 3.11.15 上实际运行得到。

**终稿门禁。** 专利终稿在交出前会和原申请文本核对。下面两行用的是同一句原文：

| 原文 | 候选终稿 | 结果 |
| --- | --- | --- |
| 只有记录已写入，才允许确认。 | 只有记录已写入，才允许确认。 | `checked` |
| 只有记录已写入，才允许确认。 | 一旦记录已写入，就允许确认。 | `blocked` |

第二行把必要条件写成了充分条件，读起来差不多，限定关系已经变了，所以被拦下。`blocked` 的意思是门禁没能在原文里核到支持，不等于认定它没有依据；门禁只覆盖有限句法，见[这一版做不到什么](#这一版做不到什么)。

**文件闭环。** [快速开始](#快速开始)的第 3 步会从仓库内的合成专利示范生成一个审阅包，并回读校验：

| 文件 | 内容 |
| --- | --- |
| `body/document.docx` | 可编辑的 Word 正文 |
| `body/GatewayFigures.svg` | 可编辑的附图 |
| `body/source.txt` | 正文文本 |
| `internal/source-map.json` | 源行映射 |
| `internal/notes.txt` | 内部说明，不进入正文 |
| `internal/quality-review.json` | 质量检查记录 |
| `manifest.json` | 包清单与状态 |

<table>
  <tr>
    <td width="40%" valign="top"><img src="skills/dyz-patent/resources/cn-gateway-flow.png" alt="合成专利示范的附图：系统关系与待确认批次的处理流程"></td>
    <td valign="top"><img src="skills/dyz-software/resources/harbor-delivery-v1.3/gui-sorted.png" alt="软件版权合成示范所用演示软件 v1.3 的界面截图"></td>
  </tr>
  <tr>
    <td>合成专利示范的附图</td>
    <td>软件版权合成示范所用演示软件 v1.3 的界面截图</td>
  </tr>
</table>

两张图都是仓库自带的合成示范资源，不含真实案件。

## 快速开始

环境：**Python 3.11—3.14 标准库**，核心工具零 pip 依赖。本机已实测基线为 Windows 下的 Python 3.11 / 3.13 / 3.14；Windows Python 3.12 及 Ubuntu / macOS（Python 3.11 / 3.12 / 3.13 / 3.14）已完成跨平台代码守护与 CI 矩阵配置，待托管 CI 实跑验证。下载完整源码或可信的完整包，保留 `tools/`、`skills/`、`references/` 的相对位置，在根目录运行命令；完整 3 分钟实操演练见[快速上手剧本](skills/dyz-workbench/resources/quickstarts.md)。

**1. 确认解释器**

```powershell
python --version
```

应显示 3.11.x 至 3.14.x（当前本机已实测 3.11 / 3.13 / 3.14，3.12 待托管 CI 验证）。

**2. 查看能力目录、帮助与合成演练**

```powershell
python -B -X utf8 -m tools help
python -B -X utf8 -m tools list
python -B -X utf8 -m tools demo --synthetic --root . --output synthetic-demo.json
```

`list` 输出 83 项的 JSON 目录，`demo` 输出 `result_written`。

**3. 生成并回读一份合成 Word 审阅包**

```powershell
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack --verify
```

依次输出 `document_written_needs_review` 和 `document_verified_needs_review`。输出目标须事先不存在，并且位于 `--root` 之内；放在仓库根目录时会被 Git 忽略。PDF 是显式可选的转换，需要本机已安装 LibreOffice，不是首次试用的前提。

**4. 通过标准 MCP（stdio）或本地安装器接入 Agent 宿主**

```powershell
# 预览安装计划与 MCP 客户端配置片段（不写盘、不改全局配置）
python -B -X utf8 -m tools.install --target D:/dyz-installed --host claude-code --plan
python -B -X utf8 -m tools.mcp_server --print-config --host claude-code
```

纯文本场景也可直接让支持读取文件的 Agent 加载 `skills/dyz-patent/SKILL.md`，再提出类似“只按给定技术材料起草内部工作稿，逐项列原文支持和缺口”的任务。文字任务不需要先填 JSON；软件版权或标准任务改用下表对应的入口。

## 从你的任务选入口

| 你要做的事 | 入口 | 可以交出的内部候选 |
| --- | --- | --- |
| 从技术材料起草或修改专利稿 | [专利](skills/dyz-patent/SKILL.md) | 技术事实、给定文献比较、权项与说明书、图示、支持反查 |
| 处理通知、答复、保护与权利问题 | [程序与权利](skills/dyz-procedure/SKILL.md) | 通知分诊、答复与替换稿、支持及程序影响、后续交接 |
| 整理软件版权材料 | [软件版权](skills/dyz-software/SKILL.md) | 范围与贡献、源码选材、操作与设计说明、同版字段及缺件 |
| 起草或修订技术标准 | [技术标准](skills/dyz-standards/SKILL.md) | 范围、术语、条款、验证计划、编制说明、意见与修订影响 |
| 核对最终文件或处理导出缺陷 | [渲染与核稿](skills/dyz-rendering/SKILL.md) | 源与输出核对、正文与内部材料分离、显示和打印检查记录 |
| 续接项目、跨业务分流 | [共享工作台](skills/dyz-workbench/SKILL.md) | 已知事实、版本依赖、开放问题及给接收角色的便笺 |

可以从一个局部任务开始，例如“按给定原稿修正这一项，并列出受影响的正文和图”。已有的事实不重复采集，没提供的材料不补造。不要把单个 Skill 目录复制出去当作自足的安装包：六个入口共享同一棵目录。

### 更多本地入口

- [3 分钟快速上手剧本](skills/dyz-workbench/resources/quickstarts.md)：跨专利、软件、标准与 MCP 接入的可复制演练。
- [完整包使用说明](skills/dyz-workbench/resources/package-use.md)：布局、按需加载、冻结和恢复。
- [本地文件工具](skills/dyz-workbench/resources/host-bridge.md)与标准 MCP 服务端：`python -B -m tools.host_bridge --describe` 或 `python -B -m tools.mcp_server --describe` 列出工具定义；多宿主安装计划使用 `python -B -m tools.install`。
- 专利工程扩展：权项-事实中间表示（`tools/patent_ir.py`）、专利门禁 2.1（从属继承、结构锚点、英文子集与 OA 双轨核验 `tools/patent_gate.py`）、三轴材料接入（`tools/patent_intake.py`）、原生 Word 数学公式 OMML（`tools/omml.py`）及美欧法域与 FTO/SEP/不建议申请策略分析（`tools/jurisdiction_analyzers.py`、`tools/procedure_strategy.py`）。
- [获准的本地软件材料](skills/dyz-software/resources/tools.md#软件成品链与集中采集)：多技术栈只读发现、三批次集中采集（`software_intake.collect_batch`）、PNG 辅助块清洗与截图清单元校验（`tools/media_prep.py`）及源码/说明/字段 DOCX 生成。所有产物仍是内部候选。
- [标准五文书闭环](skills/dyz-standards/resources/tools.md#五文书闭环与本地入口)：支持 v3 排版配置（DOCX 侧支持有限原生 OMML 公式）、外部合规模板声明式映射（`tools/template_mapper.py`）、六维结构审稿与循环定义检测及术语标准示范。
- 可选外联只读连接器与验证治理：默认离线的 USPTO/EPO/SAMR/ISO/外部 MCP 策略适配层（`tools/connectors/`）、多模态视觉覆盖台账（`tools/visual_ledger.py`）、专家试审包与连续三案升级门控（`tools/trial_pack.py`），以及开发仓未见任务盲测协议校验器（`evals/benchmark_harness.py`）。
- [文件装配](skills/dyz-rendering/resources/tools.md)与[编辑后的 Word 回查](skills/dyz-rendering/resources/docx-readback.md)。
- [有限公开专利检索附录](skills/dyz-patent/resources/cn-gateway-search.md)：研究资源，实际查询、公开版本和逐篇比较分列。

## 它是怎么组织的

```mermaid
flowchart LR
    a["你的材料<br/>技术交底 / 源码 / 标准草案"] --> b["六个 Skill 入口<br/>问诊、分流、起草方法"]
    b --> c["内部候选<br/>正文与内部说明分开"]
    c --> d["本地工具<br/>原文支持门禁、生成、回读"]
    d --> e["needs_review<br/>列出未检查项"]
    e --> f["专业人员审阅与签核<br/>不在本项目内完成"]
```

| 子系统 / 层 | 负责 | 不替代 |
| --- | --- | --- |
| 专利 | 检索、交底、可专利空间、权项、说明书与制图、核稿、审查答复、侵权/FTO、组合管理 | 软件版权登记判断、标准共识和发布批准 |
| 软件著作权／软件版权 | 权属与版本、真实源码和文档、交存登记、补正变更、版权争议材料 | 专利性、保护范围和不侵权结论 |
| 技术标准 | 体系研究、立项、术语与条款、试验验证、意见处理、国际采用、送审交接与修订 | 专利必要性认定、组织批准、产品认证 |
| 共享基础层 | 材料与证据、权限、术语与版本、差异、绘图与导出、审核记录、评测执行 | 任何专业判定；规则、通过条件和签核归各专业子系统 |

同一项目可以复用经授权的证据，但三条业务的状态、版本、公开范围和交付物各自独立。Skill 里的流程提示不是技术隔离；跨业务披露与外发的审批设计见[跨子系统交接与披露审批](docs/disclosure-and-handoff.md)。

## 这一版做不到什么

- **Windows Python 3.12、Linux/macOS 托管 CI 与跨平台 Office/PDF 尚未全部实测。** 核心标准库工具与发布检查已在本机 Windows Python 3.11 / 3.13 / 3.14 实测通过并加入跨平台守护；Windows / Ubuntu / macOS × Python 3.11 / 3.12 / 3.13 / 3.14 矩阵已写入 `.github/workflows/ci.yml`，待公开仓库后由托管 CI 实跑验证，LibreOffice/Poppler 物理分页核验仍以 Windows 实测为基线。
- **专利门禁 2.1 与美欧分析器仍只覆盖有限规则子集。** 虽已扩展从属权项继承链、结构锚点、有限英文条件关系、OA 双轨核验与 US/EP 形式提示，但仍非完整法律审查或等价语义判定。遇到 `blocked` 请保留原件，只交标明“未完成检查”的内部工作稿。
- **默认离线且未执行真实外联/付费盲测。** `tools/connectors/` 在未显式开启策略与配额前一律默认离线；未见任务盲测框架仅在本地离线夹具上完成协议自检，尚未执行大规模真人盲评或付费模型对照，不作市场效果领先声明。
- **工具结论不是专业结论。** `checked`、零 issues、Word 生成成功或 PDF 字面一致，都不证明可以提交、登记、认证或已获组织批准；83 项入口仍为 `synthetic_helper_only`，需经独立专业人员按具体组合连续复核并由维护者另行决策，不保证授权、登记、不侵权或标准获批。
- **不替你做真实动作。** 没有真实提交、自动外发、签署或付款，也不提供操作系统级隔离。正式提交、公开征求意见、发布、签章、缴费和需要执业资格的行为，须另行确认授权与资格。
- **本地工具不等于离线。** 模型如果在云端，材料仍会进入宿主的数据路径；加载前请确认未公开技术、源码和受限标准可以这样处理。
- **外部宿主自动发现与全局配置由用户自决。** `tools/mcp_server.py` 与 `tools/install.py` 提供标准 stdio MCP 接口与本地配置片段，不自动改写全局宿主配置；真实宿主模型往返稳定性须结合具体宿主版本另验。
- **合成入口只处理合成示例。** 真实案件不能改标为合成材料；真实软件与专利材料须走显式获准入口。

## 完整本地包

只想把运行所需的内容交给别人时，按固定白名单构建一个包，并绑定清单哈希：

```powershell
python -B -X utf8 -m tools.bundle --destination D:/dyz-local-bundle
$dyzManifestSha = (Get-FileHash -LiteralPath D:/dyz-local-bundle/bundle-manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
python -B -X utf8 -m tools.bundle --verify D:/dyz-local-bundle --manifest-sha256 $dyzManifestSha
```

构建输出 `bundle_created`，校验返回的 JSON 中 `"status": "matched"`。包目标须不存在，父目录须存在。本次构建是本地完整运行包白名单的 309 个源文件，不是整个 Git 源码仓库的文件总数（当前 source_candidates 口径为 415 份）；准确数量以清单为准。

- 清单哈希由构建者保存在包外。下载者应使用发布者提供的哈希来校验，不要从待核的包里重新算一个“预期值”。
- 不带包外哈希的校验只证明内部一致。两种校验都不认证来源、许可或专业质量。
- 包内是六个入口、共享工具、实际用到的资源和许可文件。源码仓库另保留可运行测试、合成夹具及 CI 定义，这些开发材料不随本地包分发。英文版 `README_EN.md` 目前也只随源码仓库提供，未列入本地包白名单。

完整布局、按需加载、冻结和恢复见[完整包使用说明](skills/dyz-workbench/resources/package-use.md)。

## 和同类 Skill 的关系

已有不少公开 Skill 把这件事的一部分做得很好。下表依据 2026-11-02 读取的固定提交做静态阅读，没有在同一环境运行，也不是效果排名。

| 方向 | 代表项目（固定提交） | 值得学的 | 本项目的侧重 |
| --- | --- | --- | --- |
| 专利 | [paper2patent](https://github.com/7toCR/paper2patent/tree/53d0a2d2cbd8db6de824dfed86aab1763caa7142)、[patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill/tree/0b95b547f78c2a0dd0e4e71eb43a88841c99c936) | 串联权项、附图、DOCX/PDF 和独立撰写说明；多条任务入口 | 原文支持、逐文献比较、修改影响和程序交接 |
| 软件版权 | [SoftwareCopyright-Skill](https://github.com/Fokkyp/SoftwareCopyright-Skill/tree/1159f6d280783616e1247f768690eac97c1a3f6e)、[software-certificate-skill](https://github.com/IvanCodesDev/software-certificate-skill/tree/ee7d4636f35210767adc0b5689f8678c68e6f7e6) | 串联选材和文档；真实截图与变化后重建 | 表达、权利与许可分流，源码选材，同版事实与版本影响 |
| 技术标准 | [gbt-standard-docx-skill](https://github.com/zhangzhangco/gbt-standard-docx-skill/tree/a3af82bc790b0dcf9c2eb8c7123df46311da68da) | DOCX 模板、交叉引用和意见表工作流 | 条款与验证依据、意见处理与修订影响、公开前的 IP 交接 |

“工程完整度超过对标项目”是建设目标，目前不作领先声明。完整比较见 [GitHub 横向比较](docs/github-skill-comparison-20261102.md)和[固定版本来源索引](docs/github-skill-comparison-20261102-sources.json)，许可与复用边界见[第三方说明](THIRD-PARTY-NOTICES.md)。本项目没有引入上游实现。

## 仓库里放什么

Git 只管理面向 GitHub 分发的内容：六个 Skill 及其必要资源、`tools/`、获准的 `references/`、可运行测试与合成夹具、CI 定义、使用与许可说明，以及 `.gitignore` 白名单内的稳定设计文档。`.gitignore` 对根目录和 `docs/` 采用白名单，新增顶层文件或设计文档需要明确加入；`.gitattributes` 关闭换行转换，保留来源映射和合成示例所绑定的原始字节。Skill 中成套的 Word、PDF 和图像示例属于可运行资源，不能只凭扩展名当作临时产物排除。

过程计划、施工台账、竞品调研快照、历史模型答卷、`outputs/`、`tmp/` 和本地配置只留在维护者本地。

不要把客户源码、未申请的交底书、证件、签章资料和受限标准全文放进公开仓库；私人案件资料放在独立目录或被忽略的 `private/` 中。Git 忽略不是加密，也不是访问控制，推送前仍要检查实际跟踪清单。

## 文档

- [全球能力蓝图](docs/capability-blueprint.md)：11 个能力域、83 个顶层能力 ID、三专业分工与适配边界。
- [能力契约与覆盖矩阵](docs/capability-contracts.md)：输入、输出、责任和验收要求；规格覆盖不等于能力已实现。
- [跨子系统交接与披露审批](docs/disclosure-and-handoff.md)：权限、版本、签核、外发及事件处置。
- [实施路线与质量门槛](docs/roadmap-and-quality.md)：长期目标、依赖和验证边界；计划不是当前支持。
- [项目施工规范](docs/development-standards.md)：目录、技能、规则、代码与分层验证约定。
- [参考项目源码分析](docs/reference-analysis.md)：固定版本来源、许可与复用边界。

## 参与贡献与安全报告

欢迎通过 Issues 和 Pull Requests 改进方法、文档、合成样例和本地工具，流程见[贡献指南](CONTRIBUTING.md)。拟合并的原创贡献需要贡献者本人同意[贡献许可](CONTRIBUTOR-LICENSE.md)：贡献者保留版权，并授予项目方商业再许可所需的权利。真实的授权接收主体在发布前尚未确定；在此之前可以讨论和审阅，不合并需要授予权利的外部补丁。

贡献者的本地检查：

```powershell
python -B -X utf8 evals/release_check.py
python -B -X utf8 -m unittest discover -s evals -q
python -B -X utf8 -m compileall -q tools evals skills
```

仓库内的 CI 定义（`.github/workflows/ci.yml`）已配置 Windows / Ubuntu / macOS × Python 3.11 / 3.12 / 3.13 / 3.14 共 12 组跨平台矩阵运行同样三步；托管 CI 尚未在公开仓库中实际执行过，当前仅 Windows 下的 Python 3.11 / 3.13 / 3.14 在本机实测过。全量测试通常需要几分钟。

敏感问题按[安全报告说明](SECURITY.md)处理。私密报告渠道尚未设置，请不要在公开 Issue 里贴复现载荷、客户材料或凭证。

## 许可

项目原创内容采用 [PolyForm Noncommercial License 1.0.0](LICENSE)，属于源码公开（Source Available），不是 OSI 定义的开源。超出该许可允许范围的使用，需要事先取得书面商业授权，说明见[商业授权说明](COMMERCIAL-LICENSE.md)。个人身份不自动意味着商业用途免费；第三方材料仍适用各自的许可证。

授权主体和商业联系渠道由维护者在发布前填写，目前尚未设置。

---

如果这个项目帮你少走了弯路，点一个 [Star](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/stargazers) 方便以后回来。发现问题或有改进想法，请按贡献指南提 [Issue](https://github.com/duyunzhoudyz/dyz-patent-copyright-skills/issues) 或 Pull Request。
