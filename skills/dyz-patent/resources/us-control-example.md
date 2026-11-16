# 烘箱服务安排与物理保护：美国专利合成开发示范

本示范为原创合成材料，含初始路线、后到原件、实际替换权项及核心说明。作者预先知道全部阶段和rubric，非盲释放、独立专业验收或真实案件。规则边界见[来源研究](../../../references/jurisdictions/us-control-evidence-20261101.md)，使用方法见[US控制方法](us-control-method.md)。文末保留冻结原题完整JSON；正文与原题区分，不以原题文字补算作答完成。

<!-- BEGIN D8-USPAT WORK PRODUCT -->
# D8-USPAT-01 内部审阅稿

## 1. 结论与实际依据

建议以固定物理保护路线B形成当前申请的审阅候选。路线A只有信用、等待时间、费用计算及人工决定采用的排序，未披露计算机自身或物理控制改善；把它写进“优化模块”不会自动克服101。路线B有可追溯的消息校验、计数、锁存和SSR动作，但适格有利不表示102/103、112或正式修改条件已经满足。

M1/C0/D1/D2、L1/L2全部合成；D1/D2日期是假定，L1不是官方回执，L2不是实际实验。本执行者预先看到全部阶段，V0/V1为开发叙述，非盲释放或专业签核。

规则于2026-11-01核验。USCTL-01是截至2024-01-31的35 USC官方汇编，未逐项清查后来公法；MPEP Rev.01.2024须合并2025-08-04提醒及12月5日立即生效的Desjardins指定段落更新。MPEP/备忘录属审查指引，Desjardins属ARP/PTAB先例，不替代制定法或法院判例。Amgen原判已取得；Alice、KSR、Williamson仅据MPEP官方转述。

USCTL-04已核2026-09-29 SMED补充：补充4月30日给申请人版，4月版替代2025年12月4日给申请人版，不替代同日给审查员版。4月PDF正文未取得。SMED自愿、非101必备；正式使用须补完整规则/阶段/证明基础，不能代造真实专家签署、实测或倒填P07算法。

定位见来源研究USCTL-01—08，官方入口 https://www.uspto.gov/patents/laws/examination-policy/subject-matter-eligibility；112见MPEP 2161/2163/2181，102/103见2131/2141。本文为内部意见，无官方OA或正式答复。

## 2. 起初材料下的两条实际路线 V0

### 2.1 路线A：A0业务安排权项

A0-1. A computer-implemented method of arranging oven services, comprising: receiving, for each customer, a customer identifier, an order amount v, a credit level c selected from 0, 1 and 2, and a waiting time h in hours; calculating a priority value a as `a = 2*c + min(h,24)`; ordering the customers by decreasing priority value and, for equal priority values, by increasing customer identifier; and displaying the resulting oven-service order for an operator to decide whether to follow.

A0-2. The method of claim A0-1, further comprising calculating, for each customer, an estimated charge as `v*(1-0.02*c)` and displaying the estimated charge.

A0两项支持均为P02；A0-2增加费用显示，v/c沿本引用路径已定义。范围仅及该信用/等待规则，排除其他分值和自动温控，改权重或同分规则即可绕开字面限定；材料不支持全部服务优化，更窄收费项也未呈现技术改善。不能借P03物理算法支持P02全部费用优化。

101 Step 1：该计算机执行方法可以属于process类别，但类别本身不排除司法例外。Step 2A Prong One：信用/等待排序和收费是商业服务安排并记载数学计算，具有抽象概念压力；这些特定公式不因参数固定便脱离例外。Prong Two：P02明确普通表格程序，只显示结果让人决定，A0中没有使计算机自身或其他技术改善的步骤；烘箱用途只是应用领域，显示不形成具体加热控制。以本材料看，整体未见把例外整合为有意义技术应用的依据。

Step 2B：按P02普通表格描述，额外输入、处理及显示单独和组合均未见超出商业自动化的安排，不足以支持显著更多。正式WURC认定仍须证据，不能只凭D1/D2某部件出现就认定整个组合广泛常用，也不把103与inventive concept合一。A0-2收费不改变这一压力，暂不推荐主攻。

### 2.2 路线B：B0固定保护权项

B0-1. A method of controlling power to a resistance heater of an experimental oven through a solid-state relay, using a local processor, comprising: at startup, initializing a high-temperature count n and a cooling count m to zero, a latch L to zero, and a last accepted sequence number s0 to minus one, and sending a zero command to the relay; then, in each control cycle of 100 milliseconds, selecting the received temperature message having the greatest sequence number, the message comprising a measured temperature T, a sequence number s, a sampling time ts and a validity bit q, a sampling board and the processor using a common monotonic clock; accepting the selected message only when q equals one, s is greater than s0, and its age at the cycle time is from zero to 150 milliseconds inclusive, and updating s0 to s only upon acceptance; when no message is accepted, clearing n and m, setting L to one, leaving s0 unchanged and sending a zero command; when a message is accepted, increasing n by one up to three for T at least 85 degrees Celsius and otherwise clearing n, increasing m by one up to two for T at most 80 degrees Celsius and otherwise clearing m, setting L to one when n reaches three, and clearing L only upon a pulse from a local reset button in that accepted cycle when m equals two, an unsuccessful reset pulse being discarded; and, after those updates in an accepted cycle, sending zero when L equals one and otherwise sending a normal binary heating request r supplied by a separate temperature controller, the relay supplying power for a one command and interrupting power for a zero command.

B0-2. The method of claim B0-1, wherein a program stored in a local memory causes the processor to perform the message acceptance, count updates, latch updates and relay command generation, and wherein the processor sends the command to the relay over a digital output line.

B0-1支持为P01、P03—P04；B0-2增加P06本地程序和数字线。相较C01，范围缩至具体异常控制链。P07出处及首样本/异常后历史温度等分支未知，只能作待核研发路线，不能当原申请或已可实施预测权项。

只保留有依据的100/150 ms、85/80°C、三次/两次和现场复位。改阈值、独立硬件或复位关系可能绕开字面范围，等同/概括另审，不扩为任意值。B0-2提供实现后备，但普通数字线未必增加103优势。删除无效切断会容许旧状态加热，放开当周期冷却与复位同时条件会容许过早按钮排队；两种反例归属不同。

101 Step 1：B0-1为实际控制过程。Prong One：温度比较、计数及年龄计算可能记载数学或逻辑概念；不把本案整体简化成“分析数据”。Prong Two：这些步骤共同限定何时允许来自独立温控器的供电请求、何时向实际SSR发0，以及恢复必须满足的现场条件，作用于加热器供电而非展示一个建议。P03—P05提供了该机制，权项也实际写入它，因而有理由主张整合了实际应用。这个意见来自有序因果链，不能仅凭“有硬件”得出。

2A整合成立时无需再做2B；若该解释被否定，重核有序组合及WURC事实。D1的SSR、D2计数已知不自动证明B0广泛常用或2B通过。101不减免102/103/112；其他软件可依计算机自身改善成立，物理执行器只是本案选择。

## 3. C0的112问题与具体改写理由

C01的optimization module将“优化服务”和“防止过热”合在一个结果式功能中，既未界定优化对象/准则，也未说明何种信息如何作用；C02又扩为any suitable algorithm、zero overshoot、至少30%效率改善，却没有基准、测量条件或达成全范围结果的技术教导。P02只能支持其具体服务规则，P03—P04只能支持固定供电保护，二者P06明示不共享决策状态。不能把任一算法说成对模块全部功能的支持。

112(a) written description看原公开是否显示占有所需组合/范围；C02效果字句不等于占有所有算法。enablement另问全范围实施是否需不当试验。P03—P04固定设计未教导任意负载零超调或任意算法达30%。不强制源码、样机或逐实现实测；Amgen全范围原则不等于软件逐例实验义务，固定稿仍待技术/专业核充分性。

112(b)看界限：C01优化/防过热规则不明，C02效率基准及零超调条件不明。B0/B1改写为温度、校验、计数、锁存、复位和命令，未用无法界定的“控制安全”结果替代步骤。

112(f)不取决于单独有没有means。C01无means通常有不适用推定，但optimization module可能是nonce占位词，关联功能且欠缺足够结构时可推翻；要按普通技术人员结合全文的理解判断。即使有means，足够结构/动作也可能改变推定。不能单靠改名module为unit、添加processor或一句不意图适用来规避。

若C01适用112(f)，应逐项找与全部功能明确关联的结构及算法，范围为对应结构/材料/动作及等同物而非任意实现；对这些专用计算功能，单一通用处理器通常不足。算法可由文字/流程/公式充分说明而不强制源码。本案P01/P06关联处理器、SSR和P03/P04固定算法；P02另有服务算法，但全范围优化、防过热及C02承诺未由这些有限步骤全覆盖。缺对应结构可带来112(b)和112(a)问题，不仅是“保护范围更窄”。即使112(f)最终不适用，112(a)/(b)问题仍在。具体方法B0/B1写明动作及关系，降低纯功能占位风险，但不预判美国专业解释必然结果。

## 4. 后到原件后的实际修改决定 V1

L1确认原始申请日为合成2025-08-01，说明书P01—P06与原C01—C02均属于原始公开；没有优先权/续案、附图或其他并入。P07为2025-09-10后加，因此预测式与Tprev分支没有当前案原始支持。保留P07于内部研发记录，不写入B1权项、核心说明或所谓新图。若后续考虑另案，程序侧另查日期、公开、支持和授权，不能让它继承旧日。

C02的零超调/30%字句既然原来已有，就不应称该字句本身为新增事项；问题是原记载未充分描述和教导实现所称全范围结果的机制。不能因字句在原权项就把后加P07视为其必然实现，更不能把“已写过”当实测。用P03—P06具体限定替换C01/C02，是从原技术教导重建明确候选；把P07补入说明书则涉及132(a)新事项，缺原始描述的新增权项涉及112(a)，程序处理有别。

L2只是一次合成台架记录，运行固定算法，没有实现P07；最高92°C相对85°C越过7°C。关断命令不能写成温度绝不超过85°C，原稿P05本来就提示热惯性。没有能耗或对照，30%无法计算。故本次删除C0的泛化功能/效果承诺，保留固定链及其命令层效果；从属后备补明已有断电重启行为。原C0、A0/B0与本说明全部保留版本，不覆盖首稿。B1没有借后到数据增加新控制步骤。

## 5. 当前申请替换候选 B1-CLAIMS

本节为完整英文候选组，重编号为1—3；它替换C0的两项，不与A0/B0混成同一组。不宣称已满足正式修改的标记/附页格式。

1. A method of controlling power supplied to a resistance heater in an experimental oven through a solid-state relay, performed by a local processor, comprising: initializing, at startup, a high-temperature count n to zero, a cooling count m to zero, a latch L to zero and a last accepted sequence number s0 to minus one, and sending a zero command to the relay; and performing the following in each control cycle of 100 milliseconds:

selecting, from received temperature messages, the message having the greatest sequence number, each message comprising a measured temperature T in degrees Celsius, a sequence number s, a sampling time ts and a validity bit q, wherein a sampling board producing the messages and the processor use a common monotonic clock;

accepting the selected message only if q equals one, s is greater than s0, and the difference between the current cycle time and ts is at least zero and at most 150 milliseconds, and updating s0 to s only when the message is accepted;

when no message is accepted, setting n and m to zero, setting L to one, keeping s0 unchanged and sending a zero command to the relay;

when a message is accepted, setting n to the smaller of n plus one and three if T is at least 85 degrees Celsius and otherwise setting n to zero, setting m to the smaller of m plus one and two if T is at most 80 degrees Celsius and otherwise setting m to zero, setting L to one when n equals three, and clearing L to zero only when a pulse from a local reset button is received in that accepted cycle and m equals two, while discarding a reset pulse for which those conditions are not met; and

after said updates in an accepted cycle, sending a zero command to the relay when L equals one and otherwise sending a binary normal heating request r received from a separate temperature controller, wherein the relay supplies power to the heater for a one command and interrupts power to the heater for a zero command, and L remains unchanged unless set or cleared by one of said operations.

2. The method of claim 1, further comprising, following an interruption of electrical power, restarting with the startup initialization and the zero command specified in claim 1 without retaining either count from before the interruption.

3. The method of claim 1, wherein a program stored in a local memory causes the processor to perform the acceptance, count updates, latch updates and command generation specified in claim 1, and wherein the processor sends the command to the relay over a digital output line.

## 6. 当前申请替换核心说明 B1-DESC

### 技术对象及方案

本设计涉及实验烘箱中加热器供电的本地控制。烘箱内设有电阻加热器、固态继电器SSR、温度探头、采样板及本地处理器。SSR接收1时为加热器供电，接收0时断开该供电。独立温控器产生取值为0或1的正常加热请求r；本地处理器位于该请求与SSR之间，其保护过程可将请求抑制为0，不将0请求变为1。

采样板发送包含探头温度T、序号s、采样时刻ts和有效位q的消息，温度单位为°C。采样板与处理器使用同一单调时钟。处理器每100 ms执行一个周期，并从已收到消息中选序号最大的一条。启动时，高温计数n及冷却计数m均为0，锁存位L为0，已接受序号s0为-1，并先向SSR输出0。电源中断后重新按此初始化，不保留先前计数。

### 有效性、计数及命令

每周期仅在消息有效位为1、序号大于s0且消息年龄在0至150 ms的含端点区间内时接受该消息。年龄由本周期时刻减去采样时刻得到。接受时将s0更新为本条序号；不接受则保持s0。无消息或所选消息不满足任一条件时，本周期无有效消息，处理器把n和m清0、将L置1，并向SSR发送0。

存在有效消息时，若T不小于85°C，将n加1并在3处封顶；否则将n清0。若T不大于80°C，将m加1并在2处封顶；否则将m清0。因此，n达到3反映三个相邻控制周期均接受高温消息，任何无效或非高温周期都会中断其积累。冷却计数同样要求相邻有效的低温周期。

当有效周期更新后的n为3时，将L置1。仅在该有效周期收到现场按钮复位脉冲且更新后的m为2时，才将L清0。不满足条件的按钮脉冲忽略且不排队保存，冷却满足后也不凭此前按钮自动恢复。除上述置位和清零外L保持原值。有效周期完成这些更新后，L为1则输出0，L为0则输出r。程序存于本地存储器，由处理器执行，命令沿数字输出线发送到SSR。

### 实施过程与作用

在r为1、已经完成正常有效低温周期的情况下，若随后相邻有效温度为86、79、86、86、86°C，高温计数依次为1、0、1、2、3，最后一个周期才因高温条件锁存断电。与此不同，无效消息在发生当周期直接触发0输出和锁存，不等待高温计数。故本方案把单个高温脉冲与持续高温序列区别处理，同时避免采集失联期间仅凭旧温度继续允许加热。

锁存后的恢复须当前有效冷却计数已达2并同时有现场按钮脉冲；第一次低温时过早按下按钮不会被保存用于以后恢复。这一关系防止仅低温达到或仅早先按钮动作就重新允许正常请求。输出0仅表示切断供电命令，不能说明箱体温度立即下降、不会越过阈值或具有确定节能比例。热惯性及继电器故障的实际响应尚需按对象条件验证。本核心稿表达原有固定设计，不包含预测温度公式、能耗试验、自动复位、远程复位或多探头融合。

### 图示与材料范围

原始申请没有附图，当前也未取得或制作图纸，P01文字连接关系是本稿依据。未出图、未渲染，不引用不存在的图1。是否需补绘只表达原有关系的图及其程序可接受性，由美国专业人员和制图负责人核验；新图不能用来增加P07机制。P02服务程序属于原始其他公开内容，当前核心稿选定固定物理路线，并不授权删除整份历史申请中的P02或改写原档案。

## 7. 原始支持、范围与文献意见

| 当前项/关系 | 原始依据和检查结果 | 边界及后续 |
| --- | --- | --- |
| B1-1硬件、100 ms、r门控、消息字段、共同单调钟及选最大序号 | P01；L1确认属于申请日原文 | 未概括为任意机器/周期，不主张改进处理器本身 |
| B1-1初始化、有效条件、s0更新、无效清计数/锁存/关断 | P03整段组合 | 150含等号、负年龄不接受、未自动删除序号校验 |
| B1-1高/低温计数、85/80、三次/两次、同时现场复位、丢弃过早脉冲及命令 | P04，与P03共同描述；P05解释命令层作用 | 只主张固定参数与现场按钮；保持位由原来仅列明置/清动作的状态语义解释，需技术/专业确认 |
| B1-2断电重启 | P04最后两句回指P03；所依1已经定义全部初态 | 实际限制重启行为，不是重复主项无新增限定 |
| B1-3本地存储和数字输出线 | P06，与P03—P04明确关联；所依1已有处理器和SSR | 普通实现后备，不宣称此项单独创造性 |
| C0原有结果与P07后加算法 | C01—C02确为原权项；P07未提交 | 原结果字句不能证明任意算法可实施，也不能支持新增预测器 |

独立项1已写入决定本稿作用的条件，不能再从说明书借隐含冷却、无效关断或按钮条件补范围。从属2、3都只依1，互不借兄弟项术语。英文将“只有”“不小于/不大于”“当周期”保持为only、at least/at most、in that cycle，没有将150变成严格小于或把现场复位译成任意远程授权。参数任意化需要新事实及范围审阅，当前不做。

101：B1维持B0有序控制链并显式列清状态保持，仍在2A Prong Two有整合实际应用的理由；取消零超调文字不取消物理动作。其实际改善主张是限制错误/失联状态下的供电许可，以及分辨瞬态与连续高温，未声称独立处理器架构改善。若审查解释改变，重新分析，不继承一张无版本的通过结论。112方面，B1以P03—P04明确算法和P01/P06连接作为描述/实施依据，完整功能与结构对应；没有用后到L2补新算法。支持表是开发核对，非合格美国专业人员的112结论。

| B1-1要素组 | D1全文对应 | D2全文对应 |
| --- | --- | --- |
| 烘箱探头/处理器/SSR及100 ms | D1-01有 | D2-01只有报警面板100 ms；D2-02只灯无SSR |
| q、新序号、同钟年龄0至150及相应s0 | D1-02无这些字段且沿用旧值 | D2-01有有效标志，没有序号/年龄/共同钟 |
| 三次相邻周期高温、无效清零并立即锁存关断 | D1-01即时温度开关，无计数/锁存 | D2-01三次有效异常报警，但无效跳过并保留计数，不等于本组合 |
| 两次有效低温与当周期现场按钮同时复位 | D1-01低温自动允许，无按钮 | D2-02按钮直接清报警，无冷却条件 |
| 启动状态、r门控及命令与状态有序关系 | D1仅温控允许，未给整套状态顺序 | D2仅报警关系，没有本电力控制链 |

按假定公开日，D1为2023-06-01、D2为2024-02-01，均早于L1的2025-08-01；本题没有其他早日关系。只在合成给定集合中，未见任一单篇给出B1-1全部要素及安排，故本集合不足以成立完整预见；不能把D1的SSR与D2三次计数拼成102单篇。旁证释义或固有性若另取须证明其有限用途，不能代补缺项。A0的信用/费用组合也未在这两篇出现，但这既不修复101，又不能代表实际业务算法查新通过。

103最强不利论证是：以D1烘箱控制为起点，为减少一次异常温度导致误断，控制技术人员有动机采用D2三次异常确认；两者均100 ms，数字比较与计数可实现，D2-03的设备报警触点可为接入保护信号提供进一步理由。因此，三次计数本身不宜作为足以授权的全部差异；只说D2没有明确写“用于烘箱”不足以反驳，灯输出改为抑制SSR请求也可能是可预期移植。

但得到B1全组合仍需解释为何改变D2无效保持计数策略为当周期清零、锁存及供电禁止，为何额外加入新序号和时龄校验，以及为何将D1自动低温允许和D2无条件按钮改为两次相邻冷却与现场脉冲同时满足。这些关系改变故障及恢复行为，不能只列部件后宣称已经结合。D2希望保留异常趋势，和本案优先停机的取舍不同；它未明示烘箱禁用本策略，不能夸成反向教导。普通失联保护、watchdog、interlock和人工复位知识可能给出这些改变的理由，仍需关键日前的真实资料和普通技术水平证据。

合理成功预期应分层：普通数字电路实现这些有限逻辑有可预期性；把它称能保持温度不越85或节能30%则缺对象动态及试验。L2没有与D1或D1+D2的相同条件对照，不能作为意外效果或商业成功证据。目前建议保留窄候选，围绕失联清零/锁存、时龄门控和冷却复位组合补检索；既不能凭两篇缺项宣称非显而易见，也不在没有证据时作必然显而易见结论。FTO、侵权及第三方有效权利未检索。

## 8. L2逐周期及边界推演

以下按原P03—P04纸面推演与给定合成日志比对，未执行控制固件、仿真或真实安全试验。初态为s0=9、n=0、m=2、L=0，r恒1；表中状态均为本周期更新后。

| now ms | 接受及理由 | s0 | n | m | L | 推演命令/原日志 |
| --- | --- | --- | --- | --- | --- | --- |
| 1000 | q=1，s=10新，年龄50，T=86 | 10 | 1 | 0 | 0 | 1/1 |
| 1100 | s=11新，年龄50，T=86 | 11 | 2 | 0 | 0 | 1/1 |
| 1200 | s=10不大于11且年龄250；两项同时无效 | 11 | 0 | 0 | 1 | 0/0 |
| 1300 | s=12新，年龄50，T=86 | 12 | 1 | 0 | 1 | 0/0 |
| 1400 | s=13新，年龄50，T=79；首个冷却周期 | 13 | 0 | 1 | 1 | 0/0 |
| 1500 | s=14新，年龄50，T=79；无按钮 | 14 | 0 | 2 | 1 | 0/0 |
| 1600 | s=15新，年龄50，T=79；当前有按钮 | 15 | 0 | 2 | 0 | 1/1 |

1200即使仅保留年龄校验仍会失败，仅保留序号校验也会失败，因此这条日志不能证明其中任何一项是唯一防线。无效后不仅不加计数，还清n/m并锁存；1300有效高温虽只n=1，不能擅自清L。1400按钮因m=1被丢弃，不排队；1500达到m=2但无新按钮，仍保持0；1600新按钮才使L清0并把r=1传给SSR。

边界输入独立从L2-04给定初态出发：s0=15、n=2、m=0、L=0、r=1。年龄150 ms、s=16、q=1、T=85时接受，s0=16、n=3、m=0、L=1，命令0，原因是含端点的有效第三次高温。把年龄单独改为151 ms则不接受，s0仍15、n=m=0、L=1，命令也0，但原因是时龄无效，而非达到n=3；不能把二者称同一状态。T=85不能计为低温，给定初态没有复位条件，因此未提供按钮值不影响这个边界结果。

吻合只及给定输入的逻辑。92°C即越过85°C达7°C，不能写零超调验证。技术负责人须补校准、负载、SSR实际电流、全曲线和对照，才谈更广性能/能耗，未做试验不得写成既成事实。

## 9. 具体交付和后续责任

正文候选包标识US-D8-B1，仅含本稿第5节B1-CLAIMS及第6节B1-DESC。支持/103/112分析及逐周期表为US-D8-I1内部审阅意见；原案M1/C0/D1/D2、L1/L2及后加P07单存US-D8-E1，P07再标研发用途。包标识表示本文确切章节范围，不表示已发送、已形成官方格式包或已运行硬门禁。A0/B0为保全历史，不混入B1当前权项组。

| 接续角色 | 具体任务与影响 | 当前状态 |
| --- | --- | --- |
| 技术负责人 | 核同钟/消息选择、状态保持、断电行为及P01—P06真实性；补真实负载/校准/曲线后才能改效果 | 待确认；本次只有合成材料 |
| 美国专业审阅者 | 以B1及原公开逐项核101/102/103/112、132、英文含义、从属限制及正式修改格式；核法条截至实际办理日版本 | 未签核，无真实委托主体 |
| 检索负责人 | 以2025-08-01及实际支持日为候选界，查烘箱失联联锁、连续判据及冷却/人工复位，核日期与常识来源 | 真实检索未执行 |
| 程序负责人 | 取真实递交包、OA及阶段，确认修改窗口；若拟另案P07或SMED，另核适用条件及签署责任 | 当前没有OA或期限，不虚构截止日 |
| 共享材料负责人 | 固定US-D8-B1正文及I1/E1分包版本/哈希，检查收件对象、保密用途、渠道及附件权限 | 仅内部本地使用已授权 |

本地分析/写稿/保存已授权。下一步拟让美国代理保密审阅B1及依据，但代理、地址、渠道、委托及签核均未定，发送未授权、未执行。I1/E1不默认随正文发，也不能向受托审阅者隐瞒相关不利事实，须明确所需附件许可；P07、完整日志、营销材料不属默认正文包。对象/用途变化后重绑批准。

逐动作交接以US-D8-B1、I1、E1为当前内容版本；下列S1、F1、P1、N1是待形成的专用包标识，尚无文件或批准，不能用这张表代替实际固定包。B1两份正文不因本次交接补充而改变；内部原件和不利记录继续保留。

| 具体动作与文件范围 | 对象、用途与渠道 | 批准责任、状态与恢复条件 |
| --- | --- | --- |
| 本地分析/存档：B1第5/6节，I1第1—4/7—9节，E1原案与L1/L2 | 当前项目内部技术、检索、程序及材料负责人；用于审阅准备；现有本地工作区 | 本轮用户已授权合成材料本地处理，已完成候选；共享材料负责人维护版本/hash，不据此放行真实材料或外发。 |
| 美国代理保密审阅：拟B1-CLAIMS、B1-DESC及按审阅需要许可的I1/E1具体附件 | 实际美国代理姓名/地址待程序负责人核；用途是范围/英文/修改审阅；拟代理认可的受控交付渠道待核 | 权利人或其有权授权负责人批准具体接收人、文件字节、用途及有效条件；美国专业人员/材料负责人先核委托、保密和附件权限。当前未组批准包、未发送；补齐后发送前重核hash、记录回执，不隐瞒相关不利事实。 |
| SMED声明起草与签署：未来S1仅含针对明确101争点的声明、证人事实基础及经许可支持附件；L2若使用须保留合成/未实测性质，不能当真实证言 | 拟由具有实际知识基础的真实声明人签署，供美国专业人员准备USPTO证据用途；拟签署渠道须由程序负责人核身份/形式 | 美国专业人员先补核未取得的2026年4月全文、阶段和可接纳性；声明人确认实际亲历与全部事实，权利人有权负责人另批用途/版本。当前无声明人、无S1、无签署；缺真实基础时不得以本例生成真实声明。签署不自动授权提交。 |
| USPTO修改或声明提交：未来F1仅含经专业核定的B1正式标记/附页、实际意见答复及被单独批准的S1；不默认附P07或完整I1/E1 | 接收方USPTO，目的为具体真实案的修改/证据提交；经核代理权限的官方账户/渠道，账户及案号当前未知 | 美国专业人员核真实原始公开、OA/阶段/期限、形式和112/132；申请人或有权负责人明确批准F1及提交动作，程序负责人发送前核包/账户并保存回执。当前没有F1、OA、真实案号或提交授权，未提交；不得把代理审阅同意当提交许可。 |
| 公开：未来P1为逐内容支持及保密审核后选出的公开摘录/图文，具体字节尚未选定，B1/I1/E1均不自动进入 | 公开受众和目的由权利人明确；网站、会议或其他渠道逐项指定，当前未定 | 权利人有权负责人批准具体公开包/渠道/日期；专利程序与材料负责人先核真实申请支持、公开前保护及附件权利。当前未形成P1、未批准、未发布；申请号或内部审阅通过均不替代此步骤。 |
| P07另案申请：未来N1为补齐首样本/异常后Tprev/优先关系后的独立技术稿及申请材料，保留P07后加日期 | 目标申请人、国家/受理局及代理待核；用途为独立新申请；具体官方渠道由程序负责人核定 | 技术负责人先补真实完整机制，美国及目标地专业人员核日期/公开/支持/权属；权利人有权负责人另批N1和申请动作。当前只有内部研发便笺，无N1或另案授权，未申请，不沿用旧申请日。 |
| 付款：未来已核委托书/官方费用单所列项目与金额 | 实际代理或官方收款方待核；用途限具体服务/程序；财务核定渠道 | 权利人财务有权人批准金额/收款方，程序负责人核费用事项及对应动作授权。当前无费用单/新付款授权，未付款；提交、签署或资料审阅许可不能代替付款许可。 |

所有未来专用包仍需实际文件、精确字节/hash及批准记录，状态变化只影响对应动作；结果不明先核回执，不盲目重试。支持核对、英文、纸面推演、真实检索、显示及专业签核分计；无实际附图、实验、外发回执或官方认可，不关闭既有独立验收缺口。
<!-- END D8-USPAT WORK PRODUCT -->

## 冻结原题原文

以下JSON为开发前冻结原题的完整字节副本；其中的用户任务、原件、后到材料和自带content哈希均保留。它是示范阅读材料，不能当作正文已经完成要求的证据。

```json
{
  "id": "D8-USPAT-01",
  "version": "stage1-frozen-design-v1",
  "synthetic": true,
  "scope": "US AIA后实用专利；软件业务与实际物理控制；已申请后内部改稿；全部材料原创合成。",
  "user_request": "请审阅实验烘箱项目的美国专利路线。先按起初M1/C0/D1/D2所能知道的范围，实际写路线A的业务安排独立权项和路线B的物理控制独立权项，至少一条有依据的从属后备；两路线都要说明取舍，不用表格提纲代正文。明确101分析各步、112(a)/(b)/(f)、给定D1/D2的新颖性和非显而易见性风险，不能把技术性等于新颖性或授权。P07出处未知时说明条件，不当已提交事实；把客户的泛化权项与功能措辞具体改清楚。用中文解释、英文给权项，英文改写不得扩展数值/条件。",
  "later_request": "收到L1和L2后，请保留起初路线分析并作一次完整改稿：交当前申请可供美国代理审阅的最终替换权项组及完整中文核心说明（技术对象、方案、实施步骤、异常/复位和效果），逐项映射实际原申请支持，说明P07及零超调/30%为何怎样处理，按L2逐行和两个边界输入做可复核文字推演。继续对最终权项做101与102/103、112分别分析，提出最强不利组合理由及实际缺证。将正文候选与内部原文/风险/测试记录分包，列具体复核责任、版本、对象/用途/渠道/许可状态及允许的下一步；不要提交、签署、发布、发邮件或替申请人宣誓。",
  "release_disclosure": "作者会同时看到全部阶段材料；阶段只用于开发叙述，不是盲释放、独立评测或专业验收。",
  "permission": "仅本地合成材料分析与公开官方规则研究；无真实案件外发、检索账号、测试机器、签核或正式提交授权。",
  "artifacts": [
    {
      "id": "M1",
      "title": "混编研发/申请讨论包 MIX-US-3",
      "kind": "synthetic_primary_material",
      "content": "[P01] 项目为实验烘箱控制器。壳体内有电阻加热器、固态继电器SSR、温度探头、采样板和本地处理器。SSR收到1才给加热器供电，收到0则断开加热器供电；处理器每100 ms执行一个控制周期。正常加热请求r为0或1，由独立的已有温控器给出。本设计位于温控器与SSR之间，只能把r改为0，不能把r=0改为1。探头值T的单位为°C，板上传的消息含T、序号s、采样时刻ts、有效位q。板与处理器使用同一单调时钟；每周期仅取已收到消息中序号最大的那一条。\n[P02] 路线A为合同服务安排。用户输入客户编号、订单金额v、信用级别c（0、1或2）及等待小时h；处理器计算a=2*c+min(h,24)，按a降序、同分按客户编号升序显示烘箱服务顺序，并估算费用v*(1-0.02*c)。没有温度输入、控制总线或自动下发；操作者可自行决定是否照表安排。界面与排序均为普通表格程序，未提出新的数据结构、计算机性能或通信机制。\n[P03] 路线B的固定保护算法为：启动时高温计数n=0、冷却计数m=0、锁存位L=0、已接收序号s0=-1，并先向SSR发0。每周期now，消息仅在q=1、s>s0、0<=now-ts<=150 ms时有效；否则本周期无有效消息。有效消息才把s0改成s。无有效消息时n=0、m=0、L=1，并发送0。s0在无效周期不变。\n[P04] 有效周期中，T>=85时n=min(n+1,3)，否则n=0；T<=80时m=min(m+1,2)，否则m=0。若n=3，L置1。只有收到现场复位按钮的该周期脉冲且本周期有效、m=2时，L才可清0；按钮脉冲不排队保存，冷却计数不满足就忽略。有效周期在以上状态更新后，L=1则发送0，L=0则发送r。电源中断后重新执行P03启动，不保留旧计数。故障后的复位需要两次相邻有效冷却周期；没有自动复位。\n[P05] 这个固定方案将单次高温脉冲与连续三个有效高温周期区别处理，并使数据失联不能以旧温度维持加热请求。设r恒1，从启动后已完成正常有效低温周期开始，T依次为86、79、86、86、86时，n依次应为1、0、1、2、3，只有最后一个周期因高温锁存切断。只要数据无效则当周期切断，与是否达到三次高温无关。继电器供电关断不等于箱体温度立即下降；热惯性、继电器故障等尚未验证。本稿只有确定性设计及纸面推演，没有实验。\n[P06] 本地存储器存有实现P03—P04全部步骤的程序，处理器经数字输出线连接SSR。没有图纸文件；本文P01就是已知连接关系，不存在可引用的图1。保护计数器是普通整数，未说明高速硬件比较器或特定处理器架构。范围没有披露其他阈值/周期/计数值、远程复位或多个探头的融合。客户层可与物理控制器同机运行，但A的信用/费用数据从不参与P03—P04，两个程序不共享决策状态。\n[P07] 新研发笔记：为了在快速升温时提前关断，增加p=T+(T-Tprev)*2。连续三次p>=85也触发锁存；Tprev由最近有效温度更新。笔记未说明首个样本、无效消息后的Tprev、复位或与P03—P04的优先次序。营销页草句称“预测模型在任意负载均保持零超调，减少能耗30%”。混编包未列P07是否原申请内容，也没有支持这句话的数据。",
      "sha256": "c01c742900162dbe5a0b1fae74a2491ad4d9b325f003f5eb3405c1155be6f5f3"
    },
    {
      "id": "C0",
      "title": "客户提供当前候选权项 US-v0",
      "kind": "synthetic_current_claims",
      "content": "[C01] 1. A system comprising a processor and an optimization module configured to optimize oven service and prevent overheating by processing information and controlling an oven.\n[C02] 2. The system of claim 1, wherein the module uses any suitable algorithm to achieve zero overshoot and improve energy efficiency by at least 30 percent.\n[C03] 客户希望保留上述“宽表达”，认为美国只要写processor就不是抽象概念，且不写means就不可能适用112(f)。这只是客户意见，不是法律结论。现阶段要交中文说明与可审阅英文权项；中国或EP稿式不应直接套入美国分析。",
      "sha256": "34210cc144b46eb142ebb41a3860889f3c0b921fb6f06b46e6617a77a7cf9c77"
    },
    {
      "id": "D1",
      "title": "SYN-US-THERMO，有限给定公开材料全文",
      "kind": "synthetic_prior_art",
      "content": "[D1-01] 本合成教学文献假定于2023-06-01公开；全文仅本记录三段，无真实公开号或申请人。实验烘箱有探头、处理器、SSR及加热器。每100 ms读取温度，T>=85°C时继电器断电，T<=80°C时自动允许正常温控请求；80<T<85时沿用上周期开关许可。\n[D1-02] 每周期使用最近收到的温度，不带采样时刻、有效位和序号。无新消息仍使用旧值。文献没有高温连续计数、锁存位或现场复位按钮，也没有服务信用排序。\n[D1-03] 单阈值异常值可能导致一次断电，自动允许有利于无人看守连续作业。本文未给故障统计、升温曲线或节能数据；没有对用户方案作评价。",
      "sha256": "4bc66c8408722a2eb6a79cce4ff09233614bf690ec137c399c097dfd4c2c0e79"
    },
    {
      "id": "D2",
      "title": "SYN-US-DEBOUNCE，有限给定公开材料全文",
      "kind": "synthetic_prior_art",
      "content": "[D2-01] 本合成教学文献假定于2024-02-01公开；全文仅本记录三段。通用数字报警面板每100 ms收到一个有效标志和一个异常位。异常位为1时计数加1，连续三个有效异常输入使报警灯亮并保持；有效正常输入使计数清0。无效周期跳过计数，原计数保持；它把“连续”定义为有效输入序列中连续，不要求相邻控制周期。\n[D2-02] 报警后的现场复位按钮直接清报警，无须两次低温条件。系统只点亮灯，不驱动加热器；未使用温度数值、时间戳或序号，也没有SSR。设计理由是忽略采集间断而保留此前的异常趋势，减少短期无效输入造成的报警延误。\n[D2-03] 文献说通用面板可接设备报警触点，但未说明改变恒温器供电路径的具体连接。没有证明其处理策略不适合烘箱，也未给失联安全停机建议；不得把缺少该建议改写成明确反向教导。",
      "sha256": "1e181dfb49e2332eacba1d7454209a477b94760f43f4561b24a93b5e95716a7d"
    },
    {
      "id": "L1",
      "title": "后到归档原件记录 FILED-US-A1",
      "kind": "synthetic_late_original",
      "content": "[L1-01] 2026-10-30档案员交回本合成案的2025-08-01原始美国非临时申请归档清单及全文比对记录。说明书内容恰为M1的P01—P06，逐字符相同；原始权项就是C01—C02。没有附图，没有其他并入材料，没有优先权或续案关系。本记录不是实际Patent Center回执，号码省略以免伪造真实官方案卷。\n[L1-02] P07来自2025-09-10后加研发便笺，未随2025-08-01申请。原文件没有p预测式、Tprev更新、任意负载零超调或30%效果依据。客户此前把含P07的MIX-US-3当原申请全文是归档混淆。原始C02有结果式“零超调/30%”文字，不等于说明书披露实现该结果的机制。\n[L1-03] 只要求内部修改方案与代理人审阅材料，不提供任何官方OA、答复截止日或真实代理授权。应分别指出P07的新技术和用原P03—P06解释现有控制步骤的不同处理；不要生成虚构审查意见或官方结论。",
      "sha256": "029f302a1f9f9685f4a4c4947276852547d3619d9c6523c95dc43b86086a4af4"
    },
    {
      "id": "L2",
      "title": "后到试验原始记录 RUN-FIXED-01",
      "kind": "synthetic_late_original",
      "content": "[L2-01] 2026-10-31研发员提供以下原创合成原始记录，假定是内部台架一次运行的逐周期导出；不代表真实实验或专业认证。运行固件只实现固定P03—P04，未实现P07；r=1，测试前已有有效T=78、已接收序号s0=9、L=0、n=0、m=2。取样/收件同钟，单位ms/°C。字段为now,ts,s,q,T,reset,command。记录未提供独立校准、完整物理负载或外部重复。\n[L2-02] 1000,950,10,1,86,0,1\n1100,1050,11,1,86,0,1\n1200,950,10,1,86,0,0\n1300,1250,12,1,86,0,0\n1400,1350,13,1,79,1,0\n1500,1450,14,1,79,0,0\n1600,1550,15,1,79,1,1\n[L2-03] 1200周期同时存在重复序号及年龄250ms两项无效理由。1400的按钮发生在第一个冷却周期；1500无按钮；1600才有符合条件的现场复位。独立温度记录只给本次SSR命令变0后读数最高92°C，不含完整曲线；相对85°C为7°C越过。客户营销仍想把关断动作写成“温度不超过85°C”，但本记录不支持。未记录用电量或对照机，无法算30%节能。\n[L2-04] 边界题是假定输入而非另一实验：已收序号15，本周期收到s=16、q=1、now-ts=150、T=85，且L=0、n=2、m=0、r=1。另有对照输入保持其他条件仅把年龄改151ms。说明各自状态/命令与原因，不把150ms边界说成无效，也不借对照证明哪项校验是唯一防线。",
      "sha256": "383bd6b4276dd5ff9dd4f01fa1ced71eed8b115d59418b68c17d7c21dde1b94f"
    }
  ],
  "output_expectation": "正文是实际权项/核心说明/论证与具体交接，约12—24KB；无需制造图纸或完整官方表格。首稿和改稿分别标版本，不只提供修订指令。"
}
```
