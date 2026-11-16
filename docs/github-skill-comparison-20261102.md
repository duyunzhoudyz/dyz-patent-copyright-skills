# GitHub 专利、软件版权与技术标准写作 Skill 横向比较

> 文中标为“仅本地”的施工记录、计划和评测归档不随源码仓库或运行包分发；它们不是运行依赖，历史结果不代表当前版本整体验证通过。

研究日期：2026-11-02（Asia/Seoul）。初次外部调研只形成本文、[来源索引](github-skill-comparison-20261102-sources.json)及施工记录。第1—8节保留调研时点的事实与建议；用户随后授权的工程落实见第9节及施工台账（仅本地：`implementation-progress.md`），不将后续实现倒写为当时已有能力。

## 1. 结论与比较口径

**下一阶段最有价值的提升是把已有专业方法稳定地变成可审阅、可修改、可复验的完整交付物。** 当前 DYZ 已有原始支持、权属/用途分流、条款验证、变更影响和内部/外部材料隔离等细致方法。不能再把这些已有内容列成“需要从零补齐”，也不能因篇幅更长就断言写作质量领先。

外部样本最值得研究的三个方向是：

- 专利：以来源支持映射连接权项、完整正文、可编辑附图、独立撰写说明和 DOCX/PDF，并用确定性检查辅助修改。
- 软件版权：从真实软件形成一致的申请事实、选材、用户操作说明、界面证据与最终文件，减少用户重复解释和手工拼接。
- 技术标准：保留组织模板样式、书签和交叉引用，从最终 DOCX 回读问题并输出可处理的修改意见表。

这些是**静态设计/工程证据的比较**。本轮没有让上游与 DYZ 在相同输入、模型和预算下作答，没有运行上游测试，不能据此给出“谁的专业写作最好”的实测排名。

### 样本选择

本轮结合 GitHub 仓库搜索和公开网页检索，按主题相关性、可见热度、独立实现特点选择 **11 个直接 Skill 样本、2 个邻近参考**。不是 GitHub 全量普查，也不是按星数证明专业水平。星数在本次会话通过 GitHub 仓库元数据读取；它属于整个仓库，不代表某个 Skill 的使用量或质量。

| 编号 | 仓库 | Stars | 本次固定提交（前12位） | GitHub 许可标记 |
| --- | --- | ---: | --- | --- |
| P1 | [handsomestWei/patent-disclosure-skill](https://github.com/handsomestWei/patent-disclosure-skill) | 12,626 | 0b95b547f78c | MIT |
| P2 | [7toCR/paper2patent](https://github.com/7toCR/paper2patent) | 704 | 53d0a2d2cbd8 | MIT |
| P3 | [RobThePCGuy/Claude-Patent-Creator](https://github.com/RobThePCGuy/Claude-Patent-Creator) | 207 | f855527c61ee | MIT |
| P4 | [handsomeZR-netizen/cn-patent-drafter](https://github.com/handsomeZR-netizen/cn-patent-drafter) | 63 | 612b3fd5bfe9 | MIT |
| P5 | [Obviously-Not/patent-skills](https://github.com/Obviously-Not/patent-skills) | 19 | a2e9cd1f4333 | MIT |
| S1 | [Fokkyp/SoftwareCopyright-Skill](https://github.com/Fokkyp/SoftwareCopyright-Skill) | 6,166 | 1159f6d28078 | AGPL-3.0 |
| S2 | [na57/chinese-copyright-application-skill](https://github.com/na57/chinese-copyright-application-skill) | 194 | ae8007f84cdd | 未识别 |
| S3 | [IvanCodesDev/software-certificate-skill](https://github.com/IvanCodesDev/software-certificate-skill) | 173 | ee7d4636f352 | MIT |
| S4 | [suling-fun/software-copyright-materials-skill](https://github.com/suling-fun/software-copyright-materials-skill) | 109 | 6c9e6e72d8af | MIT |
| T1 | [zhangzhangco/gbt-standard-docx-skill](https://github.com/zhangzhangco/gbt-standard-docx-skill) | 16 | a3af82bc790b | 未识别 |
| T2 | [HuangZhe-CN/guobiao-writing](https://github.com/HuangZhe-CN/guobiao-writing) | 0 | 930a79612c53 | 未识别 |
| A1 | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 55,633 | 5f2bc0341354 | MIT |
| A2 | [metanorma/metanorma](https://github.com/metanorma/metanorma) | 140 | 34e259b1f1c5 | BSD-2-Clause |

P1—P5 为专利；S1—S4 为软件版权；T1—T2 为技术标准直接样本。A1 是 ISO 证据准备 Skill，A2 是标准出版工具，单独作邻近参考。**没有找到足够证据支持“已有高星、完整成熟的技术标准起草 Skill 群体”这一说法**；不能拿 A1 的 55,633 个仓库星数当作标准写作 Skill 的热度。有限检索也不能证明其他项目不存在。

许可标记只用于来源筛查。S1 已读 LICENSE 为 AGPLv3；S4 已读 LICENSE 为 MIT，但其自述继承 S1 的 1.3 版本，尚未做历史逐文件追溯。T2 README 自称 MIT，但本次根目录只有 README.md 和 skill.md，未核到独立许可证；T1、S2 也未核到明确根许可证。本轮不复制任何上游实现或模板，未来复用仍按项目既有许可边界核查。

### 调研时点的本项目比较基线

以下是调研时冻结的 alignment-d12 比较基线，后续运行状态见第9节和施工台账（仅本地：`implementation-progress.md`）：

- 当前候选指纹为 `17a13f501476f84425250251655234fcdafa68335d549002e9d8061fba25520c`；119 份执行候选文件与129份包源清单是不同范围。
- 当前候选七案原28项均满足，B06-F01—F07在本候选关闭；执行通道已通过该配置预检。评分者仍是作者。
- 同版其余14案、历史三案、核心链重复、旧新对照、24触发及真实专业/宿主验收仍未完成；第6批未整体通过。83项仍为 `synthetic_helper_only`，14类真实组合缺口不升级。
- README 的部分当前摘要仍称“真实独立通道阻塞”，与上述较新台账不一致。本报告明确采用台账；该摘要同步列为文档维护项，不借本次研究改写历史评分或扩大验收结论。

## 2. 专利方向

| 样本 | 实际看到的长处 | 与 DYZ 的关系及可提升点 | 借鉴边界 |
| --- | --- | --- | --- |
| P1 patent-disclosure-skill | 主入口路由9类任务，交底、申请文件、案卷、检索、解读、地图和对照表有具体分工；最新提交增加点名海外时的检索/解读入口。[入口](https://github.com/handsomestWei/patent-disclosure-skill/blob/0b95b547f78c2a0dd0e4e71eb43a88841c99c936/SKILL.md)、[交底](https://github.com/handsomestWei/patent-disclosure-skill/blob/0b95b547f78c2a0dd0e4e71eb43a88841c99c936/skills/patent-disclosure/SKILL.md) | 值得学习任务完成时“实际交哪一份文件”和最短调用路径。DYZ 已有分流与按需资源，重点是验证真实宿主能否选对、读对、交全，而非再拆9个目录。 | 本次读到的海外入口不能推成全面查新、完整FTO或全球法域支持；未验证其在线服务可用性。 |
| P2 paper2patent | 论文事实表、权项规划、充分公开审阅、附图、申请正文与撰写说明分离，并有 DOCX/PDF 生成与检查脚本。[工作流](https://github.com/7toCR/paper2patent/blob/53d0a2d2cbd8db6de824dfed86aab1763caa7142/skills/paper2patent/SKILL.md)、[检查器](https://github.com/7toCR/paper2patent/blob/53d0a2d2cbd8db6de824dfed86aab1763caa7142/skills/paper2patent/scripts/check_patent_draft.py) | DYZ 已有支持链、后备层次、完整示范和保义编辑。最直接的差距是将这些中间成果装配成真实文件，并把未决事项集中成可操作的交接说明。 | “检查器通过”不能证明专业正确；固定载体权项、术语禁用和字数规则需按实际路线核实，不能直接套成全球规则。 |
| P3 Claude-Patent-Creator | 完整任务包含非专利文献、最强反证、缩限后的价值再判断、机器检查、独立视角审阅和停止投入的交付选项。[流程](https://github.com/RobThePCGuy/Claude-Patent-Creator/blob/f855527c61ee578b24f77cae99ef91eea80cafc6/skills/patent-application-creator/SKILL.md) | DYZ 已有反证、可检测性、成本和专利/秘密/公开策略。值得补的是在实际检索与每次范围收缩后，自动把“技术差异—支持—绕开—商业取舍”重新连起来。 | 上游对扫描覆盖、临时申请可交付性及法律效力的措辞不能直接沿用；付费检索、历史镜像扫描和代理并行不由本次研究授权。 |
| P4 cn-patent-drafter | 四类 LaTeX 骨架、章节文件映射、段号与局部修订入口清晰。[入口](https://github.com/handsomeZR-netizen/cn-patent-drafter/blob/612b3fd5bfe947faa2c0b44b0aa7265e0960e01c/SKILL.md) | 可借鉴章节定位和统一变量驱动的版式维护。DYZ 更需要输出模板的实际验证，不需要复制一套强绑定本机路径的目录约定。 | 其要求无实现先实现再写，以及把实现变量直接写入实施方式，不适合作为普遍起草前提；规则版本自述未由本轮核验。 |
| P5 Obviously-Not/patent-skills | 将代码候选抽象为机制，区分工程独特性、产品核心程度与防御性，提供快/深扫描路径。[入口](https://github.com/Obviously-Not/patent-skills/blob/a2e9cd1f433398267b4daf6a03a4c23d5d7bbc52/code-patent-scanner/SKILL.md) | 可借鉴快速候选摘要与扫描范围披露。DYZ 已有机制分析和商业取舍，宜改善结果呈现与实际覆盖记录。 | 自定义分值和阈值没有本轮校准证据，不能替代专利性判断；不能照搬默认排除测试代码等策略而漏掉技术证据。 |

专利最值得做的三个具体改进：

1. **让支持链贯穿到最终文件。** 每条权项与实施例、图节点、来源位置、待补项关联；修改一个限定后定位真正受影响的正文/图，而不是再次输出整套通用审阅清单。已有方法应接到交付装配层。
2. **把检索结果做成可复核证据。** 既有查询/覆盖记录继续保留，增加实际获取的文献版本、段落/图位置与原查询关联；非专利材料也要有日期和来源层级。网络失败、只得摘要和未执行不能变成“未见公开”。
3. **在收窄后重新解释取舍。** 已有保护策略方法足以承载，不新造总分：具体说明改后还覆盖什么、怎样绕开、哪些要素可观察，以及为什么仍值得推进或应停在内部研究。

其中第2项涉及真实来源接入，第1项涉及输出工具，均属于后续实施建议；本轮没有进行真实专利检索或生成申请文件。

## 3. 软件著作权／软件版权方向

| 样本 | 实际看到的长处 | 与 DYZ 的关系及可提升点 | 借鉴边界 |
| --- | --- | --- | --- |
| S1 SoftwareCopyright-Skill | 业务理解、申请字段、源码选择、截图方式、Markdown到Office文档形成具体流程；确认脚本绑定内容指纹。[入口](https://github.com/Fokkyp/SoftwareCopyright-Skill/blob/1159f6d280783616e1247f768690eac97c1a3f6e/software-copyright-materials/SKILL.md)、[确认脚本](https://github.com/Fokkyp/SoftwareCopyright-Skill/blob/1159f6d280783616e1247f768690eac97c1a3f6e/software-copyright-materials/scripts/confirm_stage.py) | DYZ 已有字节映射、用途权限和变更失效。可学习把事实确认、源选择、手册和输出校验贯通，避免每步重新抄一份字段。 | 当前 LICENSE 是 AGPLv3；不得按旧索引MIT复制。页面导向、补足目标页数及多次强制确认也不宜成为我们的通用流程。 |
| S2 chinese-copyright-application-skill | 申请表、源码文档、用户手册、设计说明四类产物一目了然，使用路径短。[入口](https://github.com/na57/chinese-copyright-application-skill/blob/ae8007f84cdd652762d346ffc1bb3a76c0965446/SKILL.md) | 值得学习首屏交付说明：用户不用先理解内部能力ID即可知道能拿到什么。DYZ 的范围/权属和不同产品形态方法较细，交付介绍可以更简洁。 | 占位符全替换不等于事实齐备；源码行数和固定分页规则不能替代路线核验。未核到明确根许可证。 |
| S3 software-certificate-skill | 一次集中采集不能可靠推断的事实；真实截图与来源映射；实际DOCX/PDF、分卷连续性、版本变化后局部重建。[入口](https://github.com/IvanCodesDev/software-certificate-skill/blob/ee7d4636f35210767adc0b5689f8678c68e6f7e6/SKILL.md) | 对 DYZ 最有参考价值的是 GUI 软件完整样板和从源到最终页的可追溯装配。我们的现有核心示范偏CLI/API，不能据此认为真实GUI链已验证。 | 其默认只保留正式文件、临时内部证据的保管方式不能照搬；固定页面目标、比例配额与推断优先级须另审。 |
| S4 suling-fun 派生版 | 明确README和实现可能冲突，要求核对按钮文案、数据流和真实操作视频；展示不同文档后端的依赖与限制。[入口](https://github.com/suling-fun/software-copyright-materials-skill/blob/6c9e6e72d8afce7aaccc9831ccd645a6ae2ccb16/SKILL.md) | DYZ 已要求正文回源；进一步可让手册每个操作段落对应实际状态/截图，而非只有一张笼统来源表。 | 它是S1的派生方案，不能算独立重复验证。全部去注释等做法是上游规则主张，本轮未做适用性核验；其官网提交流程不在我方本次范围。 |

软件版权最值得做的三个具体改进：

1. **建立贯穿产物的同一份已确认事实记录。** 复用现有CORE版本/权限设施，把名称、版本、权利人、软件范围、源清单、界面证据、表单和页眉连接起来；未知字段保持未知。这里的差距是实际生成链，不是再添加一段“保持一致”的文字。
2. **补一个真实GUI操作文档切片。** 在另行具备获准公开/合成软件与运行环境后，覆盖正常操作、错误提示、权限差异和恢复路径。按钮文本及截图必须对应同一构建；无GUI的CLI/API/嵌入式继续按其自身证据组织。
3. **按最终排版结果验收。** 检查长行折行、真实页数、前后范围、页眉版本、最后原行和手册目录，不把原文行数、显式分页符或文件扩展名当最终PDF证据。

S3仓库确有[浏览器E2E测试](https://github.com/IvanCodesDev/software-certificate-skill/blob/ee7d4636f35210767adc0b5689f8678c68e6f7e6/tests/test_browser_e2e.py)和[源码分卷E2E测试](https://github.com/IvanCodesDev/software-certificate-skill/blob/ee7d4636f35210767adc0b5689f8678c68e6f7e6/tests/test_source_split_e2e.py)，但分别受 `RUN_BROWSER_E2E`、`RUN_DOCUMENT_E2E` 环境变量控制。本轮只静态读取，**未确认它们在本机或上游当前CI中成功运行**。这说明我们可以学习其验收对象，不能直接引用其“通过”作自己的证据。

## 4. 技术标准方向

| 样本 | 实际看到的长处 | 与 DYZ 的关系及可提升点 | 借鉴边界 |
| --- | --- | --- | --- |
| T1 gbt-standard-docx-skill | 模板与profile、条款树、书签/REF、最终DOCX审阅、修改意见表及引用核验提示。[入口](https://github.com/zhangzhangco/gbt-standard-docx-skill/blob/a3af82bc790b0dcf9c2eb8c7123df46311da68da/SKILL.md)、[DOCX审阅器](https://github.com/zhangzhangco/gbt-standard-docx-skill/blob/a3af82bc790b0dcf9c2eb8c7123df46311da68da/scripts/review_gbt_docx.py) | 这是最直接的工程参照。DYZ 已有条款语义、验证矩阵、治理和采用方法；可补“写入模板—重排—回读—定位问题—修订输出”的实际文档链。 | 未核到明确许可证，内含标准知识材料的使用权不能推定。其入口明确目录/复杂域刷新限制，不能写成全自动Word排版已解决。 |
| T2 guobiao-writing | 按方法类、术语类、技术要求类组织章节，并列项目建议/申报材料，便于从题目走到初稿。[全文入口](https://github.com/HuangZhe-CN/guobiao-writing/blob/930a79612c5342612889b2ac256a73bace871447/skill.md) | 可借鉴按标准类型选写作骨架。DYZ 已有接口和测量专题，未来可补术语型标准的概念关系与定义完整样板，避免只靠统一条款表。 | TC279、资格、时点、文件清单等内容有明显场景限制；不能变成通用国标条件。本次0星，属于主题匹配样本，不称知名成熟项目。 |
| A1 iso-standards-readiness | 受控文件、执行记录、来源版本和缺口分开，限定证据准备职责。[入口](https://github.com/K-Dense-AI/scientific-agent-skills/blob/5f2bc0341354fd5590aef76a533ada1e1e5b4e62/skills/iso-standards-readiness/SKILL.md) | 可参考证据状态和角色说明的呈现。DYZ已有类似区分，不需要引入新的ISO认证业务。 | 面向管理体系/实验室准备，不是技术标准正文起草；整个仓库热度不能移植为该Skill热度或认证能力。 |
| A2 Metanorma | 以语义模型支持不同标准组织的扩展和出版表示。[README](https://github.com/metanorma/metanorma/blob/34e259b1f1c568f3b9e032d935e51c1fcf9d19c8/README.adoc) | 可研究“专业语义模型与出版格式分开”的方向，避免每个组织复制一套判断逻辑。 | 它是工具体系，不是写作Skill；本轮只读架构介绍，不验证输出，不建议立即引入Ruby依赖或替换现有标准库技术栈。 |

技术标准最值得做的三个具体改进：

1. **类型化正文骨架。** 方法类突出试样、设备、步骤、计算和报告；术语类突出概念关系、定义、同义/弃用词；接口类继续使用现有字节/状态/异常方法。组织/阶段模板单独适配，不能把某个TC的申报规则塞进公共正文。
2. **编辑后的最终文件反查。** 将稳定条款ID映射到Word段落、书签、表图和页码；改号后意见、验证项和引用仍能找回原条款。问题输出包含原文、位置、建议、理由和待决定者。
3. **引用状态与技术影响并列。** 既有引用版本方法继续使用；将待核项从正文提取成实际清单，并在取得来源后更新证据。T1的[引用脚本](https://github.com/zhangzhangco/gbt-standard-docx-skill/blob/a3af82bc790b0dcf9c2eb8c7123df46311da68da/scripts/check_normative_refs.py)实际主要是本地分类与联网核验提示，没有执行官方版本查询，不能称它已经解决“现行有效”核验。

## 5. 哪些已有，哪些才是真差距

| 维度 | 当前DYZ已有内容 | 本轮判断的真正提升点 |
| --- | --- | --- |
| 原始材料到专业正文 | 三核心链、专题方法、完整合成示范 | 证明新任务中稳定交出全文，降低只交提纲/问题表的失败率 |
| 权项支持、权利范围、条款验证 | 已分别建立，专业责任分开 | 贯穿实际文件和编辑后的回读，不再复制方法段落 |
| 内部审计与拟外发正文隔离 | 六Skill已有要求，七案原28项复验满足 | 在导出/装配时验证附件、批注、隐藏内容和输出范围 |
| 版本变化与审核失效 | CORE/LIFE工具、专题与多阶段示范已有 | 验证最终DOCX/PDF/截图的局部重建及证据保管 |
| 少问问题、按任务加载 | workbench和三业务入口已有 | 实测问题数、无必要追问、资源实际读取与交付时间 |
| Word/PDF及模板 | 当前渲染资源明确不等于Word排版/官方格式验证器 | 最明显的工程补足点：可编辑文件、真实转换、逐页检查 |
| 检索来源与覆盖 | 本地确定性状态、查询计划与报告已有 | 获准真实来源的取得、定位、失败恢复与证据装配 |
| 质量证明 | 当前七案有独立文字执行，作者评分 | 完成既定剩余关卡后，再做可归因的旧新对照 |

依据：[专利核心方法](../skills/dyz-patent/resources/cn-core-method.md)、[保护策略方法](../skills/dyz-procedure/resources/protection-strategy-method.md)、[软件材料方法](../skills/dyz-software/resources/cn-core-method.md)、[标准核心方法](../skills/dyz-standards/resources/cn-core-method.md)、[渲染工具范围](../skills/dyz-rendering/resources/tools.md)、[共享入口](../skills/dyz-workbench/SKILL.md)。

尤其不要把“增加商业价值分析”“增加原文支持表”“增加变更失效”“拆开正文和审计”重新列为缺失功能。这些已经写过；需要的是完成实现和验证，而非继续堆叠同义要求。

## 6. 建议优先级与可验收成果

下表是研究建议，不另立工作包或授权。R1沿用原计划，其余实施应在原冻结候选验收衔接后明确切片；不以新增功能替代当前验收。

| 顺序 | 建议与归属 | 预期可审阅成果 | 实际验收应观察什么 |
| --- | --- | --- | --- |
| R1／最先 | 按既定8.8完成当前候选余下验证；WP-10、LIFE-04 | 同版其余14案、历史三案，再接8.5的重复/对照/触发 | 七案不重复算新样本；冻结输入、实际加载资源、完整返回、评分者与失败均可追溯 |
| R2／第一批工程候选 | 专利完整包装配；DRAFT/FIG/REVIEW、CORE-07 | 一份有支持映射的完整专利内部稿，含可编辑图、正文DOCX/PDF与独立撰写说明 | 源码/事实至各段及图可追；无编造参数；真实渲染；正文不混入内部策略 |
| R3／第一批工程候选 | 软著同事实记录生成与GUI样板；SW-01—05、CORE-06/07 | 同一软件版本的表单候选、源材料、操作说明与截图关联 | 名称版本改一次后相关文件一致；源码最后原行、长行、实际页数可回查；没有运行的操作不写已运行 |
| R4／第一批工程候选 | 标准模板及最终DOCX回读；STD-04/05/07/11/12、CORE-07 | 现有接口/测量示范的一份可编辑标准稿与修改意见表 | 条款重排不丢稳定ID；引用/书签/图表可解析；条件、例外、强度、数值不因排版改变 |
| R5／贯穿前三项 | 复用共享质量设施做实际工件检查；REVIEW-07、CORE-06/07 | 固定源/产物/渲染环境/观察范围的证据包 | 缺截图、旧版PDF、目录未刷新、隐藏批注和内部附件误入能被发现，未经检查不写通过 |
| R6／随后 | 专利真实检索证据闭环；SEARCH-01—06、WP-05 | 一个限定来源/语言/日期范围的可复核报告 | 区分摘要/全文、专利/非专利、零命中/失败/未查；记录来源定位和停止原因，不扩成充分查新保证 |
| R7／随后 | 标准类型化完整示范；STD-02—06、WP-07 | 在已有方法/接口稿之外补明确需要的术语型样板 | 定义非循环、概念边界清楚、术语前后一致；不得从无证据需求造阈值或组织批准 |
| R8／在真实宿主验收中 | 交付体验与最少追问；六Skill入口、WP-03/10 | 可直接使用的三类入口与连续修订演示 | 已知事实不重复问；局部任务不展开全生命周期；最小充分资料下能交正文；记录实际读取/耗时/返工 |

优先完成R1，再从R2—R4中选择一个已有场景形成纵向交付切片，R5随该切片验证。不要同时建设三个新后端，也不要直接导入所有上游依赖。R6/R7不应成为重新扩张领域、延后当前验收的理由。

若要证明“借鉴后确实更好”，可参考P2的[评估方案](https://github.com/7toCR/paper2patent/blob/53d0a2d2cbd8db6de824dfed86aab1763caa7142/evals/README.md)，但优先沿用本项目既有深化与验收计划（仅本地：`skill-workflow-writing-plan.md`）：同模型/输入/预算、完整版本资源、重复运行、随机A/B标签和必要的位置互换；分别评忠实度、专业推理、完整正文、交付工件、变更影响及用户负担。上游存在评估方案不等于已经发表了可重复的效果证据。本轮没有增加评测分母、运行次数或“通过率”。

## 7. 不应引入的退步

- 不把一项自定义总分、模板检查或文件生成成功改写成可授权、可登记、符合标准或组织认可。
- 不为凑页数增加无关源码、重复段落或截图；也不按统一前端比例替代软件对象和真实表达范围。
- 不把“正文干净”理解成删除内部事实、支持、授权和历史证据。输出分离与受控留存应同时成立。
- 不照搬强制安装、换浏览器、自动提交、自动公开或每阶段重复询问。已有授权和本机浏览器政策继续适用。
- 不把标准全文、译文、模板素材或当前AGPL代码直接并入NC包；也不把“GitHub可见”当成再分发许可。
- 不借这次比较新增一批Skill目录、调整现有名称/description，或修改119份冻结候选和129源文件白名单。

## 8. 取证范围与交付限制

本轮经GitHub连接器读取仓库元数据、固定提交的25份入口/代表脚本/测试/许可文件，并查看相关目录；来源索引保存完整提交、Git blob SHA和固定链接，不复制上游全文进产品。公开检索用于发现样本，实际功能判断以仓库内容为主。

对旧七仓研究中重叠的项目，本轮重新核元数据和HEAD：P1已经从旧研究提交变为 `0b95b547f78c`，不能把旧快照当它当前的全部内容；S1、P3、P4、P5的固定HEAD与旧研究一致。原[2026-10-31参考分析](reference-analysis.md)及忽略的上游快照保持。

本轮没有安装、运行上游代码/测试、下载受限标准全文、执行真实申请/登记/发布、改变许可或写入Git。工程可运行性、官方规则适用、专业审阅和相同条件写作效果仍待各自验证。研究和文档检查的实际结果只记施工台账（仅本地：`implementation-progress.md`）。

## 9. 获授权后的工程落实

用户要求先完成内部工程验证。已有三业务同源文件链、可编辑图、软件同版GUI证据、标准书签与意见表，以及冻结输入、完整请求／返回、逐项评分及失败保全。d20/d21的参数、证明负担、否定动作和必要／充分方向失败及更正保持；d22文本108/108，但T005实际截断仍报全文，整体门槛未通过。d23补实际可读覆盖、分段重读与部分／失败记录，新专利36次34通过、2失败、0阻塞、组合108次106通过、2失败、0阻塞，宿主本批3通过、0失败、0阻塞，限定内部门槛未通过。详见施工台账（仅本地：`implementation-progress.md`）与当前逐次汇总（仅本地：`../evals/workflows/acceptance-d23-stability-summary.json`）。

本批于2026-11-03收尾，仍有未知状态补写与参数修改支持评估遗漏两项失败；已暂停同源抽样及扩域，不将有限通过项宣传为稳定完整能力。

历史题面／材料纠正、输入字节承接、对照更正、宿主全局上下文及专业限制继续披露；不将测试数、有限样本或不同输入的成绩换算成上游效果排名。上游25份固定文件的事实与许可判断保持，第2—4节继续提供代表项目及提交链接。源码观察、本机运行、同条件对照及专业验收分别表述。
