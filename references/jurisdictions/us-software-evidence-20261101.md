# US软件版权登记与源码交存：适配研究证据

本文件是2026-11-01实际读取公开官方来源后的研究摘记，服务SW-01/02/03/05/07/08、WP-06及WP-10的美国计算机程序登记适配。它不是专业签核、实际表单操作或全球规则结论；未改原software-rules.json，也未接入规则选择器。案卷人物、合同、出版、AI贡献与秘密事实另行标为合成，不由这些法源证明。

核验方式为公开网页/PDF的文本读取；PDF位置以下用正文页码，非浏览器搜索摘要。2026-11-01打开Compendium首页仍标2021-01-28版为适用行政手册；eCFR页面显示Title 37截至2026-10-29、全Title末次修订2026-08-26，不能把全Title日期写成§202.20刚修订。没有审查全部2026判例、州法或后续机构个案，不声称这些来源穷尽所有有效规则。

## 来源、版本与使用边界

| ID | 一手来源与实际位置 | 本轮观察的版本/日期及性质 |
| --- | --- | --- |
| US-SW-R01 | [17 USC Chapter 1](https://www.copyright.gov/title17/92chap1.html)，§101的computer program、publication、work made for hire定义，§102(b)、§103(b) | 版权局当日法典展示，页面未给统一修订日；用于表达/功能、出版及衍生范围，不把网页读取日当法律生效日 |
| US-SW-R02 | [17 USC Chapter 2](https://www.copyright.gov/title17/92chap2.html)，§201(a)/(b)/(d)、§204(a) | 当日官方展示；作者、职务作品与权利转让分别判断 |
| US-SW-R03 | [37 CFR §202.20](https://www.ecfr.gov/current/title-37/chapter-II/subchapter-A/part-202/section-202.20)，(a)、(c)(2)(vii)(A)(1)/(2)、(d) | eCFR截至2026-10-29；权威但非正式法律印本，登记交存与§407 mandatory deposit分开 |
| US-SW-R04 | [Circular 61](https://www.copyright.gov/circs/circ61.pdf)，pp.1—4、尾页版本行 | REVISED 3/2021；官方公众指引；短程序、衍生版本、代码/手册/显示区别 |
| US-SW-R05 | [Compendium Chapter 700](https://www.copyright.gov/comp3/chap700/ch700-literary-works.pdf)，§721.7—721.9，pp.37—48 | Third Edition，页脚2021-01-28；计算机程序原创性与字段说明 |
| US-SW-R06 | [Compendium Chapter 1500](https://www.copyright.gov/comp3/chap1500/ch1500-deposits.pdf)，§1509.1(F)(1)—(4)，pp.29—35 | Third Edition，2021-01-28；实际当前章内为(F)，不是Circular 61沿用的(C) |
| US-SW-R07 | [Compendium Chapter 1900](https://www.copyright.gov/comp3/chap1900/ch1900-publication.pdf)，§1902、1904、1905、1908，pp.2—13 | Third Edition，2021-01-28；出版事实与申请人判断责任 |
| US-SW-R08 | [Compendium Chapter 1000](https://www.copyright.gov/comp3/chap1000/ch1000-websites.pdf)，§1008.3(B)—(F)，pp.19—24 | Third Edition，2021-01-28；在线保留副本、授权下载与仅展示/调用区别 |
| US-SW-R09 | [AI登记政策](https://www.copyright.gov/ai/ai_policy_guidance.pdf)，III—IV，pp.3—6 | 88 FR 16190，2023-03-16公布并生效；Statement of policy，非新设AI版权法 |
| US-SW-R10 | [AI报告Part 2](https://www.copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf)，Executive Summary p.iii、II.C/F | January 2025；[2025-01-29发布说明](https://www.copyright.gov/newsnet/2025/1060.html)确认发布日期；报告解释/建议不冒充法律修订 |
| US-SW-R11 | [Standard Application Claimant Help](https://www.copyright.gov/eco/help-claimant.html)，Basic Information、Transfer of All Rights、Transfer Statement；[Limitation Help](https://www.copyright.gov/eco/help-limitation.html)，Material Excluded、Previous Registration、New Material Included | 当日公开帮助页，无页面版本号；字段语义参考，未进入真实账户核验当前控件或字符限制 |
| US-SW-R12 | [Circular 30](https://www.copyright.gov/circs/circ30.pdf)，pp.1—4；[申请类型帮助](https://www.copyright.gov/eco/help-created.html)，Question 2 | 职务/特别委托分类与单一申请排除条件；本轮未确认Circular 30尾页修订号，不伪填版本；当日实际读取 |
| US-SW-R13 | [17 USC Chapter 4](https://www.copyright.gov/title17/92chap4.html)，§408、§409；[Compendium现行入口](https://www.copyright.gov/comp3/) | 官方法典/行政手册入口；登记不创设版权，申请/费用/交存和正式决定不是内部候选材料 |

上述美国联邦官方法律/行政材料仅作事实研究、短引与本项目自写中文归纳；按§105的美国政府作品一般边界使用，不将第三方引用、案例材料、网站标识或非政府作品一并声称公有领域。未整本转载、翻译或重新许可官方PDF。项目原创归纳仍按根许可；真实harbor-demo源码仍为项目PolyForm Noncommercial 1.0.0及单独商业授权，演练中的虚构权利转移不改变它。

## 已核、可用于本案的规则命题

1. **对象与新旧范围（R01/R04/R05/R11）。** 保护可版权表达，功能、算法思想、系统和操作方法不是本次登记主张。具体版本对应具体作品；已出版、已登记、公有领域及第三方所有的既有部分原则上排除本次主张。同一claimant拥有且从未出版/登记的旧材料有有限例外，不能默认所有升级都排除或都包括。衍生版本须有足够原创的新表达；改动净行数、版本号和功能增加本身不证明达到门槛。限定主张与交存选材是不同决定，排除旧表达不等于删去短程序中的旧代码。

2. **作者与claimant（R02/R11/R12）。** 雇员在职务范围内创作与独立承包人不同。特别委托不是付费就成work made for hire，还须核定法定类别及当时的签署约定；不能把普通独立软件合同自动塞入类别。非作者作为claimant须取得本次覆盖表达的全部版权，书面转让需权利人或有权代理签署；仅许可使用/修改/分发不等于全部权利转移。候选字段保留具体作者及转让依据，不用公司付款覆盖承包人作者。

3. **出版（R01/R07/R08）。** 查具体版本、授权者、可保留副本、分发对象/目的、日期和国家。版权人授权公众下载并留存程序副本，与仅调用服务器转换功能或观看展示不同；后一事实单独不证明程序出版。确实公众下载不能因网站叫“测试”便忽略。全球可访问网站也不直接证明唯一首次出版国家；本案须靠地域限制和真实演练分发记录。完成年、部署日、首次出版日及登记日分别记录。后补冲突事实须更新候选及审阅，不因源码哈希没变而沿用旧结论。

4. **字段（R05/R09/R11/R12/R13）。** 美国候选用Standard Application、Literary Work；具体title/version、author及其human-authored contribution、work made for hire、claimant/transfer、完成年、出版、Limitation of Claim与Note to CO分别填。计算机程序可用computer program/revised computer program描述，不用“algorithm”主张功能。仅在有原登记事实时填Previous Registration；不得造号。联系/认证字段无事实即指定补件责任人，不能替有权人认证。不要拿中国开发方式、60页或每页行数机械翻译成美国表式。

5. **普通短程序交存（R03/R04/R06）。** 本次版本源码通常首末各25页；整个程序≤50页应交全部并说明为完整代码，保留该版本版权通知页（如有），首页标题和版本。Python脚本按源码处理，不拿界面截图、命令清单或功能说明代替。源文件实际字节、去重原行与排版页数分别统计；没有实际排版不能报正式页数，短程序不补行、不复制片段凑50页。不自动把另写说明书并入代码登记。

6. **秘密路线（R03/R04/R06）。** 有真实秘密事实才评估该路线，并告知Office。短程序可采用全部源码中只遮秘密的方案，遮盖比例须小于未遮部分，且可见部分仍有可辨认的足量原创表达；不能用“3/173行<50%”替代比例/表达判断。不得遮掉只是旧版、第三方或AI生成但并非秘密的内容。R03短程序文字为≤50页；R04/R06该秘密选项写<50页，边界不同保留，本案远少于50页不依赖边界。公开的同一段不能仅靠内部“秘密”标签继续套用遮盖。无法满足时评估special relief，不假设已获准；不能声称登记交存是绝对保密的保险箱。

7. **AI与人类贡献（R09/R10）。** 逐段看人类对表达的控制、改写、选择/组合的事实，提示词、测试通过或接受输出不自动使未改AI代码成为人类原创。AI/工具公司不是作者。超过de minimis的AI生成材料明确排除；边界不明可如实说明并请求Office评估，不能自行给固定代码行数阈值。仍可准备确有人类贡献的材料，不能把含AI的整个作品一概否定。补证导致作者/主张改变时修订；未提交的本案不假装进入pending更正或补充登记程序。

## 本轮未核和读取失败

- 已实际读取上述官方文本；没有登录eCO、核验实时申请控件、费用、付款、文件类型限额、处理时长、提交回执或实际接受。外发前须由负责人员按目标系统当期要求复核。
- Chapter 700首次抓取超时，后以同一官方URL重试成功；不是零命中。猜测的help-certification.html、help-cert.html、help-pub.html未能获取，未用作依据。OLRC preliminary §101/103 URL返回404，本案法条使用已成功打开的版权局法典展示；不称OLRC逐节复核完成。
- 未核群组登记、CD-ROM、游戏、外国同时出版、专门mandatory-deposit豁免、特别救济实际接受、保密材料查阅个案、诉讼门槛/救济期限及全部州法。发现这些事实须另开对应研究，不能用本案覆盖。
- 未发现本轮所查官方入口已取代上述AI政策的登记指引；这只是检索范围内观察，不是“此后绝无变更”。2025报告不替代2023申请披露要求。

本研究可支持内部适配候选和逐项复核，不证明US组合稳定交付，也不提高83项catalog支持状态。
