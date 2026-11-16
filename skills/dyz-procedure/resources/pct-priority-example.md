# 澜合PCT逐内容优先权与国家阶段内部工作示范

这是cross-region-d7开发首答，基于完整合成案卷一次作答；案卷内含初期记录与后到证据，但本次并非盲分阶段释放。方法见[工作方法](pct-priority-method.md)，规则ID和本次核验限制见[官方研究](../../../references/jurisdictions/pct-priority-evidence-20261101.md)。不构成真实法律意见、专业签核、独立验收或正式进入文件。原始case JSON逐字保存在正文后附录，包内无需依赖开发evals目录。

<!-- BEGIN D7-PCT WORK PRODUCT -->

# 澜合项目内部工作意见v1

出具基准：合成案卷截至2026-11-01 09:00，UTC+08:00。规则核验日为2026-11-01。本意见仅处理DE两份先申请经PCT进入CN发明、US371及EP地区阶段的日期、支持、材料与异常分流。所有企业、人物、案卷编号、收件及公开事件均为合成；SYN-DE-P1、SYN-DE-P2、SYN-PCT-R1均不是实际官方编号。

当前建议：优先在11月6日内部工作目标前完成EP和CN的进入准备，同时立即整理US漏费的完整原因材料供美国执业者判断。不要等待B2争点彻底消失才开始其他准备。A有P1原文依据，B1有P2原文依据；B2及C的本案候选有效日为PCT日。后到P2原件推翻了B2取得2024-08-20日期的原假设，但程序起点仍是主张中的最早日2024-04-15。CN普通30个月及US30个月已过；CN仍有需完成手续并缴宽限费的32个月路径，EP的31个月期限按已核闭馆表为2026-11-16。US不能借用CN的32个月。

## 一、实际文件链与事实可靠性

| 记录 | 本案实际内容与日期 | 使用方式 |
| --- | --- | --- |
| P1-FILED、REC-P1 | P1于2024-04-15在DE提交；完整D1—D3、权1、图1。文本内容哈希为`5a9128f55f6229645c9bc94a010296e30b2ab3f90d08cf02216f5deaba50df8e` | 可供A原始支持核对；回执内同哈希只绑定这份合成文本 |
| P2-WORKING | 2024-08-22形成的未提交工作稿，D3有10%／连续三次／失败清零。页脚明示内部稿，无对应提交回执 | 不能当成8月20日P2原件；文件名final不改变其性质 |
| P2-FILED-LATE、REC-P2 | 2026-10-30才取得；本案实际P2提交日为2024-08-20。内容哈希为`357f5b5909a49c77b90eeedc0111dbf125019a5de9fd048ad60d9944e46b4c49`，与REC-P2清单对应 | D1—D2可支持B1；D3是人工维护判断，明确没有自动阈值报警或连续计数 |
| PCT-FILED、REC-PCT | RO/IB记录国际申请日2025-04-14，英文原始文本D1—D6、权1—4、图1—2。内容哈希为`796820934ba9e224c45b68c027e4d884c3a5518e7df711d8a650539b29d99fa9` | 以这份实际文本组织三地材料；没有19／34条修改、补入部分、引用加入或提前处理请求 |
| REC-PCT优先权记录 | P1和P2两项主张均保留；2025-05-05已向IB提交两项认证副本；2025-10-16合成国际公布和ISR同时可得，ISA为EPO | 副本传送、公布及主张存在是程序事实，不证明每项内容都享有优先权，也不证明任何国家阶段已进入 |
| OWN-LANG | 同一德国公司始终为申请人，两名同一发明人；有2024-04-01申请权及优先权转让文字记录，公司称无更早申请／共同所有人／后续转让 | 在本合成事实下可继续分析；真实签章、权属及首次申请情况未查证，交对应法域人员确认，不能把文字记录写成真实权属登记通过 |
| EVENT-LOG | 截至11月1日，三地均未交进入包、未缴国家／地区阶段费用；US特别确认基本国家费未缴 | 这是本案给定未行动事实；没有查询真实官方系统。无缺件／放弃通知不延后法定触发 |

哈希按附录每份content字段的UTF-8、LF实际字节计算，仅用于版本一致性。它们既不证明收件机关真实性，也不证明有权签署、获得申请日或实质优先权。每份合成原件、旧稿和原错误备忘录均保留，不把新判断覆盖到旧记录中。

## 二、逐内容支持及候选日期

本表是基于给定完整文本的有条件实质意见。形式优先权主张、主体及首次申请条件仍需各地确认；以下没有把“材料已交”当法律审查已通过。依据为PCT-D7-02—04、EP-D7-01及US-D7-04。

| 内容／对应PCT权项 | 先申请支持与反证 | PCT原始支持 | 本案候选日期及理由 |
| --- | --- | --- | --- |
| A：环形腔、最低点通道、常闭阀、停泵开阀／运行闭阀；权1 | P1-FILED D1—D2、权1、图1逐项记载；P2与此无关 | PCT-FILED D2、权1、图1 | 2024-04-15。相同结构及控制关系有P1完整原文依据，未用后期稿添特征 |
| B1：相邻两组各8样本、平均绝对幅值比较、差值显示；权2 | P2-FILED-LATE D1—D2、权1、图1支持完整关系；P1 D3反而不采用声学／缓存 | PCT-FILED D3、权2、图2 | 2024-08-20。是P2而非P1中的内容，不能因为属于同一PCT而全部移到4月15日 |
| B2：B1加超过10%且连续三次、失败清零报警；权3 | P2真正原件D3是人工决定维护，无固定报警阈值、自动报警或连续计数；P2-WORKING D3虽有这些字句但未提交；P1亦无依据 | PCT-FILED D4、权3并引用权2 | 2025-04-14。对权3这一完整限定组合不能保留P2日；PCT有支持使它不是PCT后新增事项，却不能使它倒回P2日 |
| C：A+B1共享控制、开阀暂停且清两组、阀闭后填满两组再恢复；权4 | P1仅A；P2仅B1且未引用P1，无两者控制关系。两份资料分别有部件不构成组合披露 | PCT-FILED D5、权4、图2，D6解释清除前后样本混比；D5明示不要求B2报警 | 2025-04-14。该具体组合及顺序首次见实际PCT；不能拼贴两份优先权文件取得P1日或P2日，也不能把B2阈值擅加到C |

对A和B1可提出较早日期利益的有据意见；对B2、C不提出较早日期利益。不能由本表再推导所有独立／从属权项已符合各国全部实体要求。本案未提供国际检索对新颖性或单一性的意见，不补造“ISA已经认可”。

## 三、后到原件及公开资料怎样改变判断

10月26日MEMO-OLD依据未提交P2-WORKING，拟用2024-08-20对抗PUB-X。即使当时，正文页脚和缺回执已经不足以给出确定支持意见；10月30日的P2-FILED-LATE与REC-P2进一步明确推翻该假设。现在撤回的仅是“B2已有P2支持”的内部前提；保留P1对A、真正P2对B1、PCT对B2和C的已有证据。

PUB-X的公开证据是2025-02-03在公开演示中向60名参会者无保密条件发放同版宣传页，分发名单、收件记录和当日公共归档相互对应。公司2026-10-25才取得资料，取得日不是公开日。L1披露B1，L2披露B2及失败清零；L3明确没有压力腔、排液阀和排液控制顺序。

日期关系为：B1候选日2024-08-20早于PUB-X；B2的PCT候选日2025-04-14晚于PUB-X。就给定文本，权3的B1+B2组合与PUB-X L1—L2高度对应，失去P2日期假设后存在直接的新颖性障碍风险，应列为三地实质复核优先事项。不能再写“先申请日期足以排除该公开”。PUB-X是独立第三方自行开发的披露，没有从本案发明人取得内容；案卷也没有特定展览或其他例外事实，不能套申请人自身公开宽限来清除风险。

PUB-X没有A及C排液关系；不能据此直接说权1和权4均被同一页完整公开。B1在日期利益获得认可时可就这份较晚材料提出日期上的区分，仍须核其他现有技术。C的候选日较晚也不意味着它必然可授权：完整组合的创造性、支持、明确性及其他在先资料尚未评价。本意见不是全检索，也不作全案无效或可授权保证。

| 受影响产物 | 现在的处理 |
| --- | --- |
| 支持矩阵、优先权意见 | 生成v1，B2由旧假设P2日改为PCT日；原v0及其未签核状态保留 |
| 公开风险／权项取舍 | 把PUB-X L1—L2置于权3的直接风险项；技术负责人和各地专业人员书面比较保留争辩、依法删除或有原文支持的修改，不用未提交稿补原件 |
| CN工作译稿与其他申请材料 | 以PCT-FILED核对，准确保留D4／权3以及D5／权4的不同条件。实际旧中文译稿正文未提供，不能声称已逐句核完；只出下文校核锚点并交译稿负责人取得全文 |
| 三地进入意见和审批 | 更新日期依据、风险附件、拟申请包版本；原MEMO-OLD从未获批准，不能假造“旧批准已撤销”。将来审批须基于v1及真实完整包 |
| 无关事实 | P1/P2/PCT实际申请日、两项优先权仍被主张、英文公布和ISA身份不因B2变化而改写 |

三地准备暂以实际PCT英文原文为基础，不自动删权3，不改变优先权主张，也不把C重写成含B2的组合。是否删限权3是需要实质复核与具体授权的另一项决定，不应拖延其余材料准备。

## 四、可复算日期及期限表

按月计算采用相应日：起始事件当日不计入，但月期限落在末月同号日，不是再加一天，也不是每月30天。两项主张中最早日为2024-04-15，故国家／地区阶段程序以该日为起点。适用PCT-D7-01、05—06、CN-D7-01、US-D7-01／05、EP-D7-01／04及CAL-D7-01。

| 事件／计算 | 算式及名义日 | 地点、日历与调整 | 截至本案时点的含义 |
| --- | --- | --- | --- |
| P1实际提交 | REC-P1：2024-04-15 10:10，Europe/Berlin | 原件当地日2024-04-15 | 最早仍存在的主张日 |
| P2实际提交 | REC-P2：2024-08-20 09:30，Europe/Berlin | 原件当地日2024-08-20 | B1候选日，不另给整案新进入期限 |
| 实际PCT | REC-PCT：2025-04-14 15:30，Europe/Zurich | 原件当地日2025-04-14 | 比P1的12个月周年早一天 |
| P1的12个月周年 | `2024-04-15 + 12 months = 2025-04-15` | 周二；本案实际PCT已在此前完成，无需依赖假日顺延获救 | PCT未错过该优先权期 |
| P2的12个月周年 | `2024-08-20 + 12 months = 2025-08-20` | 周三；PCT同样早于此日 | 不触发本案优先权恢复 |
| CN普通进入 | `2024-04-15 + 30 months = 2026-10-15` | 周四，北京当地日。2026国务院假期表未列当日；本案普通结果不调整 | 已过，且未办理进入 |
| US基本费／所需副本关键期限 | `2024-04-15 + 30 months = 2026-10-15` | 周四，USPTO适用当地日；OPM的10月联邦假日是12日，15日非周末／表列假日，不调整 | 已过，基本国家费未缴 |
| EP进入 | `2024-04-15 + 31 months = 2026-11-15` | 名义日周日；EPO2026公告规定周末闭馆，11月16日周一未列附加闭馆，按Rule134(1)调至2026-11-16 | 尚可按普通进入路径准备 |
| CN附条件迟延进入 | `2024-04-15 + 32 months = 2026-12-15` | 周二，北京当地日；国务院表未列假期，按已核日历不调整 | 需完成规定手续和付宽限费，不是已经获延期 |
| EP ISR相关6个月 | `2025-10-16 + 6 months = 2026-04-16` | 周四，早于EP31个月期限；按Rule159及其引用的39／70处理进入时指定费、实审请求及费用 | 不能以ISR已公布很久为由漏掉进入时相应事项 |
| EP第三年费是否在进入前已到 | 国际申请第二周年为`2025-04-14 + 2 years = 2027-04-14` | 第三年到来在2026-11-16之后；按本案年序，第三年费不是本次进入前已经到期的项目 | 由EP经办按Rule51单独建后续年费记录，不按P1日期提前计算 |
| 内部工作目标 | 2026-11-06 | 项目约定工作日，非任何一地法定届满日 | 目标是备妥待审材料，不能写已提交 |

已核的常规假期表不证明未来或历史从无临时特殊公告。期限负责人应复核CNIPA／USPTO临时停办公示、EPO临时中断及实际渠道截止时刻；目前没有可用于主张额外顺延的具体事实，不能自行给CN／US增加日期。上表EP11月16日亦须在真实办理前重核新公告。所有法定结果以相关局当地日期为单位；本意见不把首尔／UTC+08:00工作时间直接转换成统一的24:00提交截止。

MEMO-OLD的2027-10-14来自国际申请日加30个月，起点选错；它既不能替代P1起算的30／31个月，也不能由B2、C只能依PCT日而获补正。当前没有优先权撤回或更正事实，本意见不拟通过撤回最早主张来改变期限。

## 五、中国：按32个月附条件进入准备

CN普通期限已过，建议当前准备32个月内进入发明国家阶段的具体包。第120条允许在缴宽限费后按32个月办理；它要求真实手续和缴费，不能把本意见当已取得延期。CN-D7-01的第121条第1—3项是本案关键进入条件，其他项目另有通知补正机制；内部仍应争取一并完整备妥，避免依赖补正机会。

| 拟包项 | 已填事实／候选内容 | 当前缺口与责任 |
| --- | --- | --- |
| CN-01进入声明 | 申请人Lanhe Fluid Systems GmbH；类型发明；PCT日2025-04-14；两项DE优先权分别2024-04-15、2024-08-20；与IB记录一致的两名发明人 | 案管按真实办理所需表单补完整地址等著录；本案SYN标识只能留在合成稿，不代真实国际申请号 |
| CN-02原始文本中文译文 | 从PCT-FILED D1—D6、权1—4及英文原始文件译出，不取P2-WORKING替代 | 取得既有说明书／权项工作译稿全文，由译稿负责人和陈工逐句核对；目前未提供其实际字节，不能称已核稿 |
| CN-03摘要／附图 | 补摘要中文；给图1—2全部英文标注对应中文，保留图号及标号关系 | 译稿负责人补齐，陈工核D5开阀暂停／清空／阀闭／补满两组的顺序。此类事项与第121条第1—3项进入要件分列，不能误称任何附图文字未译就必然尚未进入 |
| CN-04费用及委托 | 核申请、公布印刷、必要附加及宽限等实际适用费项与现行减免；优先权要求费另记进入日起两个月 | 中国代理候选核费项和资格，不凭公司规模默认减免；企业有权人另作代理委托、费用与行动批准。未付款、未委托 |
| CN-05优先权文件 | REC-PCT列两项认证副本已交IB；据第127条，本案不需把“首次补交原副本”列为已知缺件 | 经办核国际记录与传送可得性，保留两份真实原件的支持分析。副本手续不消除B2缺支持 |

CN-02、CN-03的校核锚点正文候选如下，仅供核译，不是已完成的全套中文申请文件：

“在自动报警实施方式中，仅当当前组的平均绝对幅值比前一组高出超过百分之十，且该条件在连续三次比较中均成立时，控制器发出报警。一次比较不满足该条件时，计数器清零。”对应PCT D4及权3；“超过”不改成“达到”，连续次数及清零条件不得删去。

“在组合监测站中，排液阀开启使控制器暂停声学比较、清空两个已存样本组并设置排液待完成状态。阀关闭后，控制器等待两组各八个样本的新数据完整写入，再清除该状态并恢复比较。该组合不要求采用百分之十的自动报警实施方式。”对应PCT D5及权4；不能遗漏等待两组或擅加B2。

CN内部进入说明候选：“拟以SYN-PCT-R1所标识的合成国际申请原始英文文本为翻译及进入发明国家阶段的基础，保留两项已主张优先权的著录。普通30个月已过，拟由有资格经办人在核定第120、121条手续和费用后准备32个月内进入；原件支持分析另见内部意见v1，B2不依P2主张实质日期利益。本说明不表示已提交、已缴费或官方已接受。”

实际进入日尚未发生，不计算虚构的优先权费绝对截止；收到进入回执后，由周主管记录进入日加两个月并核假日。若逾32个月未完成第121条第1—3项，第122条规定的效力终止分支不适用第6条第二款普通正当理由恢复；不能说以后随时付费可恢复。是否存在该条未排除的其他严格救济，需要对应事实，本案没有不可抗拒事由等证据，不作为当前兜底方案。

## 六、美国：漏基本费的恢复评估与371准备分开

本案给定国际公布在30个月前完成且可供USPTO取得，副本传送可依US-D7-01的IB公布规则处理；但是基本国家费明确未缴。依37CFR1.495(b)、(h)，在本合成事实下已经触发美国因漏基本费的放弃后果，不能因未见正式通知而继续当作正常30个月内进入，也不能以补宣誓或其他费用的机会为基本费自动延长。这里的法律后果判断不是对真实官方卷宗状态的查询报告。

现在可并行准备两部分：一是拟补作的371材料，二是供有权美国执业者判断37CFR1.137的完整事实。两者均未达到可直接签署／发送状态。

| 拟包项 | 具体内容 | 当前处理 |
| --- | --- | --- |
| US-01拟371识别及文本 | 明确以35USC371进入；申请人及两名发明人照OWN-LANG；英文PCT-FILED、REC-PCT和公布／副本记录；两项DE优先权数据 | 原文已经是英文，不从中文译回；经办核副本在实际系统的可得性，避免无依据重复递交 |
| US-02 ADS／宣誓 | 已有两人法定姓名、住址和通信地址的合成资料清单，尚无签署宣誓／声明 | 由美国经办核完整ADS及1.495(c)(3)条件。满足条件时可延期提供宣誓，不代表当前已满足，也不补救漏基本费 |
| US-03费用 | 基本国家费、检索费、审查费、实际适用附加费与1.137请求费分别核 | 4项权利要求和给定页数不自行产生高额超项假设；没有small／micro资格证明，不按减费率承诺金额。企业另批付款 |
| US-04完整延误证据 | EVENT-LOG全部原邮件、旧预算／录期依据、谁何时知道真实优先权、10月26日后等待原件的理由、10月30日发现错误后至拟可准许请求的每段行动 | 周主管保全原件，向财务、法务、研发分别补当时实际认识与决定；不删不利邮件、不倒填授权、不直接写成全程非故意 |
| US-05恢复请求候选资料 | 书面请求的案件识别、应补作行动、费用核定、整个延误原因及支持材料，由美国执业者判断；只有事实支持后才考虑有权人真实声明 | 未起草无依据的非故意签字段，未签署、未提交、未获准。若不能支持整个延误非故意，应明确该路线当前不具备可提交基础 |

拟给美国执业者的内部事实说明正文：

“本合成案的最早优先权为2024-04-15，基本国家费在按常规日历计算的2026-10-15前未缴。财务9月15日指示暂停付款，但同时要求遇必须保留的期限当日升级，明确不能只为节费丧失权利；期限助理9月16日把PCT日起算的2027-10-14误录为期限而未升级。研发在10月26日决定三地继续，同时建议等待原件；该时点已经晚于真实30个月日期，且尚无正式提交／付款授权。10月30日法务发现优先权和原件问题。请核各参与人在每一时段的认识、决定和其后延误，判断是否能真实证明整个延误非故意；所附邮件应完整保留。本说明不是申请人非故意声明。”

美国路径存在真实的判断分叉：若延误始终源于错误期限和误信仍有时间，财务指示中的保权条件也可能支持进一步调查；若查明有权人明知真实期限仍为成本或商业选择故意不付，或发现失误后又故意延迟救济，MPEP711.03(c)的非故意条件不能靠后来改变主意补足。当前证据不足以替当事人择定其中一支。暂停的是无依据的声明、正式请求和行动，不是事实归档、费用核查、371文档准备或紧急专业转交的内容起草。

PUB-X及其日期证据须随内部专业评估单交美国执业者核信息披露义务及处理时点；本次未研究完整IDS规则，未生成已提交IDS，也不把它仅存档后忽略。

## 七、欧洲：在31个月内按英文原文准备

EP尚未错过按已核日历计算的2026-11-16期限。建议依EP-D7-01—04准备普通进入；不等美国恢复结果，也不使用中国32个月口径。内部材料清单如下。

| 拟包项 | 本案填写与选择 | 必须落实的事项 |
| --- | --- | --- |
| EP-01进入及审查基础 | 拟用Form1200或适用进入文件；国际申请日2025-04-14，两项优先权日期照REC-PCT；审查基础为原始PCT-FILED说明书、权1—4、图1—2、摘要；无19／34条修改 | 经办填写实际著录及文件页码。本题仅SYN标识，未生成真实官方表单或已签署文件 |
| EP-02语言与代表 | 原文及公布为英文，是EPO官方语言，无另作德文／法文译文需求；德国主要营业地申请人并非仅因此被强制要求聘代表 | 企业可按既定意愿聘欧洲专业代表；未委托不得写其已代理。需要代表的其他真实资格事项由经办复核 |
| EP-03进入费用／实审 | 申请费及实际适用费项；ISR于2025-10-16公布，其六个月已于2026-04-16到，进入时列指定费、实审请求及审查费 | 准备书面实审请求并核实际金额／可减项，不把Form1200名称当全部手续完成 |
| EP-04检索与页数／权项 | ISA为EPO，按已核进入页面不需另缴附加欧洲检索费的分支处理；本案4项权利要求、给定页数不超过所列15项／35页阈值 | 核最终实际页数／权项及是否有其他适用费项；不因此声称全部费用已确定或免缴全部申请费用 |
| EP-05年费及后续 | 国际申请第二周年在2027年4月，第三年费未在本次31个月期限前到；无特殊展览证明事实，无提前处理请求 | 建后续Rule51年费记录；不按P1起算第三年费，不擅选提前处理 |

EP内部进入说明候选：“拟以合成国际申请SYN-PCT-R1原始英文文本作为欧洲阶段审查基础，暂不提出国际阶段修改或提前处理请求。现拟依Rule159准备进入、申请及指定费用、实审请求与相应费用，按EPO作ISA的事实处理附加欧洲检索事项。2026年闭馆公告使本案31个月名义日11月15日顺延至11月16日；具体渠道、实际文件、费用及新公告仍须经办发送前复核。权3的PUB-X风险见独立内部附件，不表示已获专利性认可。”

若未来实际漏交某项，部分遗漏对应继续处理，年费另有其救济分支，不能在尚未失期时预先写“已恢复”。本案不为可能的未来通知虚构送达日或继续处理绝对期限。

## 八、三类问题的恢复对象不同

| 问题 | 规则路径与地域区别 | 本案处置 |
| --- | --- | --- |
| 国际申请迟于12个月优先权期 | PCT-D7-06／07以失期后两个月内等条件为前提；CN指定局现接受恢复，WIPO表列unintentional且第128条有正当理由／进入日起两个月分支；US为unintentional，一般在适用30个月进入期届满后一个月内请求；EP为due care，RO仅按unintentional批准不当然有效，通常需在31个月期限后一个月内另请；提前处理另算 | PCT实际2025-04-14早于P1周年，不触发。本案不需要为了B2缺内容另造优先权恢复请求，也不能把国际阶段主张保留当恢复成功 |
| 国家／地区阶段普通期限漏失 | CN第120条32个月附条件迟延进入；US漏基本费转1.137恢复被放弃申请判断；EP需按实际遗漏区分继续处理／年费分支 | CN立即备妥迟延进入材料；US备事实和补作包、暂不作无依据非故意声明；EP正常进入准备 |
| 先申请没有B2或C披露 | 实质支持及日期问题，不是“错过一个期限”；WIPO ISPE6.05—6.10要求原先披露依据 | B2／C候选日用PCT日，重审PUB-X影响和权项选择；恢复制度不能补写历史原文 |

上述US、EP的一般指定局优先权恢复期限不是本案美国国家阶段恢复请求的截止日期。各类请求的条件、费用、理由、证据及审批分别处理，不写统一的“30个月不够就加两个月”。

## 九、可单独阅读的内部交接正文

收件角色：技术负责人陈工、期限负责人周主管、企业有权决策人；三地专业人员仅为拟转交对象，尚未委托、未外发。本交接主题为“澜合PCT v1：立即准备CN／EP进入及US迟延事实评估”。

请陈工于11月3日内部目标前确认A、B1、B2、C矩阵及PCT D4、D5译义。P2真正提交稿不含10%／连续三次／失败清零自动报警，旧工作稿不能作P2支持；请保留旧MEMO-OLD，并在技术意见中明确权3面对PUB-X L1—L2的风险和权4缺少同样披露的区别。本次尚无支持用新参数或新组合改写PCT，请勿为规避公开资料自行添加内容。

请周主管于11月2日内部目标前登记并双人复核P1起算的CN／US2026-10-15、EP名义2026-11-15及闭馆调整2026-11-16、CN附条件2026-12-15。旧2027-10-14记为起点错误的历史记录，不静默覆盖。核各局临时公告和实际电子渠道当地截止；本案未见可主张额外顺延的证据。CN取得实际进入回执后，再生成进入日起两个月的优先权费提醒。11月6日是备妥待审材料的工作目标，不是法律宽限，也不是延期授权。

请材料负责人于11月4日内部目标前取得现有中文工作译稿全文，补摘要及全部图中文字，并以PCT实际原文进行差异检查。CN准备清单CN-01—05，EP准备清单EP-01—05同步推进；EP普通进入窗口最紧，优先落实审查基础、进入费用和实审请求，CN不等待EP或美国结果。申请材料仅含目标局需要且经审核的内容，支持矩阵、PUB-X风险和财务／错录原因证据作为独立内部附件，不默认随申请正文外送。

请美国专业人员的内部对接责任人在11月2日目标前汇总US-01—05并提出委托审批：必须保留9月15日财务邮件、9月16日错误录期、10月26日决定／等待、10月30日发现及此后每段事实。请其判断1.137适用及整个延误是否可以真实认定非故意，并核需补作的371行为、费用和PUB-X的信息披露事项。若发现明知期限而故意拖延，不得仅换用“疏忽”措辞后签署。缺真实原因判断只阻塞恢复声明和请求，不阻塞材料保全或其他两地准备。

供有权人审阅的版本及附件目录为：本内部意见v1；附录11份原始合成材料及其content哈希；支持／公开风险表v1；程序日期表v1；本意见中CN-01—05、US-01—05、EP-01—05的填写事实与待办；待取得并核定的CN完整译稿、三地实际表单和费用清单；US完整原因证据及专业判断。尚未提供的译稿、表单、报价、声明和签字不冒充已存在文件；现在没有已批准可发送的独立manifest包。

请企业有权人基于v1分别决定三地策略及是否正式委托。任何真实外发／提交前，由案管固定各地完整文件字节和哈希，分别绑定具体接收机关或代理、用途、实际官方渠道／保密转交渠道、有效条件、必要专业签核、付款人及签署人，再取得对应批准。现有“研发想三地继续”不是这些具体授权。若原件、译文条件、权项、主体、规则或接收范围变化，重审关联意见及该包；其他已核事实保留。实际发送、收件、缴费和官方处理状态另记回执，不用传输成功替代进入完成；结果不明先核实，不重复上传或付款。

本次已完成的是内部支持与期限分析、三地具体准备／判断分流和交接文本。尚未完成真实委托、签字、缴费、提交、恢复、官方进入、专业签核或独立验收；既有83项覆盖及支持等级不由本示范升级。

## 规则定位

PCT-D7-01、03—07分别定位WIPO PCT Art.2(xi)、ISPE6.03—6.10、Rule80、国际阶段指南5.058—5.062、Rule49ter及2026-08-19恢复表；CN-D7-01定位2024-01-20施行的实施细则5、120—123、127—128；US-D7-01—05定位MPEP1893、2026 US国家章US.14／42、MPEP711.03(c)、213、710.05及OPM2026表；EP-D7-01—04定位Art.88、Rule159／134、EPO进入页面、2026 PCT指南F-VI3.7及OJ2025 A40；CAL-D7-01定位国办发明电2025年第7号转载。全部实际来源、版本、URL、获取失败与核验限制见随包的pct-priority-evidence-20261101.md。上述规则事实不代替本案实际文件或任何真实局状态查询。

<!-- END D7-PCT WORK PRODUCT -->

## 附录：冻结原始案卷JSON

以下代码块内部是冻结case.json的原始UTF-8／LF字节，未重排字段或重新序列化；该附录是本示范的输入，不是新增答复。原题含阶段叙述，不是本次开发执行的盲释放记录。

```json
{
  "schema_version": "1.0",
  "case_id": "CROSS-D7-PCT-01",
  "title": "澜合两次先申请与国家阶段漏期：完整合成案卷",
  "synthetic": true,
  "created_for": "cross-region-d7 development first response",
  "evaluation_status": "inputs_prepared_before_response_not_independent_professional_acceptance",
  "as_of": "2026-11-01T09:00:00+08:00",
  "target_offices": [
    "CN invention national phase",
    "US 35 USC 371 national stage",
    "EP regional phase"
  ],
  "task_prompt": "请依据完整合成案卷作内部工作意见：从两份先申请、后期误标稿、实际PCT版本和回执逐内容及组合判断可主张的日期利益；处理后到P2原件与公开资料的影响；分开实质优先权日与程序起算日，给可复算多日期表、三个目标地的具体准备／补救行动包和完整内部交接文本。说明哪些有条件意见现在可以做出、哪些只阻塞特定步骤。不得仅交模板或将所有结论推回待核；不得假造正式编号、官方状态、已提交、已签核或救济成功。三地未进入的实情以EVENT-LOG为准，不沿用MEMO-OLD。日期按当地规则和实际官方闭馆依据核验，工作提醒与法定期限分列。分析不是新颖性全检索或正式法律签核。",
  "requested_content_units": [
    {
      "id": "A",
      "location": "PCT-FILED D2 / claim 1",
      "description": "环形压力腔、最低点排液通道、常闭阀及停泵时开阀关系"
    },
    {
      "id": "B1",
      "location": "PCT-FILED D3 / claim 2",
      "description": "相邻两组各8样本、平均绝对幅值比较和差值显示"
    },
    {
      "id": "B2",
      "location": "PCT-FILED D4 / claim 3",
      "description": "超过10%并连续三次比较、失败清零的自动报警，包含B1组合"
    },
    {
      "id": "C",
      "location": "PCT-FILED D5 / claim 4",
      "description": "A+B1共享控制器及排液暂停、清两组、阀闭后补满两组再恢复的组合关系"
    }
  ],
  "phase_sequence": [
    {
      "stage": "initial",
      "available_artifacts": [
        "P1-FILED",
        "P2-WORKING",
        "PCT-FILED",
        "REC-P1",
        "REC-PCT",
        "PUB-X",
        "MEMO-OLD"
      ],
      "cutoff": "2026-10-26T12:00:00+08:00"
    },
    {
      "stage": "late_evidence",
      "available_artifacts": [
        "P2-FILED-LATE",
        "REC-P2",
        "EVENT-LOG",
        "OWN-LANG"
      ],
      "cutoff": "2026-11-01T09:00:00+08:00",
      "requirement": "在最终意见中明确初判与后到原件后的变化，不覆盖MEMO-OLD"
    }
  ],
  "raw_artifacts": [
    {
      "id": "P1-FILED",
      "title": "DE先申请P1的完整合成提交文本",
      "kind": "as_filed_specification_claims_and_figure",
      "language": "en",
      "available_at": "2026-10-26T09:00:00+08:00",
      "synthetic": true,
      "content": "SYNTHETIC RECORD — NOT A REAL PATENT APPLICATION\nTitle: Drainable pressure-sensing cartridge\nApplicant: Lanhe Fluid Systems GmbH (synthetic German company)\nInventors: Mara Lin; Leon Xu (synthetic persons)\n[D1] The cartridge has an annular pressure chamber, a pressure sensor connected to the chamber, a vertical drain channel from the lowest point of the chamber, and a normally closed drain valve in the channel.\n[D2] A controller opens the drain valve only while a pump is stopped. Liquid trapped in the chamber then drains through the channel. During pump operation the valve remains closed and the sensor measures chamber pressure.\n[D3] The cartridge may be mounted with the drain channel pointing downward. No acoustic transducer or signal buffer is used in this embodiment.\nClaim 1. A pressure-sensing cartridge comprising an annular pressure chamber, a pressure sensor, a drain channel extending from the lowest point of the chamber, a normally closed drain valve in the drain channel, and a controller configured to open the drain valve while a pump is stopped and to keep the drain valve closed during pump operation.\nAbstract. A pressure chamber can be drained during pump stop by opening a normally closed valve in a downward drain channel.\nFigure 1 (complete textual figure): chamber 10 -> lowest point 11 -> drain channel 12 -> drain valve 13; pressure sensor 14 connects to chamber 10; controller 15 connects to valve 13 and receives pump-state input 16.\nEND OF COMPLETE SYNTHETIC P1 FILED TEXT\n",
      "content_sha256": "5a9128f55f6229645c9bc94a010296e30b2ab3f90d08cf02216f5deaba50df8e",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "P2-WORKING",
      "title": "被内部误称为P2原件的后期工作稿",
      "kind": "unfiled_draft",
      "language": "en",
      "available_at": "2026-10-26T09:00:00+08:00",
      "synthetic": true,
      "content": "SYNTHETIC WORKING DRAFT — NOT FILED\nHeader: draft copied to case folder 2024-08-22; author file name P2-final-for-team.txt\nTitle: Buffered acoustic flow monitor\n[D1] An acoustic transducer samples a pipe wall. A controller stores a current block of eight samples and a preceding block of eight samples in a ring buffer.\n[D2] The controller calculates the mean absolute amplitude of each block and compares the two means.\n[D3] The controller emits an alarm only when the current mean exceeds the preceding mean by more than ten percent for three consecutive comparisons. A failed comparison resets the counter to zero.\nClaim 1. An acoustic monitor with a transducer, an eight-sample ring-buffer block comparator and the three-comparison ten-percent alarm condition of D3.\nNo chamber drain or drain/alarm handshake is described.\nFooter: INTERNAL REVIEW COPY, generated after the filing appointment; no filing receipt attached.\nEND OF COMPLETE WORKING DRAFT\n",
      "content_sha256": "99c00cae496aa8ffa9aa8a268fecd40a3e4d1018495fa2feeb7d98e6501e82e0",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "P2-FILED-LATE",
      "title": "10月30日才取得的P2完整合成提交原件",
      "kind": "as_filed_specification_claims_and_figure",
      "language": "en",
      "available_at": "2026-10-30T16:00:00+08:00",
      "synthetic": true,
      "content": "SYNTHETIC RECORD — NOT A REAL PATENT APPLICATION\nTitle: Buffered acoustic flow monitor\nApplicant: Lanhe Fluid Systems GmbH (synthetic German company)\nInventors: Mara Lin; Leon Xu (synthetic persons)\n[D1] An acoustic transducer samples a pipe wall. A controller stores a current block of eight samples and a preceding block of eight samples in a ring buffer.\n[D2] The controller calculates the mean absolute amplitude of each block, compares the two means and outputs the numerical difference on a maintenance display.\n[D3] An operator decides whether the displayed difference warrants maintenance. No fixed numerical alarm threshold, automatic alarm or consecutive-comparison counter is part of this embodiment.\nClaim 1. An acoustic flow monitor comprising a pipe-wall acoustic transducer, a ring buffer storing a current block of eight samples and a preceding block of eight samples, and a controller that calculates a mean absolute amplitude for each block, compares the means and displays their numerical difference.\nAbstract. Two consecutive blocks of acoustic samples are compared for maintenance inspection.\nFigure 1 (complete textual figure): transducer 20 -> sampler 21 -> ring buffer 22 [previous 8 | current 8] -> mean comparator 23 -> display 24.\nNo pressure chamber, drain valve, reference to P1, or drain/alarm control relationship occurs elsewhere in this complete text.\nEND OF COMPLETE SYNTHETIC P2 FILED TEXT\n",
      "content_sha256": "357f5b5909a49c77b90eeedc0111dbf125019a5de9fd048ad60d9944e46b4c49",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "PCT-FILED",
      "title": "PCT-R1完整合成原始提交文本",
      "kind": "as_filed_specification_claims_and_figures",
      "language": "en",
      "available_at": "2026-10-26T09:00:00+08:00",
      "synthetic": true,
      "content": "SYNTHETIC RECORD — NOT A REAL INTERNATIONAL APPLICATION\nTitle: Drainable pressure cartridge and buffered acoustic monitoring\nApplicant: Lanhe Fluid Systems GmbH (synthetic German company)\nInventors: Mara Lin; Leon Xu (synthetic persons)\n[D1] This application describes a drainable pressure cartridge, an acoustic monitor, and a combined monitoring station. The separate embodiments and the combined station are described below.\n[D2] The pressure cartridge has an annular chamber, a pressure sensor connected to the chamber, a vertical channel from the lowest point of the chamber, and a normally closed drain valve. Its controller opens the drain valve while the pump is stopped and keeps the drain valve closed during pump operation.\n[D3] The acoustic monitor has a pipe-wall transducer and a ring buffer containing a current block of eight samples and a preceding block of eight samples. The controller computes the mean absolute amplitude of each block, compares the means and displays their numerical difference.\n[D4] In an automatic-alarm embodiment, the controller emits an alarm only when the current mean exceeds the preceding mean by more than ten percent for three consecutive comparisons. If a comparison does not satisfy that condition, a counter is reset to zero.\n[D5] In the combined station, the cartridge of D2 and acoustic monitor of D3 share a controller. Opening the drain valve causes the controller to suspend acoustic comparison, clear both stored sample blocks, and set a drain-pending state. After the valve has closed, the controller waits for two complete new blocks of eight samples before clearing drain-pending and resuming comparison. The combined station does not require the ten-percent automatic-alarm embodiment.\n[D6] The clearing and refill sequence prevents the comparison of pre-drain and post-drain blocks. No tested numerical performance improvement is asserted.\nClaim 1. A pressure-sensing cartridge comprising an annular pressure chamber, a pressure sensor, a drain channel extending from the lowest point of the chamber, a normally closed valve in the drain channel, and a controller configured to open the valve while a pump is stopped and keep it closed during pump operation.\nClaim 2. An acoustic flow monitor comprising a pipe-wall acoustic transducer, a ring buffer storing a current block of eight samples and a preceding block of eight samples, and a controller configured to calculate the mean absolute amplitude of each block, compare the means and display their numerical difference.\nClaim 3. The acoustic flow monitor of claim 2, wherein the controller emits an alarm only when the current mean exceeds the preceding mean by more than ten percent for three consecutive comparisons, and resets a comparison counter to zero after a comparison that does not satisfy that condition.\nClaim 4. A combined monitoring station comprising the pressure cartridge defined in claim 1 and the acoustic monitor defined in claim 2 with a shared controller, wherein opening the drain valve causes the controller to suspend comparison, clear both stored blocks and set a drain-pending state, and wherein after valve closure the controller waits for two complete new blocks of eight samples before clearing drain-pending and resuming comparison.\nAbstract. Separate drainable pressure and buffered acoustic embodiments are provided. A combined station suspends and clears acoustic processing during draining and restarts it only after refilling two new blocks.\nFigure 1 (complete textual figure): chamber 10 -> lowest point 11 -> drain channel 12 -> valve 13; sensor 14 -> controller 15; pump state 16 -> controller 15.\nFigure 2 (complete textual figure): transducer 20 -> sampler 21 -> ring buffer 22 [previous 8 | current 8] -> comparator 23 -> display 24; valve-state signal 25 -> shared controller 15 -> suspend/clear/refill gate 26 -> comparator 23.\nEND OF COMPLETE SYNTHETIC PCT-R1 FILED TEXT\n",
      "content_sha256": "796820934ba9e224c45b68c027e4d884c3a5518e7df711d8a650539b29d99fa9",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "REC-P1",
      "title": "P1模拟收件记录",
      "kind": "synthetic_receipt",
      "language": "en",
      "available_at": "2026-10-26T09:00:00+08:00",
      "synthetic": true,
      "content": "SIMULATED RECEIPT — NO OFFICIAL STATUS\nLocal case reference: SYN-DE-P1 (not a real application number).\nReceiving office in the scenario: DE. Filing date recorded: 2024-04-15. Local receipt time: 10:10 Europe/Berlin.\nApplicant: Lanhe Fluid Systems GmbH. Submitted text: P1-FILED. Content SHA-256: 5a9128f55f6229645c9bc94a010296e30b2ab3f90d08cf02216f5deaba50df8e.\nComplete text and figure schedule acknowledged in this synthetic scenario. No earlier application for the same content is listed in the synthetic corporate register.\n",
      "content_sha256": "73c1fc58171f6d98504cb128578407eb1233be7a966dcc0754d9c41daef2ae95",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "REC-P2",
      "title": "P2模拟收件与迟到原件核对记录",
      "kind": "synthetic_receipt_and_retrieval",
      "language": "en",
      "available_at": "2026-10-30T16:00:00+08:00",
      "synthetic": true,
      "content": "SIMULATED RECEIPT AND RETRIEVAL — NO OFFICIAL STATUS\nLocal case reference: SYN-DE-P2 (not a real application number).\nReceiving office in the scenario: DE. Filing date recorded: 2024-08-20. Local receipt time: 09:30 Europe/Berlin.\nApplicant: Lanhe Fluid Systems GmbH. Actual submitted text: P2-FILED-LATE. Content SHA-256: 357f5b5909a49c77b90eeedc0111dbf125019a5de9fd048ad60d9944e46b4c49.\nOn 2026-10-30 the case archivist retrieved the complete filed text and checked its content against this manifest. The 2024-08-22 working draft is not the submitted file. The prior internal folder had only the draft. The earliest known application for the acoustic block comparator is P2.\n",
      "content_sha256": "10903f7eb6631afa622814479b9f8fb57c9c214e8ce0cd6f73f51f14b3205f14",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "REC-PCT",
      "title": "PCT模拟回执及优先权文件传送记录",
      "kind": "synthetic_receipt_and_bibliographic_record",
      "language": "en",
      "available_at": "2026-10-26T09:00:00+08:00",
      "synthetic": true,
      "content": "SIMULATED PCT RECEIPT — NO OFFICIAL STATUS\nLocal case reference: SYN-PCT-R1 (not a real PCT or WO number).\nReceiving office in the scenario: RO/IB. International filing date recorded: 2025-04-14. Local receipt time: 15:30 Europe/Zurich.\nApplicant: Lanhe Fluid Systems GmbH. Inventors: Mara Lin; Leon Xu. Language filed and published: English.\nSubmitted text: PCT-FILED. Content SHA-256: 796820934ba9e224c45b68c027e4d884c3a5518e7df711d8a650539b29d99fa9.\nPriority claims as filed and remaining in the scenario: SYN-DE-P1, 2024-04-15; SYN-DE-P2, 2024-08-20. All PCT designations retained; no withdrawal or priority correction. No later-filed part, incorporation by reference, Article 19 or Article 34 amendment. No early national processing request.\nSynthetic IB record: certified priority copies of both P1 and P2 received on 2025-05-05 and available for designated offices. This receipt does not decide substantive entitlement to priority.\nSynthetic international publication event: 2025-10-16, full PCT-FILED text and international search report made available together; no real publication number assigned. ISA in the scenario: EPO. No opinion on novelty or unity is supplied; no such finding may be invented.\n",
      "content_sha256": "3f090449e7a000d8f75fe2312941086cefa47a7f028c2814d7cd3a1e2c1da72f",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "PUB-X",
      "title": "独立第三方公开资料及日期证据",
      "kind": "synthetic_publication_and_access_record",
      "language": "en",
      "available_at": "2026-10-26T09:00:00+08:00",
      "synthetic": true,
      "content": "SYNTHETIC THIRD-PARTY LEAFLET AND ACCESS RECORD\nPublisher: Boreal Acoustic Works (synthetic independent company, no relationship to Lanhe).\nLeaflet title: Eight-sample alarm module; edition 2025-02-03.\n[L1] A pipe-wall acoustic transducer supplies a current block of eight samples and a preceding block of eight samples to a ring buffer. The module computes and compares the mean absolute amplitude of the blocks and displays their numerical difference.\n[L2] An alarm is raised only if the current mean is more than ten percent above the preceding mean on three consecutive comparisons. A nonqualifying comparison resets the counter.\n[L3] The device has no pressure cartridge, no drain valve and no suspend/clear/refill sequence tied to draining.\nAccess evidence in this synthetic scenario: the leaflet was handed without confidentiality terms to all 60 attendees at an open trade demonstration on 2025-02-03, 11:00 Europe/Berlin. The event organizer's distribution list and attendee receipt both identify this complete leaflet edition. A public archive captured the same content that day; retrieval by Lanhe occurred only on 2026-10-25.\nThe synthetic facts state that the publisher developed it independently and did not obtain it from the named inventors. No government-recognized exhibition, confidentiality breach, inventor disclosure exception, or other grace-period fact is supplied.\nEND OF COMPLETE SYNTHETIC PUBLICATION\n",
      "content_sha256": "ccf46a842ae53b677b072d4a3790ef371b0c56f305a49354bcdf3ae06e1a732f",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "MEMO-OLD",
      "title": "10月26日内部初步备忘录",
      "kind": "internal_unreviewed_memo",
      "language": "zh-CN",
      "available_at": "2026-10-26T12:00:00+08:00",
      "synthetic": true,
      "content": "合成内部备忘录v0，未签核、未外发：项目同事根据文件夹里的P2-final-for-team.txt，认为PCT权3的“10%且连续三次”在P2提交时已有，拟以2024-08-20对抗2025-02-03宣传页。尚未取得P2真实提交原件。预算表把CN、US、EP统一写成“PCT提交日起30个月=2027-10-14”；同事又称即使晚了，各地都可加费到32个月。以上是本案待核历史主张，不是题目给定法律结论或有效批准。\n",
      "content_sha256": "564d27ecfe2345239977e5a7e4afdab2e7101d17fa835b5dcfab3955abc2dbe7",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "EVENT-LOG",
      "title": "三地未进入与迟延原因的合成原始事件记录",
      "kind": "internal_event_log",
      "language": "zh-CN",
      "available_at": "2026-11-01T09:00:00+08:00",
      "synthetic": true,
      "content": "全部为合成事件，无真实账号查询。\n2026-09-15 10:00 Europe/Berlin，财务负责人邮件：“在我收到董事会国家选择前，暂停所有国家阶段付款；若会错过必须保留的日期，请法务当天升级。不能仅为节约费用主动丢失权利。”\n2026-09-16 09:00 Europe/Berlin，期限助理回复：“系统填的是2027-10-14，年内没有到期，我不升级。”其系统依据栏为“PCT提交日+30个月”，没有先申请字段。\n2026-10-26，研发负责人决定三地都继续，希望等P2原件齐后再准备。该决定未指定提交包、付款人、代理人或签字人，没有外发／提交授权。\n2026-10-30，法务助理首次见到两项优先权和P2原件，保留旧预算／邮件原件，没有改写原因陈述。\n2026-11-01，案管对合成台账和全部付款凭证核对：CN未提交进入声明、未缴任何国家阶段费、无进入回执；US未支付基本国家费、未提交371包、无国家阶段收件；EP未提交1200或其他进入文件、未缴地区阶段费。PCT副本已按REC-PCT国际公布，未见三地恢复请求、恢复决定、放弃决定或缺件通知。\n本题只允许内部工作；对US迟延是否完全非故意，财务暂停指示和错误期限录入均须保留。尚无有权人经完整事实核实后签署的非故意陈述。不得把未见正式放弃通知解释为美国30个月尚未生效。\n",
      "content_sha256": "7eb324ea6a086b5f2f38bdb67bef8d77f62ec503ea2d9905bac59a72c38aa2c4",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    },
    {
      "id": "OWN-LANG",
      "title": "申请人与材料清单的合成原始事实",
      "kind": "ownership_language_and_material_record",
      "language": "zh-CN",
      "available_at": "2026-11-01T09:00:00+08:00",
      "synthetic": true,
      "content": "合成企业事实：Lanhe Fluid Systems GmbH始终为P1、P2、PCT的同一申请人，注册地和主要营业地在德国；两名发明人Mara Lin、Leon Xu为企业员工。案卷有两人在2024-04-01签署给该公司的发明申请权和优先权转让文字记录，范围包括本案三个文本；只有合成文字记录，未进行真实签章或权属登记查证。企业称无更早申请、无共同所有人、无转让、无PCT92bis变更。\nPCT原文和公布均为英文，4项权利要求，文本总7页，图2页，摘要1页；没有序列表、生物保藏或遗传资源事项。原文完整存在。\nCN：公司选择发明专利。已有中文说明书／权利要求工作译稿，但尚未完整翻译摘要与附图中的英文文字；译稿尚未对照PCT-FILED逐句核稿。无中国经常居所／营业所。只列一家拟委托中国专利代理机构，未委托、未签授权、无费用核定。\nUS：英文原始PCT可用，无需把中文工作稿反译英文。已有含两位发明人姓名、住址、通信地址的合成ADS资料清单，但没有签署宣誓／声明；拟由注册美国专利执业者办理，未完成委托。没有small/micro entity资格证明。无恢复请求正文或费用批准。\nEP：拟继续用英文原始PCT作为审查基础；没有修改稿，没有提前处理请求。ISA为EPO，ISR随2025-10-16公布；申请人主要营业地在德国。拟聘欧洲代理但未委托；不因未聘代理臆造“德国公司依法必须代理”的事实。没有特殊展览证明。\n授权：现在只准对合成案卷作内部研究、计算、翻译差异检查、草拟材料清单及交接意见。任何真实提交、缴费、签字、委托、撤回、通知外部代理、公开或承诺救济成功均未获授权。\n",
      "content_sha256": "831265b5fbc94fc2f9a970ec56b9d37fa6efd3aac80213610ed80a31783de458",
      "hash_scope": "content字段UTF-8实际字节（LF）；只证明本合成版本一致，不证明官方真实性"
    }
  ],
  "assumptions_explicitly_not_given": [
    "没有正式进入或恢复批准",
    "没有证明全部延误非故意的签署陈述",
    "没有国内法豁免／宽限期事实",
    "没有修改或撤回最早优先权主张",
    "没有真实官方编号或真实签章",
    "没有保证未来无临时闭馆／电子渠道中断"
  ],
  "internal_roles": {
    "technical": "技术负责人陈工（合成）",
    "docket": "期限负责人周主管（合成）",
    "CN": "中国专利代理人候选，未委托",
    "US": "美国注册执业者候选，未委托",
    "EP": "欧洲专业代表候选，未委托",
    "decision": "企业有权决策人，未批准具体行动包"
  },
  "internal_work_target": "建议在2026-11-06前形成可供有权人审阅的CN／EP材料包和US完整延误事实包；这是本题工作提醒，非法律截止",
  "source_research": "references/jurisdictions/pct-priority-evidence-20261101.md",
  "scope_boundary": "当前仅开发合成示范；不执行浏览器、真实外发、付款、签字、登记、发布、安装或Git写入。"
}
```
