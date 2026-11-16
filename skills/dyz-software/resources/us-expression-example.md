# BlueHarbor美国软件表达争议：完整合成示范

本例对应SW-07/08，展示第十一巡回源代码争议内部候选。先读[表达方法](us-expression-method.md)与[官方来源研究](../../../references/jurisdictions/us-expression-evidence-20261101.md)。下面所有当事人、源码、合同、邮件、日志和登记卡均为原创合成，不能作为真实案件文件使用。S0/S1/S2一次提供，作者知预设要求；不是盲测或独立专业验收。

<!-- BEGIN D8-USCOPYRIGHT WORK PRODUCT -->
## S0：2026-10-27首次内部处理记录

本时点只使用A1、A2、B1、G0及REQ/OWN/EMAIL/ACCESS-SUM/REG/OLD。先保存经理原稿OLD，不采用其90%结论：无计算输入和统计口径，函数同名、TSV输出相同都不能直接证明侵权。源码时间与本次hash也不证明原创。REG记载的是申请待决；缴费不等于登记决定。Google案不能概括为所有接口代码免费，更不能据此处理两个完整报表实现。现在可完成静态比较、内部备忘录及证据目录；不把整仓库发给客户或法院。

初步取舍分三项。A1/B1的cell/row逐字一致，但OWN承认教程来源，文件第2行也有CommonsGrid通知，尚缺实际教程，故从经理的“全部独创”改为来源待核、暂不作排他主张；相同注释只能暂留来源线索。G0第1—2行自称生成文件，与Mina人工口述冲突，应查生成输入/日志，不能把25行全部纳入自方原创。A1/B1第15—28行的组织及多处用语对应，REQ没有要求分组顺序与港湾叙述，作为较具体的剩余候选继续查贡献和可替代选择，不能因它们有功能就停止分析。

A2第27—31行是新尾注，B1没有相应代码；本时点已应排除这部分“被B1复制”的说法。EMAIL支持Noah获A1附件的机会及回复，ACCESS-SUM称访问1.1但无状态码/字节，不能认定拿到了A2。Eli补邮件原件和附件、1.1服务记录、教程及生成记录；Mina交设计草稿和职责材料；June核作品/登记状态及美国规则。S0不认定事实复制或可诉复制已完成证明。

## S1/S2：保留旧结论后的实际修订

| 到达与新材料 | 先前候选/说法 | 当前替换及影响 |
| --- | --- | --- |
| S1，2026-10-29 14:30 -04:00；T0及TPL材料 | helper来源待核，相同注释暂留线索 | T0第3—12行与A1/A2/B1同区间同字节；撤下helper的自方原创/独占候选，不再用该注释独自支持来自A1的复制；保留许可通知与鉴真缺件。 |
| S1；G-LOG及Mina更正 | G0人工口述与generated头冲突 | G0第1—25行按共同客户生成输出处理，撤下其自方人工原创/排他候选；原错误口述和更正都保留，不造AI事实。 |
| S1；B-EARLY | 尚无具体独立来源反证 | 早期摘要与T0支持helper的独立来源解释；摘要不含render和港湾词句，不能将B1全部视为已证独立创作。 |
| S2，2026-10-31 10:00 -04:00；ACCESS-RAW | 商务简报说拿到最新版 | A1有投递和回复；A2该次请求403、0字节，撤回该请求取得1.1的推断；不据此排除所有未知渠道。 |
| S2；CREATION、B-REPLY | render贡献与来源仍待查 | 设计转录支持自方有选择过程；对方否认及惯用语主张留档。原设计载体、对方完整历史与惯用例证仍缺，剩余争点不自动成立也不整体撤销。 |

这是一次同时看到全部合成阶段后的发展示范，以上阶段记录不能被称为真正盲分阶段测试。下面是S2之后可独立阅读的完整终版，而不是在经理旧稿上直接签发。

## 内部备忘录 BH-US-EX-M1

日期：2026-11-01。收件角色：BlueHarbor内部法务协调人June、技术负责人Mina及记录管理员Eli。批准联络：Owen。版本：S2终稿候选r1。案号：D8-USCOPYRIGHT-01为合成题号，没有真实诉讼案号。所有当事人、材料、源码与时间均为合成，法律来源单独核验。

### 1. 当前建议及审阅对象

建议继续调查A1第15—28行与B1相应区间的具体选择和编排，范围聚焦两组形成、先后呈现、组内排序、连续港湾用语及小结的组合实现。不要对TSV功能、字段合同、共同helper、G0或A2独有尾注发出排他主张。剩余组合只是待美国专业人员审阅的候选范围；“有多种可写方式”和“对方得到过A1”均不足以直接宣布侵权。

本稿对象是BlueHarbor Ledger 1.0的完整小模块A1及GulfNote Board 0.8的完整小模块B1，辅以自方1.1模块A2、共同生成文件G0和后到模板T0。完整小模块不等于双方整个产品；未取得生产部署、销售、其他模块或损害事实。本次只作获准静态分析，没有运行源码或生成器，没有发函、起诉、登记或发送资料。

拟议佛州南区联邦路径尚待美国律师确认实际管辖、诉讼地和资格。为准备材料，本稿限定使用第十一巡回源码框架。AFC不是全国统一机械测试。版权归属、事实复制和可诉复制分开；专利新颖性、逐要素侵权及固定相似率不适用于替代这三项判断。

### 2. 依据和权利范围

使用2026-11-01核到的公开来源：R01为17 U.S.C. §§102、103、107；R02为§§201、202；R03为Compulife 2020意见第16—27页；R04为Compulife 2024意见第8—18页；R05为Google v. Oracle多数意见第15、35—36页；R06/R07为§§410/411及Fourth Estate 2019多数意见第1—4页。官方原始链接与版本限制见同包研究文件us-expression-evidence-20261101.md。该研究未完成全部后续判例或2025整编后全部立法追踪，不能据此签署真实法律意见。

OWN给出Mina全职、报表职责、BH-17任务、公司设备及无相反约定，支持在这些给定事实下将其任务内原创贡献按work made for hire归属BlueHarbor的候选判断。仍需June向拟聘美国律师交完整人事/任务原件，核真实关系和作品范围。Mina的实际贡献记录保留；公司法定作者/归属分析不把Mina写过的事实抹掉，也不扩张到教程作者或客户生成物。

T0的许可是Iris给予接收人的非独占使用、修改和带通知再分发许可，不是给BlueHarbor的独占转让。G0是客户交付的SchemaMill 2.0确定性生成输出，Mina明确更正未人工编写。两者退出BlueHarbor自身原创/排他主张，不等于裁定它们无人享权或可任意对外传播；通知与具体用途仍须核。A2的新增尾注另有版本贡献记录，未见于B1，暂不纳入本次B1复制指控。

### 3. 版本与接触事实

A1为36物理行，A2为41物理行，B1为36物理行，G0为25物理行，T0为27物理行，均含空行/注释。完整UTF-8、LF、末行LF的字节和SHA-256见审计BH-US-EX-A1；总165物理行只描述5份题内文件，未统计整个产品、版权原创行数或法定交存页数。

A1与A2除了第1行版本注释，A2在原A1第27行之前插入第27—31行：收集未就绪ID，输出Unmoored或Every lantern found a berth.，之后原尾句移至第32行、return移至第33行。B1仍在第27—28行结束render，且没有这些新增尾注，不能按A2全文把新增五行算作B1相似。这里仅说明静态结构，未证明对任意迭代输入的实际运行行为。

2024-04-12 EMAIL明确A1附件及两周封闭兼容评估目的；ACCESS-RAW有15:12:03投递accepted和16:01:22回复Received，时区均为-04:00。结合题内完整附件，支持Noah有取得A1的机会，并非证明他读完、使用或复制全部表达。评估许可未授权复制到商业产品，是否发生超出许可的具体行为仍待查，不能把合同许可边界直接变成版权侵权结论。

2024-06-20 10:05 -04:00的A2链接请求是403、0字节、expired-token。商务简报“访问过所以拿到最新版”已被该次原始记录纠正，不能再作A2接触依据。该记录不排除未来查到的其他渠道，但当前无证据。2026-09-15是对方提供B1封闭评估包的记载时点，不能当成B1的创作或首次商业使用日。REG出版记录、CREATION转录、文件时间和本次hash也各有证明边界。

### 4. 抽象和过滤后的剩余争点

先把该模块拆为任务功能、接口/转义约束、共同helper、生成字段辅助、分组呈现实现和整体编排。REQ要求id/state/rank字段及其TSV行内顺序、转义、先处理反斜杠；这些同源约束支持过滤相应功能/受限实现。REQ并未要求waiting先于ready、每组rank后id排序、港湾词句或组后计数小结，故不能把整段render笼统标“只有功能”。

T0第3—12行与A1/A2/B1第3—12行一致，含第4行相同注释；TPL-RECEIPT记载双方2023年收到教程，B-EARLY记载早期helper和一般export。就现有题内材料，该区间有具体共同源解释，不能继续用“独特注释也相同”单独推自方被复制。课程包签名、完整备份和时间鉴真尚缺，应保留缺口而非删除反证。

G0完整25行是双方共同客户输出，G-LOG绑定任务SM-2024-0210-01、CM-4输入、SchemaMill 2.0、human-edit=false及题内字节。口述更正足以让本次候选放弃“BlueHarbor人工编写G0”说法，但不是本次重跑生成器的证明，也不据此裁定生成器及模板权利全部无效。原错述与更正均入审计，不用AI政策填补不存在的AI事实。

剩余比较以A1第15—28行及B1同区间为审阅窗口，具体行和差异在BH-US-EX-A1。窗口包含需过滤的普通循环、字段调用和输出拼接，不能称14行每一行均享排他权。重点是A1选择先构造waiting/ready两组，再以waiting为前、ready为后，把组内rank/id排序、三组相呼应的港湾用语和每组灯数小结连续组织；B1改变量、品牌后仍保持这组对应关系。CREATION转录列出单表、全局排序、相反组序备选，提供选择过程线索，仍需原载体与同类来源核验。

整体源码编排是单独候选组成部分，不能因短语、变量和算法各自可能不受保护便机械消失，也不能因为能换顺序便当然受保护。Compulife 2024要求将编排拿出来分析，但该判决并未直接判其案涉编排受保护。本例需进一步判断整体是否有足够原创表达、组合是否仍由约束或共同源决定，以及被取用部分对A1的质与量意义。不能用“90%”或小于某百分比作结论。

此小模块的render是主要组织输出的实现，待审组合在其中有集中作用；这说明它值得具体审阅，不等于其商业重要性已证。程序总共36行也不等于36行全属原创，窗口14行不是法律分母。品牌、变量和标签差异必须一并保留；目前没有已核的“所有短语均行业惯用”样本，也没有排除世界上全部共同来源的全面检索。

### 5. 事实复制推断及反证

A1附件机会与剩余组合的对应构成继续调查的理由。R03区分用于证明事实复制的probative similarity与过滤后判断可诉复制的substantial similarity；二者不能互相替代。Noah否认复制、称只用CM-4/T0，是真实题内反证陈述，当前既不能忽略，也不能仅凭否认结束调查。

B-EARLY没有render及港湾词句，只为helper的独立来源提供支持，不证明B1第15—28行在接触A1前已存在。反之，缺少早期render记录不等于对方一定复制。下一步应由June在获得外部沟通授权后请求对方自愿提供render首次加入前后的完整仓库对象、服务器备份、作者/审阅记录和其所谓惯用语材料；Eli先保全现有自愿摘要，Mina准备只针对剩余组合的技术问题，不要求不相关整仓库公开。

CREATION原纸本/扫描、BH-17评审记录与同期备份可检验自方选择过程；邮件原件、附件hash、完整网关及服务日志可检验接触范围。对真实性未知的来源不采用“越早时间就越原创”的排序。R03的过滤举证责任有有效版权和事实复制等前提，内部补证不改法院负担分配，更不能因对方尚未交材料就先宣布事实复制已证。

### 6. 公平使用问题及登记状态

R05中Google v. Oracle针对特定Java API重实现事实作合理使用判断，并为论证假设其可版权；没有裁定所有API不受保护，也没有授予复制任意实现代码的通行许可。本例B1是报表实现，现只知封闭评估包与兼容主张，不能直接套用Android平台事实。

| 因素 | 已知及具体待证事项 |
| --- | --- |
| 目的与性质 | 对方说兼容并有商业产品背景，但B1实际用途、评估与生产边界、是否有改变用途的事实未知；由June请求实际使用说明，不能仅因商业性判败或因兼容判胜。 |
| 作品性质 | CM-4/转义有功能性，剩余组合及文本可能涉及表达选择；需Mina提交约束与选择证据，不能将功能性当全部免除。 |
| 取用量与重要性 | 以准确版本和被指控取用范围为对象，核必要性、可替代方案及其对A1整体的意义；没有90%的可复算基础，也未证全部取用出于接口必要。 |
| 市场影响 | 现无B1生产部署、销售、替代或许可市场资料；保全双方相应授权/客户事实后再评，不编损害金额，也不把缺数据当零损害。 |

REG只记A1于2026-10-20申请/交存/缴费且版权局尚无决定；无证书、无注册号、无预登记或拒绝。基于题内仅在美国授权分发的记录，先按美国作品一般路径交律师核；§411(a)和Fourth Estate不允许把待决申请当一般登记前提已满足。有限例外、作品身份与真实状态另核，本题不补造例外。A2没有该登记记录，不能继承A1事项卡状态。

即使以后取得满足§410(c)条件的证书，其初步证据效力也不是对B1复制、可诉性、损害或禁令的判决。保护存在不以登记为唯一来源，登记程序又不能省略；June另请律师核时效、§412及其他救济条件，本稿不计算索赔或承诺全面禁用。原经理稿的程序/范围判断均不可作为正式行动依据。

### 7. 当前结论与交接

内部候选保留对A1/B1剩余具体编排的进一步分析；撤下自方对helper/G0的原创排他候选；不主张B1复制A2独有尾注；将取得A2的说法改为该次请求未取得且其他渠道未知。现有证据不足以终局认定事实复制、可诉复制、公平使用或损害，仍足够完成针对性的内部比较与保全准备。

June接收本备忘录M1和动作表X1，Mina与Eli接收审计A1及题内源文件清单，按各自职责完成证据核对。具体文件、hash、角色、用途和下一动作在交付表中固定；本稿及完整教学附录都不是律师函、起诉状、登记申请或可整体外发包。外部专业人员尚未选定，不假装已取得其意见；内部处理已进行不因外部条件缺失统一暂停。

## 内部源码与证据审计 BH-US-EX-A1

版本：S2-r1；仅用于Mina、Eli和June的内部复核。下表原行含空行/注释；完整内容在本资源末尾原案JSON的source_files中，包外开发目录不是使用本例的必需依赖。

### 字节清单

| ID / 相对源码路径 | 字节 / 物理行 | SHA-256 |
| --- | --- | --- |
| A1 / blueharbor/1.0/report.py | 1128 / 36 | 276cb6a11b158d006c3acf20209352ac326b04cee7021d40050d15ef72bc1778 |
| A2 / blueharbor/1.1/report.py | 1340 / 41 | 9d4b7ded27e3324021ba3bbff77477304a52b111d9208efa536fd3f9436b5463 |
| B1 / gulfnoteboard/0.8/report.py | 1138 / 36 | 5526a2848188356aab9fdc7390e08c9af93b554ae460b1e858c2e364115dcece |
| G0 / shared/generated_schema.py | 472 / 25 | e5534bd004f9bdf035566689548eb6da3913743d7db43f9e708aab18fcd7c615 |
| T0 / commonsgrid/2023-09/template.py | 686 / 27 | 09c8f488b731363ba42faec813af65ac16e3ba215fc628c69fb0ae385c909019 |

每项按content字符串解码后的UTF-8字节计算，LF换行且末尾有LF；JSON字符串中的转义不是源文件中的额外反斜杠。合计4764字节、165物理行。提取后的副本不加行号、不重排换行、不执行。文件hash证明本次副本相同，不证明来源/历史或证据可采性。

### 逐行与组合映射

| 比较位置 | 相同和差异 | 来源/约束与当前取舍 |
| --- | --- | --- |
| A1/A2/B1第3—12行；T0第3—12行 | cell/row及Seal cells注释字节一致 | 共同模板与许可；S1从来源待核改为排除自方独占主张；REQ转义顺序亦给功能约束。 |
| A1/B1第15—20行 | 两个列表按state==ready分流，waiting/ready/item/target改为pending/finished/entry/bucket | 分组算法本身不独占；结合REQ未要求分组，将具体后续组合留下审阅。改名不自动消除也不自动证明复制。 |
| A1/B1第21行 | Harbor ledger改GulfNote ledger；lantern / berth / wake相同 | 品牌差异明确；短语单独不作为排他对象，连续呈现候选在整体层比较。 |
| A1/B1第22—23行 | 先未就绪后ready，组名At the gate、Beyond the gate及方括号包装相同；组变量不同 | REQ允许任意组序/组名；整体编排候选，普通括号/短语不逐个垄断。 |
| A1/B1第24—25行 | 组内rank/id排序；迭代变量互换；行字段id/state/rank一致 | 行字段顺序受CM-4约束应过滤；排序方法本身不主张；与其他选择的具体组织是否有表达另审。 |
| A1/B1第26—28行 | 每组灯数小结、One harbor; two tides.、最终换行拼接相同 | 短语/常规join不能单独定权；小结与组名的连贯组合仍需查原创性/来源/重要性。 |
| A2第27—31行对B1 | A2新增labels及两种尾注，B1无对应 | 从本次B1复制范围排除；A2第32—33行对应A1/B1第27—28行，不能错位比较。 |
| A1第31—36行；A2第36—41行；B1第31—36行 | preview薄包装相同；format_name品牌不同 | 不以函数同名/一行转调证明受保护表达复制；保留完整上下文。 |
| G0第1—25行 | 双方同一生成文件 | G-LOG和Mina更正；撤下BlueHarbor人工原创/排他候选，未作全世界无版权认定。 |
| 整体候选A1/B1第15—28行 | 分流、指定组序、组内排序、连续隐喻、小结、结语的组织关系对应 | 单列为可能受保护的组成部分；再过滤约束、共同来源和普通表达，并评剩余质与量；不是把14行全列为权利。 |

### 证据目录与取得任务

| 证据 | 支持与不支持 | 原件/后续任务及责任 |
| --- | --- | --- |
| A1/A2/B1/G0/T0完整字节 | 可核当前版本和左右内容；不能证历史创作/生产使用 | Eli保存原题、提取副本和hash清单；真实场景由源持有人给授权载体与取得记录。 |
| OWN及CREATION | 支持职责/候选归属和选择过程；转录不等于原件鉴真 | June核完整人事/任务协议；Eli取得纸面设计、原扫描及评审记录；Mina解释备选实现，不重写旧稿。 |
| EMAIL/ACCESS-RAW/ACCESS-SUM | A1机会及A2该次失败；不是阅读/复制的直接证明 | Eli保全原eml及附件、网关日志、完整文件服务日志和时区配置，保持简报与纠错同时存在。 |
| TPL-LICENSE/TPL-RECEIPT/T0 | 具体共同源及非独占许可；时间仍待鉴真 | Eli经客户授权请求课程zip原包、清单、许可和备份来源；不改通知，不将本次hash当2023时间戳。 |
| G-LOG及G0 | 指向客户确定性生成产物与错误口述更正；不证本次复跑 | Mina/Eli经客户授权保全生成任务输入、工具版本说明、原日志和输出；保留Mina前后说法；不执行生成器。 |
| B-EARLY/B-REPLY/B1 | helper独立来源及对方否认；不证完整render独立创作 | Eli保留收到原貌；June待沟通授权后请求对方自愿提供具体render历史/备份及惯用语用例，不进入对方系统。 |
| REG与授权包记录 | pending及给定出版线索；不证登记完成/侵权/损害 | June核正式申请/交存/付款/通知原件及A1首次分发证据；Eli保全B1封闭评估包原载体与取得用途限制。 |
| OLD | 证明历史主张和需纠正事项；不证明90%或法律结论 | June原样存档，附M1取代说明；不得覆盖原稿或删除不利表述。 |

### 保全实施边界

已经做的是合成JSON静态读取、源码字节提取/hash和上述定位；没有执行案卷程序，没有现实原邮箱/服务器/纸本取得。拟由Eli在现有授权内完成本方载体保全：原件只读保存，工作副本另编号；记录操作者、权限依据、取得命令/工具与版本、取得时间和时区、源/副本hash、存储位置、每次访问/复制和交接。导出邮件须连附件及必要头部，仓库须连相关历史对象和备份，不能只抄显示时间。

客户/对方尚缺授权的原件由June请求合法提供；保留完整上下文和不利反证，不改时间、不补签、不用生成材料冒充原件。拟法院证据保全、调取、鉴定、证据可采性及诉讼保全义务由美国律师另核。本地副本和hash不是法院保全或防篡改系统，访问控制及日志未实施的部分写待建，不能填已通过。

## 动作与交付表 BH-US-EX-X1

版本：S2-r1。M1为完整内部备忘录，A1为内部源码/证据审计；此处A1包标签不改变源码文件ID A1的含义。X1绑定两份同版文件和源代码清单；三份实际文件的hash在示范交付清单中列出，后续任何正文或原件改变都重新计算、重审受影响结论和包，不沿用旧批准。

| 具体动作 / 所需材料 | 对象、目的与渠道 | 角色、当前状态与恢复条件 |
| --- | --- | --- |
| 内部技术比较；A1审计及5份题内源码副本 | Mina、Eli；核行号、约束和来源；当前授权本地工作区 | 合成材料处理已获准，静态比较/副本提取已完成；Mina的现实确认未发生。Owen负责范围变化的授权。 |
| 内部法务整理；M1、X1、REG/OWN及原OLD | June；判断下一步事实问题；同一内部工作区 | 已完成候选，不等待外部律师才起草；June非假定美国律师，专业签核待取得。 |
| 内部保全；邮件、仓库、设计及现有反证原件 | Eli；保持原貌；拟本方受控只读证据区及访问日志 | 当前完成仅题内副本。真实载体取得须核本方权限、位置与工具；June确认保全范围，Owen负责新增权限。 |
| 向客户/对方补证；TPL/G-LOG/B-EARLY/B1授权包缺件清单 | 具体客户保管人或对方指定联系人待June核；目的限补证；拟双方认可的安全交付渠道待定 | 未联系未发送；Owen批准具体清单/对象/渠道，June核对方同意与用途限制后Eli接收；不登录他方系统。 |
| 外部律师审阅；拟最小M1+必要A1摘录/原件索引 | 尚未选定的美国版权律师；专业意见；拟律师确认的受控数据室 | 未选聘、未组外发包、未发送。June核身份/委托/保密和资料权限，Owen批准具体版本/接收人/渠道后发送前重核hash并收回执。 |
| 向对方函告；未来律师核定正文及必要附件 | GulfNote有权收件人待核；表达争点沟通；律师核定渠道待定 | 未起草正式函、未发送。先取得当前范围/归属/法律审核和Owen动作授权，排除完整教学附录/内部审计默认外附。 |
| 法院起诉/保全申请；未来律师形成专用包 | 有管辖法院和代理人待核；正式救济；律师确认的法院渠道 | 未申请未提交。美国律师核管辖、资格、登记/例外、时效、证明与保护安排；Owen授权具体动作和版本后方可执行。当前本地保全不代替该步骤。 |
| 版权局登记跟进/新材料；REG事项及经核的A1版本 | 美国版权局；查询/答复或依法需补资料；具体账户/渠道待June核 | 本任务未登录、未提交。pending卡不能填已登记；June核原申请/交存/新来源影响并交专业人员，Owen另批具体提交，不把A2自动换入。 |
| 认证或签署；未来特定表单/声明版本 | 有权签署人及接收机构待核；真实性声明；对应正式渠道 | 未签署。June核事实/签署资格，Owen确认权限；不代签、不把模型分析写成亲历事实。 |
| 付款；未来费用单/委托约定 | 已核律师或官方收款方；具体服务/程序；经财务核定渠道 | 未付款。Owen审批预算/金额，June核收款对象与用途；历史登记缴费记录不授权新费用。 |
| 公开源码或向客户传播；拟披露专用最小包 | 受众/客户名单待定；用途待Owen明确；渠道待定 | 当前无授权、不发布。先核第三方许可、评估限制、秘密/其他权利和专业结论，不能整体发教学示范或把函告权扩为公开权。 |
| 新模型/云服务处理；未来明确选定的文件子集 | 具体服务商/模型待核；处理目的待定；数据路径待核 | 本次宿主获准仅合成材料；不承接真实秘密或自动扩新云权限。Owen与资料负责人核服务条件、保留/索引路径及逐包许可后才处理。 |

所有现实外部动作目前均未执行，没有发送/登记/付款/签署回执。以后发送结果不明先查对应记录，不盲目重试。新增共同源、接触证据、版本、规则或收件范围会触发相应实体与包重审。已完成的内部候选和字节核对属于开发产物，不是独立专业验收、真实法务签核或稳定性交付证明。

## 实际开发交付清单

以下是本次本地形成的三个独立文件，不是拟外发批准。完整合成原题附于资源末尾，单独使用资源不依赖outputs路径。源码副本仅来自原题content，不是从真实对方系统取得。

| 内部包 | 开发实际文件 | 字节 | SHA-256 |
| --- | --- | --- | --- |
| M1 | uscopyright-memo-r1.md | 11413 | 12bb23bfa601dd46275ba8bb4d9ccb9c80b1c4c668da6fedfbceb4aea504601d |
| A1审计 | uscopyright-audit-r1.md | 6227 | ef6f693347a33bc09f34cee1bf16c7c9bf96ee6fbe37ec2d9f49ae19a6480e62 |
| X1 | uscopyright-actions-r1.md | 4338 | 19aac773ab59943585dc740fd1ab7a5f355131be73bfaa03aa37223c1cef29ba |

仅静态字节/行映射核对已完成；专业审阅、真实原件鉴真、浏览器显示、外部动作和稳定性验证不从这张文件清单推定完成。显示检查如后续由整合者实际执行，只对其绑定版本另记。
<!-- END D8-USCOPYRIGHT WORK PRODUCT -->

## 完整合成原题与原始源码字节

以下JSON完整保留冻结原题字节。source_files内content解码后即原始源码；不能把JSON转义记号当成源文件额外字符。各阶段材料仍全部可见，不能把本资源标为逐阶段盲输入。

```json
{
  "case_id": "D8-USCOPYRIGHT-01",
  "synthetic": true,
  "as_of": "2026-11-01",
  "task": "编写供BlueHarbor内部法律/技术小组审阅的美国软件表达争议备忘录，先给S0有限结论，再给S1、S2之后可独立阅读的完整终版；定位逐行、选择性表达与整体编排，修订拟主张范围，形成证据/保全和逐动作交接。不能发函、登记、起诉或运行对方代码。",
  "jurisdiction": {
    "assumption": "双方为佛州公司，项目组拟请美国律师评估佛州南区联邦法院路径；本题只按第十一巡回源代码框架准备材料。未取得实际法院/管辖/诉讼地专业意见，无真实案件。",
    "scope": "不是全国统一AFC机械测试，不含专利、商业秘密或合同侵权终局判断。"
  },
  "permissions": {
    "status": "题目、人物、邮件、合同、日志、源码、时间均为作者原创合成；不含真实第三方源码或账户。",
    "allowed": "宿主模型读取这些合成材料、本地静态比对/hash/提取和内部稿展示；不执行任何案卷代码。",
    "forbidden": "不登录对方系统、不下载真实对方资料、不向律师/对方/法院发送、不真实提交登记或诉讼、不付款或签署。"
  },
  "roles": {
    "technical": "Mina，BlueHarbor技术负责人",
    "records": "Eli，BlueHarbor记录管理员",
    "legal": "June，BlueHarbor内部法务协调人；不是假定有美国执业资格",
    "authority": "Owen，BlueHarbor授权负责人",
    "external": "美国律师尚未选定，联系方式及委托范围未知"
  },
  "stages": [
    {
      "id": "S0",
      "received_at": "2026-10-27T09:00:00-04:00",
      "available": [
        "A1",
        "A2",
        "B1",
        "G0",
        "REQ",
        "OWN",
        "EMAIL",
        "ACCESS-SUM",
        "REG",
        "OLD"
      ],
      "request": "先保存旧经理稿并给实质可执行的初步取舍；不能预知后到T0与G-LOG。初始缺来源不等于所有相同代码都原创。"
    },
    {
      "id": "S1",
      "received_at": "2026-10-29T14:30:00-04:00",
      "available": [
        "T0",
        "TPL-LICENSE",
        "TPL-RECEIPT",
        "G-LOG",
        "B-EARLY"
      ],
      "request": "共同来源与生成出处到达；明确撤下哪些初始候选/证据意义，保留哪些仍需查的表达。不要整个案件一笔勾销。"
    },
    {
      "id": "S2",
      "received_at": "2026-10-31T10:00:00-04:00",
      "available": [
        "ACCESS-RAW",
        "CREATION",
        "B-REPLY"
      ],
      "request": "接触范围收窄为1.0；晚到1.1链接403。用原字节更新结论并交完整终稿；不将日期链或接触机会写成复制已证。"
    }
  ],
  "source_files": [
    {
      "id": "A1",
      "path": "blueharbor/1.0/report.py",
      "arrived": "S0",
      "origin": "自方1.0完整模块；文件系统mtime不作创作证明",
      "encoding": "UTF-8",
      "newline": "LF",
      "terminal_newline": true,
      "bytes": 1128,
      "physical_lines": 36,
      "sha256": "276cb6a11b158d006c3acf20209352ac326b04cee7021d40050d15ef72bc1778",
      "content": "# SYNTHETIC BlueHarbor Ledger 1.0; no production data.\n# CommonsGrid helper notice: nonexclusive reuse with notice.\ndef cell(value):\n    # Seal cells before they travel.\n    text = str(value)\n    text = text.replace(\"\\\\\", \"\\\\\\\\\")\n    text = text.replace(\"\\t\", \"\\\\t\")\n    return text.replace(\"\\n\", \"\\\\n\")\n\n\ndef row(values):\n    return \"\\t\".join(cell(value) for value in values)\n\n\ndef render(records):\n    waiting = []\n    ready = []\n    for item in records:\n        target = ready if item[\"state\"] == \"ready\" else waiting\n        target.append(item)\n    lines = [\"Harbor ledger\", \"lantern / berth / wake\"]\n    for title, group in ((\"At the gate\", waiting), (\"Beyond the gate\", ready)):\n        lines.append(\"[\" + title + \"]\")\n        for item in sorted(group, key=lambda entry: (entry[\"rank\"], entry[\"id\"])):\n            lines.append(row((item[\"id\"], item[\"state\"], item[\"rank\"])))\n        lines.append(\"-- \" + str(len(group)) + \" lights --\")\n    lines.append(\"One harbor; two tides.\")\n    return \"\\n\".join(lines) + \"\\n\"\n\n\ndef preview(records):\n    return render(records)\n\n\ndef format_name():\n    return \"BlueHarbor text ledger\"\n"
    },
    {
      "id": "A2",
      "path": "blueharbor/1.1/report.py",
      "arrived": "S0",
      "origin": "自方1.1完整模块；增加未就绪ID尾注",
      "encoding": "UTF-8",
      "newline": "LF",
      "terminal_newline": true,
      "bytes": 1340,
      "physical_lines": 41,
      "sha256": "9d4b7ded27e3324021ba3bbff77477304a52b111d9208efa536fd3f9436b5463",
      "content": "# SYNTHETIC BlueHarbor Ledger 1.1; no production data.\n# CommonsGrid helper notice: nonexclusive reuse with notice.\ndef cell(value):\n    # Seal cells before they travel.\n    text = str(value)\n    text = text.replace(\"\\\\\", \"\\\\\\\\\")\n    text = text.replace(\"\\t\", \"\\\\t\")\n    return text.replace(\"\\n\", \"\\\\n\")\n\n\ndef row(values):\n    return \"\\t\".join(cell(value) for value in values)\n\n\ndef render(records):\n    waiting = []\n    ready = []\n    for item in records:\n        target = ready if item[\"state\"] == \"ready\" else waiting\n        target.append(item)\n    lines = [\"Harbor ledger\", \"lantern / berth / wake\"]\n    for title, group in ((\"At the gate\", waiting), (\"Beyond the gate\", ready)):\n        lines.append(\"[\" + title + \"]\")\n        for item in sorted(group, key=lambda entry: (entry[\"rank\"], entry[\"id\"])):\n            lines.append(row((item[\"id\"], item[\"state\"], item[\"rank\"])))\n        lines.append(\"-- \" + str(len(group)) + \" lights --\")\n    labels = [str(item[\"id\"]) for item in records if item[\"state\"] != \"ready\"]\n    if labels:\n        lines.append(\"Unmoored: \" + \", \".join(labels))\n    else:\n        lines.append(\"Every lantern found a berth.\")\n    lines.append(\"One harbor; two tides.\")\n    return \"\\n\".join(lines) + \"\\n\"\n\n\ndef preview(records):\n    return render(records)\n\n\ndef format_name():\n    return \"BlueHarbor text ledger\"\n"
    },
    {
      "id": "B1",
      "path": "gulfnoteboard/0.8/report.py",
      "arrived": "S0",
      "origin": "对方同意用于封闭评估的包内模块；没有生产部署证据",
      "encoding": "UTF-8",
      "newline": "LF",
      "terminal_newline": true,
      "bytes": 1138,
      "physical_lines": 36,
      "sha256": "5526a2848188356aab9fdc7390e08c9af93b554ae460b1e858c2e364115dcece",
      "content": "# SYNTHETIC GulfNote Board 0.8; no production data.\n# CommonsGrid helper notice: nonexclusive reuse with notice.\ndef cell(value):\n    # Seal cells before they travel.\n    text = str(value)\n    text = text.replace(\"\\\\\", \"\\\\\\\\\")\n    text = text.replace(\"\\t\", \"\\\\t\")\n    return text.replace(\"\\n\", \"\\\\n\")\n\n\ndef row(values):\n    return \"\\t\".join(cell(value) for value in values)\n\n\ndef render(records):\n    pending = []\n    finished = []\n    for entry in records:\n        bucket = finished if entry[\"state\"] == \"ready\" else pending\n        bucket.append(entry)\n    lines = [\"GulfNote ledger\", \"lantern / berth / wake\"]\n    for title, group in ((\"At the gate\", pending), (\"Beyond the gate\", finished)):\n        lines.append(\"[\" + title + \"]\")\n        for entry in sorted(group, key=lambda item: (item[\"rank\"], item[\"id\"])):\n            lines.append(row((entry[\"id\"], entry[\"state\"], entry[\"rank\"])))\n        lines.append(\"-- \" + str(len(group)) + \" lights --\")\n    lines.append(\"One harbor; two tides.\")\n    return \"\\n\".join(lines) + \"\\n\"\n\n\ndef preview(records):\n    return render(records)\n\n\ndef format_name():\n    return \"GulfNote text ledger\"\n"
    },
    {
      "id": "G0",
      "path": "shared/generated_schema.py",
      "arrived": "S0",
      "origin": "双方包内同字节；初期仅有自方人工撰写口述，后到G-LOG纠正",
      "encoding": "UTF-8",
      "newline": "LF",
      "terminal_newline": true,
      "bytes": 472,
      "physical_lines": 25,
      "sha256": "e5534bd004f9bdf035566689548eb6da3913743d7db43f9e708aab18fcd7c615",
      "content": "# SYNTHETIC SchemaMill 2.0 generated output; do not edit.\n# Input contract CM-4; generated artifact, not a human draft.\nFIELDS = (\"id\", \"state\", \"rank\")\nKINDS = (\"text\", \"text\", \"integer\")\nREQUIRED = (True, True, True)\n\n\ndef field_names():\n    return FIELDS\n\n\ndef field_kind(name):\n    return KINDS[FIELDS.index(name)]\n\n\ndef is_required(name):\n    return REQUIRED[FIELDS.index(name)]\n\n\ndef has_field(name):\n    return name in FIELDS\n\n\ndef schema_name():\n    return \"CM-4\"\n"
    },
    {
      "id": "T0",
      "path": "commonsgrid/2023-09/template.py",
      "arrived": "S1",
      "origin": "后到共同模板完整字节；原始lesson包由客户档案保管人提供",
      "encoding": "UTF-8",
      "newline": "LF",
      "terminal_newline": true,
      "bytes": 686,
      "physical_lines": 27,
      "sha256": "09c8f488b731363ba42faec813af65ac16e3ba215fc628c69fb0ae385c909019",
      "content": "# SYNTHETIC CommonsGrid lesson 2023-09, not real third-party code.\n# Nonexclusive permission; preserve this notice when redistributing.\ndef cell(value):\n    # Seal cells before they travel.\n    text = str(value)\n    text = text.replace(\"\\\\\", \"\\\\\\\\\")\n    text = text.replace(\"\\t\", \"\\\\t\")\n    return text.replace(\"\\n\", \"\\\\n\")\n\n\ndef row(values):\n    return \"\\t\".join(cell(value) for value in values)\n\n\ndef export(records):\n    lines = [row((\"id\", \"state\", \"rank\"))]\n    for item in records:\n        lines.append(row((item[\"id\"], item[\"state\"], item[\"rank\"])))\n    return \"\\n\".join(lines) + \"\\n\"\n\n\ndef empty_export():\n    return export(())\n\n\ndef format_name():\n    return \"CommonsGrid TSV\"\n"
    }
  ],
  "documents": [
    {
      "id": "REQ",
      "content": "合成客户合同CM-4 2024-02-01：记录字段名称固定为id、state、rank，TSV行内字段顺序固定id/state/rank，制表符和换行须转义，反斜杠先转义以免二次解释；允许任意展示标题、组名、组排列、叙述、页尾。客户不要求先按state分两组，不要求rank/id排序，不要求灯/港口隐喻。CM-4给双方使用，不能单凭字段相同推断双方互相复制。"
    },
    {
      "id": "OWN",
      "content": "合成人事/任务摘录：Mina为BlueHarbor全职雇员，在其报表开发职责内于2024-03完成A1，2024-06完成A2；公司提供设备且任务单BH-17明确要求实现报表，无相反版权归属协议。本题提供的是完整合成相关条款，不是现实雇佣关系鉴定。Mina在初访中称render为其人工写作，cell/row从内部教程取用且忘记名称；G0她最初误称人工。公司没有取得CommonsGrid或SchemaMill的独占版权转让。"
    },
    {
      "id": "EMAIL",
      "content": "合成原始邮件摘录，Message-ID=<demo-0412@synthetic.invalid>，2024-04-12T15:12:00-04:00，Mina发给GulfNote开发员Noah：附件为BlueHarbor 1.0 report.py，供两周封闭兼容性评估，不授权复制到商业产品。附件在题中就是A1字节。Noah同日回复Received, I will check the row contract. 邮件已提供头部摘录与完整附件，但现实原邮箱载体、DKIM链未有，不能宣称司法鉴真。"
    },
    {
      "id": "ACCESS-SUM",
      "content": "合成商务简报：Noah曾打开1.0附件，也于2024-06-20访问过1.1链接，因此一定拿到了最新版。简报未附服务器状态码和字节数。"
    },
    {
      "id": "REG",
      "content": "合成内部登记事项卡：BlueHarbor Ledger 1.0 claimed computer program；2026-10-20已提交申请/交存/费用的项目组记录，版权局截至题目日尚未作出登记决定；无证书、无注册号，未预登记、未拒绝。A1曾由公司授权在2024-04-01只向美国客户提供可留存副本；未有境外或更早公开记录。A2未纳入该卡，不据此认定1.1已经登记。"
    },
    {
      "id": "OLD",
      "content": "保留经理原话：两个程序百分之九十相同，函名一样，连Seal cells before they travel和generated_schema都相同，证明我方独创全部被抄；Git时间最早就是原创证据。对方能做相同TSV输出就已侵权。我们付完登记费就能起诉，Google v Oracle也只是说所有接口代码都免费。应向客户和法院发送整仓库要求全面禁用。百分之九十没有计算输入、规则或结果。"
    },
    {
      "id": "TPL-LICENSE",
      "content": "合成CommonsGrid 2023-09许可原文：作者Iris授予收到本教程者非独占使用、修改、再分发模板及修改副本的许可，须保留教程来源及许可通知；不转让版权，不授予接收人对模板的独占权。许可不涉及接收人日后另写的render函数。本题源码已保留短通知；是否满足真实项目全部通知条件不在题中认定。"
    },
    {
      "id": "TPL-RECEIPT",
      "content": "合成客户档案收件清单：2023-09-18向BlueHarbor与GulfNote各交同一CommonsGrid课程zip，T0是该zip完整template.py；本次从客户只读备份提取，档案人员Eli记录取得2026-10-29T14:30:00-04:00。提供清单与原文件，但课程zip全包签名和独立可信时间戳未提供；该早期分发时间为待外部鉴真的合成记录事实，不能由T0本次hash反推。"
    },
    {
      "id": "G-LOG",
      "content": "合成SchemaMill日志原文：job SM-2024-0210-01; input CM-4 fields=id,state,rank; generator SchemaMill 2.0; output generated_schema.py; mode deterministic; operator=customer-build; human-edit=false. 输出字节就是G0，客户同时给双方。Mina书面更正：我没有写G0，只从客户包复制；先前口述错误请保留。日志不是生成器源码或可复跑环境，不能宣称本次重跑生成器。生成文件来源是确定性模板生成，不是AI事实，不臆造AI作者。"
    },
    {
      "id": "B-EARLY",
      "content": "合成对方自愿提供2023-09-21仓库导出摘要：含T0的cell/row及一般export，没有render，没有lantern/berth/wake、At the gate、Beyond the gate或One harbor; two tides。该摘要带仓库时间字段但未提供完整历史对象/服务器备份；可支持共同源的独立来源解释，不能证明B1整体在接触A1前已存在。"
    },
    {
      "id": "ACCESS-RAW",
      "content": "合成邮件网关/文件服务原始摘录：2024-04-12T15:12:03-04:00 recipient=noah@gulfnote.synthetic.invalid message=demo-0412 attachment=A1 delivery=accepted; 2024-04-12T16:01:22-04:00 reply=Received. 2024-06-20T10:05:00-04:00 recipient=noah target=BlueHarbor-1.1 status=403 bytes=0 reason=expired-token. 无其他A2访问记录；没有证据Noah完全读过A1，更不能由HTTP访问记录推出拿到A2。"
    },
    {
      "id": "CREATION",
      "content": "合成设计笔记BH-17-N，2024-03-03纸面扫描转录：Mina比较了单表、按rank全局排序、两个相反顺序组；选择waiting在前、ready在后，每组按rank再id排序，标题与小结用港湾意象连续呈现。2024-03-05评审记录把该选择对应A1 render实现。原纸本和扫描原文件待记录管理员取得。本题没有第三方较早相同表达的全面检索，没有独立可信创作时间戳。"
    },
    {
      "id": "B-REPLY",
      "content": "合成对方自愿书面说明：Noah说自己只参考CM-4与CommonsGrid，否认把A1复制进B1；将相同英文词句称行业惯用语，但没有提供用例。称商业产品需要相同接口，援引Google案；未给转换用途、取用必要性、市场或损害证据。B1系2026-09-15封闭评估包，公司在争议发生前交给BlueHarbor作内部兼容测试。现实生产部署、销售量、损害、是否将此版对外分发均未知。"
    }
  ],
  "deliverables": [
    "S0范围候选与旧稿纠正",
    "S1/S2变化记录且保存旧判断",
    "完整终版内部备忘录（规则、权利、版本/接触、抽象/过滤/剩余比较、反证、公平使用问题、登记/诉讼条件）",
    "逐行映射、独立编排争点及证据清单",
    "具体保全和内部/外部行动分流，区分已做与拟做"
  ],
  "execution_limit": "所有阶段一次提供，演示阶段响应不等于真正盲分阶段；不得把本例计为专业独立验收。"
}
```
