# 第三方研究来源与复用边界

本项目研究了以下公开仓库。固定提交、检查范围和结论见 [源码分析](docs/reference-analysis.md)及[固定版本比较](docs/github-skill-comparison-20261102.md)。研究快照位于被主仓库忽略的`.references/`和`竞品对比/`；后者的阶段比较报告也仅留本地。源码仓库及运行包保留白名单内的原创来源分析和公开链接，不分发竞品快照、附带标准全文及第三方实现。忽略不改变本地原件或第三方许可，不构成安全隔离。新增来源另行核权；公开下载不推定获准再分发。

| 来源 | 本次本地许可文本 | 当前使用方式 |
| --- | --- | --- |
| https://github.com/handsomestWei/patent-disclosure-skill | MIT | 静态研究和出处引用 |
| https://github.com/Fokkyp/SoftwareCopyright-Skill | GNU Affero General Public License v3 | 静态研究；不复制进PolyForm NC发布包 |
| https://github.com/jaccen/AI-Copyright-Skill | MIT | 静态研究和出处引用 |
| https://github.com/handsomeZR-netizen/cn-patent-drafter | MIT | 静态研究和出处引用 |
| https://github.com/Obviously-Not/patent-skills | MIT | 静态研究和出处引用 |
| https://github.com/RobThePCGuy/Claude-Patent-Creator | MIT | 静态研究和出处引用 |
| https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep | MIT | 静态研究和出处引用 |

## 后续复用要求

- 引用思想、分析事实与复制源码/模板/受保护表达不是同一行为。复用前应记录具体文件、版本、来源与许可义务。
- MIT内容若实际进入发布包，必须保留要求的版权和许可声明；本项目限制不撤销上游原件的MIT授权。
- AGPL内容不能直接形成衍生实现后仅以PolyForm NC分发。需要时先另行获许可，或对独立组合方式及相应义务进行专门审查。
- 示例图片、文档模板、法规转载、论文、数据库内容和模型资产可能有独立条款，不能仅凭仓库根许可证推断全部权利。
- 被Git忽略不免除复制、使用和分发时的许可义务。
- 官方网站的链接和规则出处不代表官方认可、认证或背书。

本文件是研究来源说明，不是对将来引入的所有第三方组件的一揽子许可确认。本轮没有导入第三方实现。

## EPO Linked open EP data的有限研究数据

来源：European Patent Office，[Linked open EP data](https://www.epo.org/en/searching-for-patents/data/linked-open-data)，2026-11-03核对其公开数据许可及偶发小规模查询范围。原数据字段、英语摘要及所选申请／公开字段位于[cn-epo-search-record.json](skills/dyz-patent/resources/cn-epo-search-record.json)，继续适用[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，不改为项目仅非商用许可。文件保留来源URI、查询、取回时间、选择／日期转换及原响应哈希；本项目新增的是记录组织和有限比较，不表示EPO认可或背书。

上一摘要切片仅两次摘要索引查询及两次已知URI读取，没有复制EPO客户端／界面实现、整页HTML或完整专利文献进入包。数据许可不在此扩展到所有网页或PDF；原研究比较和查询组织另按项目许可处理。详见[访问及许可边界](references/jurisdictions/patent-epo-linked-source-20261103.md)。

2026-11-03后续[全文研究](skills/dyz-patent/resources/cn-epo-fulltext-study.md)按Publication Server REST读取两个指定版本，包内只保留原创分析与定位，不放原PDF／XML／附图。[全文研究记录](skills/dyz-patent/resources/cn-epo-fulltext-record.json)另选3次Linked data已知URI返回中的申请日／优先引用／同族等字段，原字段继续CC BY 4.0、署名EPO，保留原URI／日期表示及选择说明。它不替代优先文件内容、完整世界同族或当前法律状态核验，也不表示EPO认可本项目。

同日[优先／同族与版本续查记录](skills/dyz-patent/resources/cn-priority-family-record.json)的selected_original_fields另选EP3327589B1公开、EP17001923申请和简单同族60452341三次响应原字段；继续署名European Patent Office并适用CC BY 4.0，记录选择、原URI和响应SHA。B1原PDF／XML／附图及第三方网页全文不入包。原创版本比较、阅读范围、当前Word位置交接和第三方标识线索不意味着来源机构背书；不把B1出版、同族成员或第三方状态标签解释为当前权利有效或优先权成立。
