# DYZ Patent Skills

专利、软件著作权／软件版权与技术标准的起草、分析及核对辅助，配套可追溯的本地工具。

**当前版本：`0.1.0a1`，拟发布标签 `v0.1.0-alpha.1`，尚未对外发布。** 六个Skill入口共享完整目录；11个能力域、83项目录入口的支持等级仍为 `synthetic_helper_only`。已有方法、内部候选生成与有限检查，不代表全球完整专业能力或正式办理通过。

原创内容采用 **PolyForm Noncommercial 1.0.0＋单独商业授权**，属于Source Available，不是OSI定义的开源。欢迎外部贡献，提交方式与权利声明见[贡献指南](CONTRIBUTING.md)和[贡献许可](CONTRIBUTOR-LICENSE.md)。发布范围、未完成检查及待维护者填写的信息见[发布说明](RELEASE.md)，版本变化见[变更记录](CHANGELOG.md)，敏感问题按[安全报告说明](SECURITY.md)处理。

## 五分钟开始

当前支持环境为 **Windows＋Python 3.11**，工具只使用标准库。先运行 `python --version` 确认实际是3.11；如果默认指向其他版本，以下命令改用已安装3.11解释器的完整路径。Python 3.14、其他系统和任意宿主未通过本版完整验证。可选PDF另需获准的本机Office／Poppler工具，不作为首次试用前提。

下载完整源码或可信完整包，保留 `tools/`、`skills/`、`references/` 及随包说明的相对位置。先从下面三个例子选择一个；首次输出目录须不存在，命令从完整根目录运行。

**文字任务，无需先填JSON：** 让支持文件读取的Agent实际加载 `skills/dyz-patent/SKILL.md`，再提出“只按给定技术材料起草内部工作稿，逐项列原文支持和缺口”。软件版权或标准任务改用下方对应入口。加载前确认材料可以进入该宿主的数据路径；本地工具不使云端模型离线。不要将一个Skill目录单独复制后当作自足安装包。

**查看工具目录与合成演练：**

```powershell
python -B -X utf8 -m tools list
python -B -X utf8 -m tools demo --synthetic --root . --output synthetic-demo.json
```

**生成并回验合成Word：**

```powershell
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack
python -B -X utf8 -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack --verify
```

演练只处理标明的合成示例，输出仍是内部候选。真实软件材料走下方单独的获准入口，不能把真实案件改标为合成。宿主自动发现与工具注册不由显式文件加载保证；实验性元数据检查器不是通用安装器。

## 首版使用限制

- 专利最终正文门禁只核有限句法和固定原文。原文含从属权项继承、公式、表格或其他未支持表达时，可能使有依据的候选仍被阻断；`blocked`不等于已经认定缺少原始支持。保持原件，只交标明未完成检查的内部工作稿。
- OA最终路径把答复论证与技术替换稿共同交给原申请支持门禁，尚未分别核验法律／程序／引证论证的依据。通常完整OA不能据此承诺最终放行；内部draft与法域专业审阅分开。
- 文档格式、有限语义检查、模型稳定性和专业审阅分别记录。工具`checked`、零issues、Word生成或PDF字面相同均不证明可提交、登记、认证或组织批准。
- 本版不提供真实提交、自动外发或操作系统级隔离。只读材料也须确认宿主模型、索引、日志及工具的处理权限。

## 三个专业子系统与共享基础层

| 子系统/层 | 职责 | 不替代的专业责任 |
| --- | --- | --- |
| 专利 | 全球检索、交底、可专利空间、权项/说明书/制图、核稿、审查答复、侵权/FTO和组合管理 | 软件版权登记判断、标准共识和发布批准 |
| 软件著作权／软件版权 | 权属与版本、真实源码/文档、交存登记、补正变更及软件版权争议材料 | 专利性、保护范围和不侵权结论 |
| 技术标准 | 标准体系研究、立项、术语/条款、试验验证、协调核稿、意见处理、国际采用、送审交接与修订 | 专利必要性认定、组织批准、产品认证；不是通用润色插件 |
| 共享基础层 | 材料/证据、检索连接、权限、术语/版本、差异、绘图/导出、审核记录和评测执行 | 不持有专业判定权；规则、通过条件和签核由各专业子系统负责 |

同一项目可复用经授权的证据，但三条业务的状态、版本、公开范围和交付物独立。标准公开前的专利保护审查，与标准专利声明/必要性/许可/FTO分析是两条独立交接；申请号不证明所有待披露内容已经获得申请支持，引用专利也不等于SEP或已获许可。编辑工具共享，但必须分别保护权项范围、软件事实和标准要求强度。

跨业务披露按受控基线、内容与申请支持映射、具体包签核、发送前复核、回执、变更重审和事件处置设计。审批绑定版本、接收对象、用途、渠道及有效条件；软件登记、外部审阅、服务商处理与公开标准各自授权。skill中的流程提示不等于技术隔离，指导模式与受控执行模式必须明确区分。

## 当前可运行入口

本版公开范围、支持环境和已知限制见[发布说明](RELEASE.md)。以下提供当前源码的运行入口；本地安装、模型任务和历史检查不代表当前版本已经整体通过。

运行工具使用Python 3.11标准库，无第三方运行依赖。普通文字任务先选下表的专业入口，只读相关方法；需要确定性检查或文件操作时再读对应工具契约。在包含完整`tools/`的仓库或可信本地包根运行：

```powershell
python -m tools list
python -m tools demo --synthetic --root . --output synthetic-demo.json
python -m tools.bundle --destination D:/dyz-local-bundle
python -B -m tools.bundle --verify D:/dyz-local-bundle --manifest-sha256 <包外保存的清单SHA256>
python -B -m tools.host_bridge --describe
```

结果文件与包目标须不存在，父目录须存在。本地包只复制固定白名单，包含六入口、共享工具、实际资源和许可；准确文件数及字节以本次清单为准。不带包外可信哈希的校验只证明内部一致，不证明来源、许可或专业通过。完整布局、按需加载、冻结和恢复见[完整包使用说明](skills/dyz-workbench/resources/package-use.md)。

- [共享工作台](skills/dyz-workbench/SKILL.md)：问诊、专业分流、版本依赖、补证责任与续接。
- [本地文件工具](skills/dyz-workbench/resources/host-bridge.md)：有界分段读取、按hash修改／复制、图片、装配、Word回查及有限保真核对；控制器接入与宿主注册分别验证。
- [获准本地软件材料](skills/dyz-software/resources/tools.md#软件成品链与集中采集)：software-intake以控制台集中采集、prepare-software生成内部准备包、build-software生成源码/说明/字段DOCX及可选PDF，绑定原图和实际物理页检查；请求读取前核权限。部分结果退出4，所有产物仍是内部候选，不是正式交存或专业批准。
- [标准五文书闭环](skills/dyz-standards/resources/tools.md#五文书闭环与本地入口)：v2原意见、决定、条款和说明派生五类Word，真实字节回验、默认质量扫描与内部确认失效；另有旧意见表显式转换、新副本及有损报告。真实组织模板和专业通过不由转换或文件生成推定。
- [文件装配](skills/dyz-rendering/resources/tools.md)与[编辑后Word回查](skills/dyz-rendering/resources/docx-readback.md)：按当前配方核包，优先定位差异、异常和必要原文；保留完整报告及未解释项。
- [原创研究示例](skills/dyz-rendering/resources/research-documents.md)与[读取范围生成及回验](skills/dyz-workbench/resources/reading-scope.md)：适用材料逐文件声明，读取记录不认证全文已读或专业结论。

实验性[宿主元数据检查器](skills/dyz-workbench/resources/package-use.md#7-当前源码的本地六入口元数据配置工具)绑定特定二进制，版本不符在启动前拒绝；新运行时须先取得同版资格。安装、元数据发现、模型实际读取、完整业务、重复稳定性和专业审阅分别验证，不能用本地旧版安装结果代替当前源码验证。

## 从任务开始

| 当前任务 | 入口 | 可交出的内部候选 |
| --- | --- | --- |
| 从技术材料起草或修改专利稿 | [专利](skills/dyz-patent/SKILL.md) | 技术事实、给定文献比较、权项／说明书、图示与支持反查 |
| 整理通知、答复、保护与权利问题 | [程序与权利](skills/dyz-procedure/SKILL.md) | 通知分诊、答复／替换稿、支持及程序影响、后续交接 |
| 整理软件版权材料 | [软件版权](skills/dyz-software/SKILL.md) | 范围与贡献、源码选材、操作／设计说明、同版字段及缺件 |
| 起草或修订技术标准 | [技术标准](skills/dyz-standards/SKILL.md) | 范围／术语／条款、验证计划、编制说明、意见与修订影响 |
| 核最终文件或处理导出缺陷 | [渲染与核稿](skills/dyz-rendering/SKILL.md) | 源—输出核对、正文／内部材料分离、显示与打印检查记录 |
| 续接项目、跨业务分流 | [共享工作台](skills/dyz-workbench/SKILL.md) | 已知事实、版本依赖、开放问题及接收角色便笺 |

按宿主支持的方式加载对应入口。可以从一个局部任务开始，例如“按给定原稿修正这一项，并列出受影响的正文和图”；已有事实不重复采集，未提供材料不补造。上表是使用导航；原24条边界提示已在实际宿主检查路由、读取和停止边界，结论限于实测提示与配置。

本地包可使用上表六入口和文件工具说明。源码仓库另保留可运行测试、合成夹具及CI定义，这些开发材料不随本地包分发。施工台账、阶段计划、竞品调研与历史模型答卷仅留在维护者本地，不作为公开使用的前提。

以下命令从仓库内已有合成专利示范生成可编辑DOCX、源行映射及独立内部说明，并回读该包：

```powershell
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack
python -m tools.documents --synthetic --root . --input skills/dyz-rendering/resources/document-example.json --output patent-review-pack --verify
```

`patent-review-pack`首次生成时须不存在。PDF是显式可选转换，需本机已安装LibreOffice；软件源码／说明和标准正文／意见表的完整命令见[文件工具说明](skills/dyz-rendering/resources/tools.md)。这些入口仅处理合成示范，不能将真实案件改标为合成材料使用。 另有[有限公开专利检索附录](skills/dyz-patent/resources/cn-gateway-search.md)：实际查询、公开版本/日期和逐篇比较分列；属于研究资源，当前通用run入口没有因此获得真实资料输入或联网检索能力；另列的prepare-software只开放上述受限本地软件准备。

## 与公开写作 Skill 的工程对比

本项目以三业务独立判断、共享证据及版本设施组织工作。以下对标以2026-11-02读取的固定提交为准，仅描述源码观察与有限示例，未进行同环境运行或写作效果排名。完整来源见[GitHub横向比较](docs/github-skill-comparison-20261102.md)及[固定版本来源索引](docs/github-skill-comparison-20261102-sources.json)。历史观察不等于本版可重复结果；本版已知限制见[发布说明](RELEASE.md)。

| 方向 | 代表项目已有的做法 | 本项目已有基础 | 历史证据与剩余项 |
| --- | --- | --- | --- |
| 专利 | [paper2patent](https://github.com/7toCR/paper2patent/tree/53d0a2d2cbd8db6de824dfed86aab1763caa7142)串联权项、图、DOCX/PDF和独立撰写说明；[patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill/tree/0b95b547f78c2a0dd0e4e71eb43a88841c99c936)提供多条入口路线 | 原文支持、逐文献比较、修改影响及程序交接方法；本地合成核对工具 | 已有有限公开检索、官方原件范围及逐篇比较，混合来源三版完整稿/图/Word/PDF与编辑反例；EPO摘要两查询及[两篇全文研究](skills/dyz-patent/resources/cn-epo-fulltext-study.md)已接[GW-1.2返工文件](skills/dyz-patent/resources/cn-gateway-delivery/file-bindings-v1.2.json)，区分确认/删除与分组可见性；优先原始内容、完整世界同族、官方状态及独立/专业验收仍待核 |
| 软件版权 | [SoftwareCopyright-Skill](https://github.com/Fokkyp/SoftwareCopyright-Skill/tree/1159f6d280783616e1247f768690eac97c1a3f6e)串联选材和文档；[software-certificate-skill](https://github.com/IvanCodesDev/software-certificate-skill/tree/ee7d4636f35210767adc0b5689f8678c68e6f7e6)关注真实截图及变化后重建 | 表达/权利/许可分流、源码选材及版本影响；CLI/API合成示范 | 已有1.2/1.3同版材料、真实GUI操作、功能变化重建/旧输入拒绝；新增逐文件表达与贡献、20字段来源、秘密方案和具体专业待审问题；真实权属与登记仍待核 |
| 技术标准 | [gbt-standard-docx-skill](https://github.com/zhangzhangco/gbt-standard-docx-skill/tree/a3af82bc790b0dcf9c2eb8c7123df46311da68da)提供DOCX模板、交叉引用及意见表工作流 | 条款与验证依据、意见/治理/修订及两路IP交接方法 | 已有两版正文/意见、1.1边界及状态链；新增[同作者双进程字节互通](skills/dyz-standards/resources/river-local-interop/verification.md)、混版拒绝/新进程作用域及异常控制，当前文件接旧目标；新增12项具体专业待审问题及交接分流，复用六对Word/PDF；独立产品互操作、适用时的持久化/并发、专业及组织格式仍待核 |
| 共同质量 | 部分项目提供检查脚本或评估方案，存在方案不等于已验证效果 | 固定候选、请求/响应留存、逐项评价与失败保全；CORE/LIFE依赖及有限事实关系／正文绑定 | 增加完整包只读校验、包外清单绑定及实验性本地元数据检查，补启动状态、错误脱敏、阶段保全与自有进程身份／资源计数；既有复制候选退出失败未关闭；另提供独立八文件工具及默认hash收据，模型注册／权限／数据路径仍须宿主提供。d23组合108次106通过、2失败保留，独立及专业验收待执行，不作效果排名 |

“工程完整度超过对标项目”是本轮建设目标，当前不作全面领先声明。后续对外介绍只写可链接到具体版本、产物和运行证据的差异；未实现项写为计划，专业签核与技术检查分别表述。第三方许可与复用边界继续见[第三方说明](THIRD-PARTY-NOTICES.md)，本轮对比不引入上游实现。

标准链已增加[既选River组合的来源与接口约束对照](skills/dyz-standards/resources/river-source-profile.md)，把完整读取的RFC、勘误争点、原创条款与合成输入逐项联系；协会申投诉来源、GB/T全文／许可缺口分别记录。它提供可复核的具体工程差异，不证明专业效果领先，也未将新来源并入正式稿或升级原83项支持状态。

当前标准示例已连接原创研究示例模式，完整重建1.0与1.1正文、各自编制/验证/意见和同版DOCX/PDF，来源类别与旧审阅状态分别保留。实际文字、唯一书签和全部10页PDF已核；该工程差异不证明完整GB/T符合性、互操作或专业效果领先。

## 设计与维护文档

- [全球能力蓝图](docs/capability-blueprint.md)：11个能力域、83个顶层能力ID、三专业分工与适配边界。
- [能力契约与覆盖矩阵](docs/capability-contracts.md)：输入、输出、责任和验收要求；规格覆盖不等于能力已实现。
- [跨子系统交接与披露审批](docs/disclosure-and-handoff.md)：权限、版本、签核、外发及事件处置契约。
- [实施路线与质量门槛](docs/roadmap-and-quality.md)：长期目标、依赖及验证边界，不把计划视为当前支持。
- [项目施工规范](docs/development-standards.md)：目录、技能、规则、代码与分层验证约定。
- [参考项目源码分析](docs/reference-analysis.md)：固定版本来源、许可与复用边界。

贡献与检查方式见[贡献指南](CONTRIBUTING.md)。本版83项能力仍为`synthetic_helper_only`；真实原始支持、权利链、组织要求、专业签核与跨平台等条件须分别核验，方法和示例不替代专业审阅。

## 仓库管理范围

Git管理面向GitHub分发的六Skill及必要资源、`tools/`、获准的`references/`、可运行测试与合成夹具、CI、使用／许可说明，以及`.gitignore`明确列出的稳定设计文档。Skill中的Word、PDF、图像等成套示例属于可运行资源，不能仅凭扩展名当作临时产物排除。

`.gitattributes`关闭自动换行转换，保留来源映射及合成示例绑定的原始字节。`.gitignore`采用根目录与`docs/`白名单；新增顶层文件或设计文档需明确加入公开范围。过程计划、施工台账、本地`AGENTS.md`、整个`竞品对比/`与`.references/`、`evals/workflows/`历史模型归档、`outputs/`、`tmp/`、本地配置和缓存保持本地，不随提交上传。不要用强制暂存绕过这条边界。

私人案件／标准项目资料应放在独立私人目录或被忽略的`private/`中；临时演练和生成结果统一放在`outputs/`或`tmp/`。不把客户源码、未申请交底书、证件、签章资料和受限标准全文放进公开仓库。Git忽略不是加密和访问控制；推送前仍须检查实际跟踪清单。

## 授权

项目原创内容采用 [PolyForm Noncommercial License 1.0.0](LICENSE)，超出该许可允许范围的使用需要另行取得书面商业授权。该模式属于 **Source Available（源码可用）**，不是OSI定义的开源。

个人身份不自动意味着商业用途免费；许可对部分机构用途有明确规定。第三方材料仍适用各自许可证，不被本项目许可替代。

## 专业与能力边界

技能提供有限的本地取证、结构化分析、起草、校核和交接辅助，不保证授权、登记、不侵权或标准获批。正式提交、公开征求意见、发布、签章、缴费、签约和涉及执业资格的行为须分别确认授权与资格。各法域、标准组织/类型/阶段的规则、数据服务、模板与实际输出需独立验证后，才可标为支持；文本核稿不等于产品认证。

公开skills不意味着可以公开收录标准全文、译文或图表；第三方标准资料的获取、云端处理、复制和再分发权限分别核实。标准用语、条件、例外、容差及试验依据不能因去AI味或去防御性写作而改变。

既有七个参考项目分析为静态检查，没有安装上游依赖、运行其脚本/测试、调用收费检索或实际提交申请。之后获授权实现的本地工具已运行合成AC/DG分支测试；当前检索续建仅证明对应本地确定性分支，文档一致性检查不证明业务门禁有效。专业签核与身份认证、官方格式、真实申请/登记/标准发布、真实出口、完整专业案件的宿主隔离和跨平台均未完成验证；原24条实际宿主边界观察不外推全部自动触发情形。技术标准及其他扩展规则仍需逐组合核验现行版本、资料许可和专业预期，不把既有专利/软著研究视为标准子系统的验证。
