# 青屿：国际来源对照、两版候选与合同过渡完整示范

本例是cross-region-d7开发首答。所有SYN标准、青屿主体、数值、合同和未来时间均为自创合成资料，采用本项目许可，不复制真实标准，不是现实申请或国家标准。题目附录保留原JSON字节；学习运行只需本文件和[方法](international-adoption-method.md)、[公开研究](../../../references/standards/international-adoption-evidence-20261101.md)，不依赖开发评测或outputs目录。

<!-- BEGIN D7-ADOPTION WORK PRODUCT -->

## 1. 本次结论与工作状态

交付QY-ADOPT-D1及D2两份完整中文候选。D1修复D0的绝对误差定义和维护模式自相矛盾；同时保留已确认的技术提议。D2吸收后到源2026版的48 h和GAP要求。二者均不能标“IDT中文稿”：源2024允许维护时不采样及旧时间格式，D1/D2拒绝这些行为；D2与源2026仍有温度指标、环境和manifest差异。

方法类比上，两版保留源的主要结构、对象、采样、测量、响应、留存和标识链，差异可定位，倾向MOD的实质方向。真实采标类别不成立：SYN源并非真实国际标准，青屿无归口委托，GB/T 1.2—2020正文未获许可读取。这里研究的真实目标是总局／国家标准委体系下推荐性国家标准的立项前预研，不是虚构一个能批准GB的组织。

规则依据采用2025年第102号令（https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2025/art_f32bbf79511348699d385a86cf1fffa0.html）的公开条文及官方修订解读（https://www.samr.gov.cn/xwxcs/xwxc/art/2025/art_7fe29632d88849aab439d5d7434e599f.html）。2001旧办法、GB/T 20000.2—2009不作为当前依据；2020年第26号国家标准公告第1项明确GB/T 1.2—2020替代GB/T 20000.2—2009及GB/T 20000.9—2014，自2021-06-01实施；旧GB/T 20000.2—2009目录同日标废止（研究A04，公告：https://std.sacinfo.org.cn/gnoc/queryInfo?id=A3AAE367213CB7CBF4812C565A033D5B）。GB/T 1.2—2020公开页面（https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=A4CDFE74D18CBE2DB888C5A2274C1A4F）仅支持目录状态，未取得正文。ISO页已观察到AI使用限制，未继续取得或改写其标准全文。未执行真实试验、互通、专业签核、组织程序或发送。

## 2. QY-ADOPT-D1完整候选正文

### 农业仓储非安全温度记录器——快照记录

文件版本：QY-ADOPT-D1，内部合成技术候选。源比较基线：SYN-ORBIT-LOG:2024。无正式国家标准编号、采标标记或生效日期。各项要求仅用于本合成技术方案，不构成真实监管阈值。

前言。 本稿以自创源文为比较基线，保留其基本结构，提出维护连续记录、0.30 ℃指标、30 ℃环境、新时戳、事件和manifest等技术变化。变化的工程合理性及适用性待验证。规范性内容为第1—9章及附录A；本前言为说明。

### 1 范围

本文件规定农业仓储非安全温度记录器的快照、维护事件、示值性能、启动响应、断电保留、导出和验证。医疗使用、食品安全判定及安全控制不在范围内。

### 2 规范性引用

SYN-CLOCK:2026《合成UTC时戳格式》为唯一规范性引用，仅该版适用，后续版不自动纳入。其完整自创文本译写于规范性附录A；附录A足以确定本稿时戳要求。

### 3 术语

3.1 工作模式：记录器正在记录快照的状态，包括短时通信中断；维护模式不属于工作模式。

3.2 绝对示值误差：温度示值减参考温度的差的绝对值，即 `a = |T_ind − T_ref|`，单位℃。

3.3 维护模式：本机选择、具有可见提示的服务状态；在此状态下快照记录继续。

### 4 快照及维护事件

4.1 工作模式和维护模式均应每60 s至少记录一条快照。快照包括device_id、timestamp和temperature。device_id由1—16个大写ASCII字母或数字组成；timestamp符合附录A；temperature以℃为单位，固定两位十进制小数，负值带负号。

4.2 快照应保留采集顺序。时戳格式适用SYN-CLOCK:2026，不因格式相似而接收2024版字符串。

4.3 每次进入和退出维护模式均应记录事件，按事件发生顺序保存于独立文件events.csv。每行依次为`device_id,timestamp,event`；前两字段分别符合4.1和附录A，event仅可为`ENTER_MAINT`或`EXIT_MAINT`。文件使用UTF-8编码，无表头，以LF结束每行。

### 5 示值性能

环境温度为（30±2）℃时，在5.00 ℃、15.00 ℃及25.00 ℃三个参考温度点，每点的绝对示值误差应不大于0.30 ℃。第8章的区间判定规则适用，不仅比较中心值。

### 6 启动响应

工作模式下，有效START请求的末字节到达记录器后，ACK末字节应在500 ms内发出。起点为请求末字节到达时刻，终点为ACK末字节离开时刻；500 ms包括等于边界的情形。本条不为维护模式增设START响应要求。

### 7 保留和导出

7.1 断电后全部快照和维护事件应保留至少24 h。

7.2 快照应按采集顺序导出为UTF-8逗号分隔行，字段依次为`device_id,timestamp,temperature`，无表头，每行以LF结束。events.csv按4.3输出，分别保持其自身事件顺序。

7.3 导出目录还应包含manifest.txt，UTF-8编码，内容恰为以下两行且每行以LF结束：

```text
profile=QY-D1
clock=SYN-CLOCK:2026
```

### 8 验证

8.1 用同一待验证记录器，记录型号、固件和配置版本。检查连续120 s工作区间和连续120 s维护区间，覆盖进入、退出维护操作和一次工作模式通信中断；留取边界前后快照以判断60 s区间要求。检查字段、时戳、快照采集顺序和事件发生顺序。发现间隔超限时记不满足；不能以事件存在代替快照。

8.2 环境保持（30±2）℃；在参考温度5.00 ℃、15.00 ℃、25.00 ℃各稳定10 min后取5个示值，计算每个参考点的最大绝对误差a，并记录该点扩展不确定度U。使用有有效校准及溯源记录的参考温度装置；设备、校准、环境、稳定过程、原始示值及U的评定依据均应记录。无有效U时不作本规则的确定符合结论。

8.3 对上限L，若`a+U≤L`，该点数值满足；若`max(0,a−U)>L`，该点数值不满足；其余为不确定。三个点都需评价。该规则是本合成方案给定判据，不宣称是通用真实标准规定。

8.4 工作模式发送10次有效START，使用经校准的计时或抓取装置观测规定起止点，记录每次时间及计时不确定度。对最大时间及其对应不确定度应用8.3的上限区间规则，L=500 ms；若各次不确定度不同，应另核所有次的上界，不能只凭最大中心值覆盖其他次。记录单位换算和抓取配置。

8.5 取得快照和维护事件基线后断电24 h，恢复供电，逐条比对导出快照、events.csv与基线，检查数量、字段、数据及各自顺序，并检查7.3的manifest两行、编码和行尾。断电状态不是工作或维护记录状态，本稿未要求断电期间采样。

8.6 完成记录文件、说明书及附录A正负例的检查，分别报告方法执行、数值判定、不确定项及未覆盖模式。本章是验证要求，写入本稿不代表已完成试验或认证。

### 9 标识

说明书应注明实际实施的文件版次和时戳版次。仅实施本稿时标QY-ADOPT-D1和SYN-CLOCK:2026；不得借此声称真实国际或国家标准认证。

### 附录A（规范性）SYN-CLOCK:2026完整格式

时戳恰为24个ASCII字符，格式`YYYY-MM-DDThh:mm:ss.sssZ`，表示有效公历UTC日期时间。年份2000—2099，小时00—23，分和秒00—59，sss恰为3位十进制数字。时区偏移和闰秒值60均无效；除所述格式外的字符串无效。有效例为`2026-11-01T12:00:00.000Z`。

仅当2024版原记录的采集时刻已知精确到整数秒时，才可插入分隔符及`.000`转换；应保留原记录并记录转换，不得声称新测得毫秒精度。转换例：`20261101120000Z`在满足该前提时转换为上述有效例。未知秒内时刻不可依此编造精度。

## 3. 拟对外技术文件一：D2完整正文

以下独立内容对应实体文件`outputs/cross-region-d7/adoption-package-r2/adoption-d2-body.md`；四份技术材料均为待签核候选，不能从本合订示范直接发送。

#### BEGIN ADOPTION PACKAGE BODY
# QY-ADOPT-D2：农业仓储非安全温度记录器——快照记录

版本D2；原创合成内部候选。源比较基线SYN-ORBIT-LOG:2026。无真实GB编号、采标标签、生效日或认证。第1—9章和附录A为本合成技术方案的规范性内容。

前言：本稿吸收源2026版的48 h保留和GAP记录，保留本地0.30 ℃、（30±2）℃及manifest技术提议；适用性待验证，不声称已获任何组织批准。

## 1 范围

本文件规定农业仓储非安全温度记录器的快照、维护及间断事件、示值性能、启动响应、断电保留、导出和验证。不适用于医疗、食品安全判定或安全控制。

## 2 规范性引用

仅SYN-CLOCK:2026《合成UTC时戳格式》适用，后续版本不自动纳入。其完整自创格式写于规范性附录A，无需另找输入题目。

## 3 术语

3.1 工作模式：记录器正在记录快照的状态，包括短时通信中断；维护模式不属于工作模式。

3.2 绝对示值误差：温度示值与参考温度之差的绝对值，`a = |T_ind − T_ref|`，单位℃。

3.3 维护模式：本机选择、具有可见提示的服务状态，此时快照记录继续。

## 4 快照和事件

4.1 工作和维护模式均应每60 s至少记录一条快照。快照含device_id、timestamp、temperature；device_id为1—16个大写ASCII字母或数字，timestamp符合附录A，temperature以℃表示并固定两位十进制小数，负值带负号。

4.2 快照应保留采集顺序；时戳使用SYN-CLOCK:2026，不接收旧格式作为本版输出。

4.3 每次进入及退出维护模式应记录事件，发生顺序保存于独立events.csv。行字段为`device_id,timestamp,event`；前两字段分别符合4.1及附录A。event可为`ENTER_MAINT`、`EXIT_MAINT`，或符合7.4的`GAP`。文件为UTF-8、无表头、每行以LF结束；事件按发生顺序保存。

## 5 示值性能

环境温度（30±2）℃时，在5.00 ℃、15.00 ℃、25.00 ℃每个参考点，绝对示值误差应不大于0.30 ℃。按第8章含不确定度规则判断。

## 6 启动响应

工作模式下，有效START请求末字节到达后500 ms内，应完成ACK末字节发送。起止点分别为上述到达和离开时刻；边界等于500 ms包含在上限内。维护模式无本条新增响应要求。

## 7 保留、导出与采样间断

7.1 断电后全部快照和事件应保留至少48 h，包括维护事件和GAP事件。

7.2 快照按采集顺序导出为UTF-8逗号分隔行，字段为`device_id,timestamp,temperature`，无表头，每行以LF结束。events.csv符合4.3并保持事件发生顺序。

7.3 导出目录还应有UTF-8编码的manifest.txt，内容恰为以下两行，且每行以LF结束：

```text
profile=QY-D2
clock=SYN-CLOCK:2026
```

7.4 对供电运行期间每次超过60 s的采样间断，应在恢复后第一条快照的时戳记录恰一条GAP事件。GAP不豁免4.1的60 s要求，间断仍应记录为不满足。断电期间无采样义务，不能仅因断电间隔强制生成本条GAP；有供电运行中的间断时按该实际间断判断。

## 8 验证

8.1 固定一台待验证样机的型号、固件和配置。检查连续120 s工作及120 s维护区间，覆盖维护进入、退出及一次工作模式通信中断；保存观察边界前后快照，检查字段、时戳、采集间隔、采集顺序及事件发生顺序。检查事件不可代替快照。

8.2 环境维持（30±2）℃，参考温度5.00 ℃、15.00 ℃、25.00 ℃每点稳定10 min后取5次示值，计算该点最大绝对误差a和对应扩展不确定度U。使用校准有效且可溯源的参考温度装置，记录设备、校准、环境、稳定过程、原始数值和U评定依据。缺U不能作本规则的确定符合结论。

8.3 对上限L，`a+U≤L`为该点数值满足；`max(0,a−U)>L`为数值不满足；其余为不确定。温度L=0.30 ℃，三点分别评价。若各读数U不同，核全部读数区间，不只取最大中心值。此为给定合成判据，非通用真实规则。

8.4 工作模式测试10次有效START，以经校准的计时或抓取装置测量第6章起止点，逐次保存时长、单位、计时不确定度及抓取配置。对最大时长与其对应不确定度应用8.3的区间法，L=500 ms；另核其他次区间是否更不利。

8.5 保存快照和维护／GAP事件基线，断电48 h后恢复，逐行核对导出记录的数量、数据和各自顺序；核7.3两行、编码和LF行尾。另在有供电状态下注入超过60 s的采样中断，检查恢复第一快照时戳的一条GAP，并同时记录4.1不满足。故障注入用于证明检测行为，不把被强制产生的超限当正常运行合格。

8.6 检查说明书、规范字段及附录A正负例；按版本分别记录计划、实测、数值判定、不确定和未覆盖范围。本章不证明已经试验、互通或认证。

## 9 标识

说明书应列实际实施文件版次及时间格式版次。仅实施本稿时列QY-ADOPT-D2及SYN-CLOCK:2026，不宣称真实标准认证。

## 附录A（规范性）SYN-CLOCK:2026完整格式

时戳为恰24个ASCII字符`YYYY-MM-DDThh:mm:ss.sssZ`，表示有效公历UTC日期时间。年份2000—2099，小时00—23，分、秒00—59，sss恰3位十进制数字。时区偏移、闰秒值60及所有其他字符串均无效。有效例：`2026-11-01T12:00:00.000Z`。

从2024版转换，仅当采集时刻已知精确到整数秒时可插入分隔符及`.000`；保留原记录和转换记录，不得称新测毫秒精度。`20261101120000Z`在满足前提时可变为上述例，未知秒内时刻不能这样制造精度。
#### END ADOPTION PACKAGE BODY

## 4. 拟对外技术文件二：差异、类别与替换说明

#### BEGIN ADOPTION PACKAGE DIFFERENCES
# QY-DIFF-D2：源版本、目标对应和修订说明

版本D2，原创合成技术讨论候选；对应QY-ADOPT-D1/D2。所有源文使用SYN编号，均非真实国际标准。以下结论不是正式采标类别或组织审查结果。

## 4.1 源2024到D1的完整对应

| 源位置 | D1位置 | 变化及性质 | 提议理由、反证与验证影响 |
| --- | --- | --- | --- |
| 标题、前言性说明 | 标题、前言 | 中文表达及状态说明；删除D0未经依据的IDT主张 | 标题本身无技术变化；不得用中文外观证明等同 |
| 1 | 1 | 对象及三类排除保留 | 不把农业仓储稿扩大成食品安全或医疗规范 |
| 2 | 2、附录A | 注日期引用2024→2026，技术差异 | 计划提供统一毫秒字段；旧15字符输出在新24字符语法下无效，需双版互通验证 |
| 3.1 | 3.1 | 工作模式定义保留，译名无新增外延 | 通信中断仍是工作模式；不能因此免采样 |
| 3.2 | 3.2 | 相对源定义保留；D0漏绝对值属缺陷修复 | −0.80不能作为“≤0.30”合格误差；需绝对值反例 |
| 3.3 | 3.3 | 维护从暂停改继续，技术差异；同时修D0内在冲突 | 提议减少服务期记录盲区，维护实现代价和可靠性未验证 |
| 4.1 | 4.1 | 移除维护豁免；字段规则保留 | 扩大采样义务，源允许无维护快照的实现不满足D1；维护区间需验证 |
| 4.2 | 4.2、附录A | 采集顺序保留；时戳切版 | 格式变化不可当排版；转换不得制造精度 |
| 4.3 | 4.3 | should→应；新定事件文件格式，技术差异 | 服务状态可追溯是提议；源中不记录维护事件的实现仍可能满足建议层次，D1不接受 |
| 5 | 5、8.2/8.3 | 0.50→0.30 ℃，20±2→30±2 ℃，两项独立技术差异 | 提议更窄误差及较暖环境；没有真实性能证据。更严不等于更适用，也不能从30℃外推20℃ |
| 6 | 6、8.4 | 0.500 s→500 ms精确等价，无技术阈值变化 | 1 s=1000 ms；起止、模式、含等于和取最不利区间保留。若舍入或改成首字节即变技术内容 |
| 7 | 7 | 24 h与快照导出基本保留；事件保留明确化，增加manifest为技术要求 | profile/clock让使用者识别配置；源不要求manifest，缺文件实现被排除；检查事件留存和两行字节 |
| 8 | 8 | 完整本地方法；维护观察60→120 s，改环境和时戳，覆盖事件/manifest | 120 s沿D0确认的维护持续采样目标补足跨60 s边界观察；这是候选验证方法补充，非源规则原文；重新评议方法适用性 |
| 9 | 9 | 版次标识义务保留并绑定目标 | 不把候选版本号当认证标志 |

原稿D0第8章只写“沿用”，在环境、模式和引用已改变时不可执行，故D1写出实际完整方法。D1的扩展方法、设备记录和不确定度记录要求均是合成验证计划展开，不宣称源中隐含同样文字；实质新增需随正文审阅。

## 4.2 类别分析与可推翻结论的事实

D1相对源2024不满足IDT实质：旧时戳和维护无快照这两类源允许行为在D1被排除，不涉及对测量不确定度的猜测；阈值、环境、事件和manifest还进一步改变接受条件。0.500 s与500 ms本身不构成这个反证。

D1保留源1—9章的核心目的、记录实体、60 s间隔、三参考点、绝对误差概念、START起止、导出顺序和版次标识，重要技术链仍对应；在允许真实采用且理由充分的前提下，可以提出MOD方向。不过不能按章数“9/9”证明保留大部分重要内容，需技术组逐项确认本地变化是否使原来的关键目的仍实现。

D2相对源2026的维护连续记录、2026时戳和强制事件已趋同，但温度指标0.30对0.40、环境30±2对20±2及manifest仍不同；IDT仍被排除。反向也不能说D2必然符合源2026：仅在30℃测试满足不能证明20℃条件满足。

NEQ不作为差异多、缺许可或缺全文的兜底标签，更不称“NEQ采用完成”。本案正式采用标签不成立，原因是源资格虚构、委托和完整编写规则/许可缺失。仅技术比较和MOD方向建议可交付；恢复正式判断需真实源资格、合法全文/处理权限、完整规则、适用性证据和有权审阅。更严格的数值仍需可行性证明，不能仅以国情为笼统理由。

## 4.3 后到源2026相对D1：独立基线

| 源2026位置 | D1当前状态 | D2处理与仍存差异 |
| --- | --- | --- |
| 1 | 范围一致 | 保留；D2标题/范围提及间断事件不扩至安全用途 |
| 2、4.2 | 已是CLOCK2026 | 旧引用偏差消失，保持注日期；不是自动换版 |
| 3.1、3.2 | 实质一致 | 保留工作模式和绝对值 |
| 3.3、4.1 | 都要求维护持续记录 | 旧维护例外偏差消失 |
| 4.3 | 都强制维护事件 | 主体事件格式趋同；D2事件枚举另连GAP |
| 5 | D1=0.30℃/30±2℃；源=0.40℃/20±2℃ | 两项偏差保留，不把更严数值当环境覆盖 |
| 6 | 500 ms与0.500 s | 精确等价仍保留 |
| 7 | D1仅24 h，无GAP；有manifest | D2改48 h，加GAP，保留manifest；manifest仍为附加偏差 |
| 8 | D1测试24 h，无GAP注入 | D2改48 h及GAP方法；温度环境差异仍需独立验证 |
| 9 | D1标识 | D2更新profile和说明书版次，源标识要求仍保留 |

## 4.4 D1转D2的全部受影响替换文字

以下文字可直接替换；未列出的D1条款保持原文。完整清洁稿见同包D2正文；附件A不变。

- 文件身份行替换为：“文件版本：QY-ADOPT-D2，内部合成技术候选。源比较基线：SYN-ORBIT-LOG:2026。无正式国家标准编号、采标标记或生效日期。”
- 前言替换为：“本稿吸收源2026版的48 h保留和GAP记录，保留本地0.30 ℃、（30±2）℃及manifest技术提议；适用性待验证，不声称已获任何组织批准。”
- 第1章替换为：“本文件规定农业仓储非安全温度记录器的快照、维护及间断事件、示值性能、启动响应、断电保留、导出和验证。不适用于医疗、食品安全判定或安全控制。”
- 4.3替换为：“每次进入及退出维护模式应记录事件，发生顺序保存于独立events.csv。行字段为device_id,timestamp,event；前两字段分别符合4.1及附录A。event可为ENTER_MAINT、EXIT_MAINT，或符合7.4的GAP。文件为UTF-8、无表头、每行以LF结束；事件按发生顺序保存。”
- 7.1替换为：“断电后全部快照和事件应保留至少48 h，包括维护事件和GAP事件。”
- 7.3替换为：“导出目录还应有UTF-8编码的manifest.txt，内容恰为profile=QY-D2和clock=SYN-CLOCK:2026两行，按此顺序，每行以LF结束。”
- 新增7.4：“对供电运行期间每次超过60 s的采样间断，应在恢复后第一条快照的时戳记录恰一条GAP事件。GAP不豁免4.1的60 s要求，间断仍应记录为不满足。断电期间无采样义务，不能仅因断电间隔强制生成本条GAP；有供电运行中的间断时按该实际间断判断。”
- 8.3替换为：“对上限L，a+U≤L为该点数值满足；`max(0,a−U)>L`为数值不满足；其余为不确定。温度L=0.30 ℃，三点分别评价。若各读数U不同，核全部读数区间，不只取最大中心值。此为给定合成判据，非通用真实规则。”这里补明各读数U不同的处理，属于验证说明完善，随技术审核核对，不伪装源版新要求。
- 8.5替换为：“保存快照和维护／GAP事件基线，断电48 h后恢复，逐行核对导出记录的数量、数据和各自顺序；核7.3两行、编码和LF行尾。另在有供电状态下注入超过60 s的采样中断，检查恢复第一快照时戳的一条GAP，并同时记录4.1不满足。故障注入用于证明检测行为，不把被强制产生的超限当正常运行合格。”
- 第9章替换为：“说明书应列实际实施文件版次及时间格式版次。仅实施本稿时列QY-ADOPT-D2及SYN-CLOCK:2026，不宣称真实标准认证。”

D2清洁稿对其他条款作无技术意义的中文压缩；使用上列替换法形成的文本应与清洁稿逐条比较，确认条件、量值和引用相同后才固定字节。当前属于预研稿内部修订建议；未发布国家标准，不将此列为已批准“修改单”。
#### END ADOPTION PACKAGE DIFFERENCES

## 5. 拟对外技术文件三：验证计划与向量

#### BEGIN ADOPTION PACKAGE VERIFICATION
# QY-VERIFY-D2：验证计划与合成向量

版本D2，对应QY-ADOPT-D1/D2；以下均为计划及纸面推导，无真实仪器、样品或执行记录。数值界限全部来自本合成题的设计意图，非真实监管阈值。

## 5.1 可执行计划

| 对象 | 条件、步骤与设备 | 判据、记录与缺件 |
| --- | --- | --- |
| 文档/范围/标识 | 文件审查D1或D2、说明书、manifest；记录文件字节哈希 | 核范围排除、实际profile及CLOCK版；无说明书时为缺件，不填已检查 |
| 快照/维护/事件 | 固定一台样机及固件配置；各120 s工作和维护；覆盖进入/退出、通信中断；前后边界留样；用可记录原始字节的采集器 | 60 s、字段、时戳、两个文件各自顺序；记录操作时间、所有原始行和电源状态。跨边界间隔亦检查；60 s通过、61 s不满足 |
| 温度 | 校准有效且可溯源的参考装置、环境监测器和可稳定三参考点的设备；（30±2）℃；5/15/25℃各稳定10 min、取5值 | 按绝对值及U区间规则逐点，温度上限0.30；保存校准证书、环境曲线、稳定记录、原数值、U预算及覆盖因子。缺校准/U或条件超界不作确定结论 |
| 响应 | 校准计时/字节抓取装置；工作模式10次START；同一明确起止点 | 500 ms区间判据，保存10次原始抓取和各自U；不将维护模式漏测写不合格，因为本条不适用 |
| 时戳/导出 | 对两个独立解析器（尚未实现）分别输入正负向量并交叉读取文件；旧新profile分开 | 格式、长度、有效日期、字段顺序、UTF-8、LF及manifest；这是互通计划，纸面语法核查不能代替两个实现执行 |
| 保留 | D1断电24 h，D2断电48 h；断电前固定所有记录和事件基线；恢复后逐条比较 | 量、值、顺序不丢；计时不确定度须保证实际断电不少于目标时长，不以23.99 h当24 h；记录电源/计时证据 |
| GAP | 仅D2：供电运行故障注入61 s采样中断，检查首恢复快照时戳；另做正常60 s及单纯断电对照 | 61 s有且仅一条GAP并记录间隔失败；60 s无本条GAP要求；断电不凭间隔生成GAP。注入导致的失败与正常运行结果分列 |

一台样机/15次温度读数/10次响应仅覆盖给定候选方法，不代表批量、跨型号、所有环境或长期稳定性。第二实验室及其他型号的复现计划需另定覆盖，不编造统计置信度。设备型号、序列号、执行者和校准证书待真实试验时填入，当前为空缺事实。

## 5.2 八组预置向量的纸面预期

| 向量 | 计算或观察 | D1/D2及源版本边界 |
| --- | --- | --- |
| V1 | a=abs(14.72−15.00)=0.28℃，U=0.04，区间`[0.24,0.32]` | 在30℃给定条件对0.30上限为不确定；不能取0.28宣布满足。源两版要求20±2℃，本向量30℃不在其方法条件，不能判源整体符合 |
| V2 | a=abs(14.20−15.00)=0.80℃，U=0.02，区间`[0.78,0.82]` | D1/D2数值不满足。若沿D0有符号差−0.80会误收，故定义修正必要；源条件仍不匹配 |
| V3 | 499±2 ms=`[497,501]`ms，上限500ms；也为`[0.497,0.501]`s | 工作模式下各版同一上限，跨限不确定；0.500s→500ms不改变结果 |
| V4 | `20261101120000Z`，15字符有效旧格式 | 源2024时戳语法满足；D1/D2及源2026语法不满足。转换须另核整数秒前提及保留原文 |
| V5 | `2026-11-01T12:00:00.000Z`，24字符有效新格式 | 新版时戳语法满足；源2024不接收。仅语法满足不是该记录器全部符合 |
| V6 | 有供电维护区间，快照间隔61 s、59 s；已给进入/退出事件 | D1/D2的61 s违反60 s；D1无GAP要求，现有事件不补救快照；D2要求恢复t=61 s有一条GAP，给定events未含GAP故该项亦不满足。源2024维护豁免采样，不据61 s判其失败；源2026与D2相同GAP要求 |
| V7 | 假设仅知全部行保留到24 h | 可支持本向量的D1最短时长比较，其他项目未定；D2/源2026的48 h证据不足，不能从“看到24 h”编造成“25 h即丢失”的失败。源2024的24 h门槛可比较，非实测 |
| V8 | 旧格式、维护无采样；20℃误差0.45℃但U未给 | 旧格式/维护行为分别可被源2024相应条款接受而被D1/D2排除，足以反驳技术一致；0.45无U不能作完整源符合判断，且20℃不能证明目标30℃。更不能认证整个原样实现 |

补充反向边界向量：新格式中2026-02-30、秒60、带+08:00、两位毫秒均应拒绝；device_id含小写或17字符拒绝；温度只有一位小数拒绝。全部为静态预期，后续应把确切字节、输入序列和电源日志绑定真实执行结果。

本计划不能作为已有验证报告附件。重验优先级为维护连续记录与事件、时戳互通、30℃及0.30指标、48 h和GAP；任何结果只对固定版本/条件生效。
#### END ADOPTION PACKAGE VERIFICATION

## 6. 拟对外技术文件四：版本过渡技术说明

#### BEGIN ADOPTION PACKAGE TRANSITION
# QY-TRANSITION-D2：版本过渡技术说明

版本D2，技术讨论候选；日期是合成内部计划，不是官方发布、实施、废止日。所有工作尚待执行与签核，不承诺按期验证完成。

| 内部计划日 | 责任角色 | 具体产物与前置条件 |
| --- | --- | --- |
| 2026-11-15 | 技术编辑、协议工程师 | 固定D1/D2及源两版对应表；验证两个CLOCK解析配置、manifest与事件枚举；取得真实项目所需材料和规则许可后再进入实际标准程序 |
| 2026-12-15 | 试验负责人 | 执行并审阅D1/D2的30℃、维护及24/48h计划，形成原始记录/U预算/未决；未达到条件不得借计划日期改成通过 |
| 2027-01-15 | 配置负责人、商务/合同责任人 | 分离旧源、D1、D2配置及导出；核每一验收实际锁定的标准版、附录和签署文件，确认变更同意；同名文件不证明同版 |
| 2027-02-01 | 项目负责人、技术负责人 | 仅对完成验证、版本确认、培训及批准的项目启用D2；不满足则重排并保留旧配置，不自动覆盖冻结验收基线 |

固件增加维护采样、48h持久化及GAP后，存储、电源恢复、日志顺序和导出工具需联动核查。温度30℃/0.30需要该条件的新证据，不能借源20℃报告代替；说明书、测试规程、样机配置、验收脚本和产品profile同时更新。不能只改manifest字符串而保持旧行为。

双版本数据维护：原2024字符串和原始采集值永久保持本任务所需溯源副本；只在确认采集时刻为整数秒时生成2026表达及转换记录，不声称毫秒测量。由2026退到2024时，非零毫秒不能悄悄截断后冒充同一时刻；须保留原始记录、核目标验收允许条件或重新取得满足该版的记录。两个配置标明各自标准/时戳版本，不能把D2输出递给要求旧格式的验证器并称自然兼容。

三类纳入方式应分别登记：冻结源版、约定时点最新版及另签本地附件；是否变更由其各自有效文件决定。源版本更新、技术讨论收件和国家标准推荐性均不能代替合同变更同意。缺已签附件时先取原件与哈希，再核候选差异。此处只给版本管理要求，不含合同逐方文本、谈判底线或法律结论。

正式国家标准过渡须依据真实发布、实施及替代文件；本稿未立项，无权宣布原标准废止。若未来成为真实已发布采标国家标准，再由有权主体按源更新规模和适用性决定修改单、修订或废止路径；本次仅内部改稿。
#### END ADOPTION PACKAGE TRANSITION

## 7. 仅内部：历史覆盖、三份合同与审批

H-01覆盖分析。 H-01是合成历史索引，不是真实报告；型号A/固件1.0、源2024、CLOCK2024、20±2℃、仅工作模式、24 h。0.28+0.02=0.30的算术不能把报告迁到30℃目标。缺原始曲线和校准证书，连历史结果的可靠性也未在本轮验证。维护连续采样及事件、CLOCK2026、manifest、48 h及GAP均未覆盖。试验负责人接新方法和样品重新计划；文档负责人保留旧记录及覆盖关系，不删除历史或把未受影响的源结构说明一并作废。

受影响审核。 D0的IDT主张不保留；D1的技术讨论意见不能自动覆盖D2新增48 h/GAP、事件枚举及profile。D1未变的范围、绝对误差概念、500 ms起止和CLOCK2026定义可作为比较基线，但没有真实签核可继承。D2全文、差异、验证、过渡及外发包必须重新绑定字节。法律/版权/组织审阅与技术审核分别待办。

| 合同 | 本题给定适用版本及缺件 | 2027-03-31验收与具体动作 |
| --- | --- | --- |
| C-A | 冻结源2024及CLOCK2024，未有双方书面变更 | 保留旧配置和旧验收规程；D2新格式不代替旧格式，旧维护豁免/24 h仍按该合同技术约定分析。商务负责人取得变更决定前不得推送D2覆盖；若希望升级，提交逐条变更与新增验证供双方决定 |
| C-B | 给定约定的验收时最新版；题设源2026自2027-01-01视为最新版，连带其注日期CLOCK2026 | 该合成条件下2027-03-31选源2026＋CLOCK2026；要求20±2℃、0.40℃、48 h/GAP等，不能把D2的30℃/0.30替代源性能证据。试验负责人额外安排源2026条件验证，商务负责人确认无另一期后到版或合同修正 |
| C-C | 约定另签QY-ADOPT-D1；已签附件原件/哈希未给 | 冻结约定保留，实际技术基线待原件核验；当前候选D1不能视同已签。合同责任人取签署附件及签章/版本依据，技术编辑逐条比较当前D1/D2。未获双方D2变更不替换，技术讨论收件不产生同意 |

上述为给定合成事实的版本分流，非真实合同效力法律意见。C-A旧版合同不让旧标准恢复官方现行地位；未来如发生法律/强制标准冲突，交法律与标准负责人另行判断，而不是套用推荐性标签解决。

内部资料隔离。 C-A/B/C-C原文、谈判底线、H-01缺口、本段审批和私有审计仅留内部。未公开研发/IP筛查资料未提供，不能断言无风险；有实际新增技术/保护目标时，技术负责人按内容交procedure/patent核公开前支持，必要性/FTO/许可仍走各自专业。合成源许可不覆盖真实ISO/IEC材料。

拟外发请求。 包标识QY-D2-TECH-DISCUSS-01，仅四个技术文件，接收者为虚构E1技术顾问席位，目的为D2差异及验证计划技术讨论；拟议受控文件门户尚无真实地址或账号。技术负责人核正文/方案、材料权利负责人核许可和实际新披露、项目负责人核固定包/E1/用途/渠道；目前均未签核。需补接收身份、实际权限和传播条件、渠道访问配置、审批有效期及签核后才可恢复真实发送判断。当前仅生成本地候选，未发送，无收件或官方回执。核稿、材料齐备、获准发送和组织批准是四件事。

四文件不含本合订示范、原题JSON、内部合同、H-01索引、真实受限标准全文或审计。实体包各文件字节哈希见下一节，哈希只固定版本，不证明许可或内容通过。

## 8. 实体技术包清单

| 文件 | 版本 | 字节 | SHA-256 |
| --- | --- | --- | --- |
| `outputs/cross-region-d7/adoption-package-r2/adoption-d2-body.md` | QY-ADOPT-D2（排版r2） | 5712 | `9b972aae05ff319cea4fa4f87112f31259e03d14021eca6af59a744d3343dc83` |
| `outputs/cross-region-d7/adoption-package-r2/adoption-differences.md` | QY-DIFF-D2（排版r2） | 8360 | `1213c8add231480873b84a0e0ec827df3e25f37b9a77705d70877e0b530be875` |
| `outputs/cross-region-d7/adoption-package-r2/adoption-verification-plan.md` | QY-VERIFY-D2（排版r2） | 4913 | `25f144f42b52e985354c5d6e52b568aed0546674af559a260db8e544d637c1cf` |
| `outputs/cross-region-d7/adoption-package-r2/adoption-transition.md` | QY-TRANSITION-D2（排版r2） | 2607 | `d4e017b403f94d28151ef4c239f609866d40e8ce50759a056026ad722dbe2cc3` |

本次只有静态构造、数值推导和开发协作审阅；没有真实实验、独立专业验收、宿主自动触发或正式发布。下列题目附录用于教学追溯，位于工作产物标记之外，不纳入拟外发包。

<!-- END D7-ADOPTION WORK PRODUCT -->

## 附录：冻结题目原JSON

<!-- BEGIN D7-ADOPTION CASE EXACT BYTES -->
```json
{
  "case_id": "D7-ADOPTION-01",
  "version": "frozen-input-candidate-1",
  "synthetic": true,
  "license": "本文所有SYN编号文本、实体、数值、合同和事实均由本项目自创，仅作合成演练，按仓库PolyForm Noncommercial 1.0.0及单独商业授权边界使用；不复制真实国际标准，不授予真实第三方标准权利。",
  "task": "为青屿记录器协作组完成国际来源标准采用技术预研：交完整可独立阅读的中文D1候选正文、逐条对应及差异理由、类别实质建议与反证、验证向量和计划、后到v2的具体替换文本及过渡/合同影响、拟对外技术讨论包。不得把初稿的符号错误原样保留；不得只给模板或用表格代替正文。使用已核官方规则研究，但不声称取得未获准GB/T或ISO全文，不宣称真实采标、试验、发布或专业签核。",
  "adaptation": {
    "jurisdiction": "CN",
    "target_organization": "国家市场监督管理总局／国家标准化管理委员会体系",
    "target_type": "拟推荐性国家标准；未立项的内部技术预研稿",
    "stage": "立项建议前的技术比较和工作稿，不是正式征求意见稿或报批稿",
    "drafting_group": "青屿记录器协作组（虚构，无真实归口委托）",
    "field": "农业仓储非安全温度记录器；不涉及医疗、冷链食品安全判定或安全控制",
    "source_qualification": "澄星跨国技术论坛及SYN-ORBIT均为虚构，不能据此满足真实ISO/IEC/ITU源资格或其他组织采用条件；IDT/MOD只可用于实质比较练习，正式采标标签不成立。"
  },
  "materials": {
    "source_v1": {
      "id": "SYN-ORBIT-LOG:2024",
      "language": "en",
      "title": "Non-safety warehouse temperature loggers — Snapshot records",
      "status": "原创虚构国际来源标准短全文，非ISO/IEC/ITU文件",
      "complete_text": "SYN-ORBIT-LOG:2024 — SYNTHETIC FULL TEXT\n1 Scope\nThis document specifies snapshot records for non-safety agricultural warehouse temperature loggers. It excludes medical use, food-safety decisions and safety control.\n2 Normative reference\nOnly SYN-CLOCK:2024, reproduced in the supplied case, applies. Later editions do not apply automatically.\n3 Terms\n3.1 Active mode: the logger is recording snapshots, including a temporary communications outage; maintenance mode is not active mode.\n3.2 Absolute indication error: the absolute value of indicated temperature minus reference temperature.\n3.3 Maintenance mode: a locally selected service state, visibly indicated, during which snapshot recording is suspended.\n4 Snapshot records\n4.1 In active mode, the logger shall record at least one snapshot every 60 s. No snapshot is required in maintenance mode. A snapshot shall contain device_id (1 to 16 uppercase ASCII letters or digits), timestamp and temperature in degrees Celsius with exactly two decimal places; negative values shall have a minus sign.\n4.2 Timestamp shall conform to SYN-CLOCK:2024. The logger shall preserve acquisition order.\n4.3 The logger should record each entry to and exit from maintenance mode.\n5 Indication performance\nAt ambient (20 ± 2) °C, absolute indication error shall be no greater than 0.50 °C at each reference temperature 5.00 °C, 15.00 °C and 25.00 °C.\n6 Start response\nIn active mode, a valid START request shall receive an ACK within 0.500 s after the final request byte arrives. ACK timing ends when its final byte leaves the logger.\n7 Retention and export\nRecords shall be retained for at least 24 h after power loss and exported in acquisition order as UTF-8 comma-separated rows, one snapshot per row, with fields device_id,timestamp,temperature and LF row endings. A header row is not permitted.\n8 Verification\nFor clause 4 inspect an active interval of 120 s and a 60 s maintenance interval; check fields, intervals and clock syntax. For clause 5 use one logger, five readings at each reference point after 10 min stabilization, in the stated ambient range, and calculate the largest absolute error. Apply the supplied case decision rule including uncertainty. For clause 6 measure 10 valid START requests in active mode and compare the largest elapsed time. For clause 7 power off for 24 h, restore power and compare exported rows with the acquired sequence. These are verification requirements, not evidence that tests occurred.\n9 Identification\nThe manual shall state the implemented document edition and clock edition.\nEND OF SYNTHETIC FULL TEXT"
    },
    "clock_v1": {
      "id": "SYN-CLOCK:2024",
      "complete_text": "SYNTHETIC FULL TEXT. A timestamp is exactly 15 ASCII characters YYYYMMDDhhmmssZ. Fields denote a valid Gregorian UTC date and time; year is 2000 to 2099, hour 00 to 23, minute and second 00 to 59. Fractions, offsets and leap-second value 60 are invalid. Example: 20261101120000Z. All other strings are invalid. END."
    },
    "clock_v2": {
      "id": "SYN-CLOCK:2026",
      "complete_text": "SYNTHETIC FULL TEXT. A timestamp is exactly 24 ASCII characters YYYY-MM-DDThh:mm:ss.sssZ. Fields denote a valid Gregorian UTC date and time; year is 2000 to 2099, hour 00 to 23, minute and second 00 to 59, and sss is exactly three decimal digits. Offsets and leap-second value 60 are invalid. Example: 2026-11-01T12:00:00.000Z. A 2024 string may be converted only when its acquisition time is known to an exact second; append .000 and delimiters, retain the original record and record the conversion, never claim newly measured millisecond precision. All other strings are invalid. END."
    },
    "target_d0": {
      "id": "QY-ADOPT-D0",
      "status": "待核内部初稿，以下是全文，前言的IDT主张未审",
      "complete_text": "QY-ADOPT-D0 农业仓储非安全温度记录器 快照记录（内部合成初稿）\n前言：本稿为SYN-ORBIT-LOG:2024的IDT中文稿。\n1 范围\n规定农业仓储非安全温度记录器的快照记录。不适用于医疗、食品安全判定和安全控制。\n2 规范性引用\nSYN-CLOCK:2026，采用其全部规则。注日期引用仅适用该版。\n3 术语\n3.1 工作模式：记录快照的状态，包括短时通信中断；维护模式不属于工作模式。\n3.2 绝对示值误差：示值减去参考温度所得差值。\n3.3 维护模式：本机选择且可见提示的服务状态，此时快照记录暂停。\n4 快照记录\n4.1 在工作和维护模式均应每60 s至少记录一条快照；快照含device_id（1至16个大写ASCII字母或数字）、时间戳、以摄氏度表示且固定两位小数的温度，负数带负号。\n4.2 时间戳符合SYN-CLOCK:2026；保留采集顺序。\n4.3 每次进入及退出维护模式应记录事件，字段为device_id,timestamp,event；event仅为ENTER_MAINT或EXIT_MAINT，按事件发生顺序保留在独立events.csv中，无表头、UTF-8、LF行尾。\n5 示值性能\n环境为（30±2）℃，参考温度5.00℃、15.00℃、25.00℃每点绝对示值误差应不大于0.30℃。\n6 启动响应\n工作模式下，有效START请求末字节到达后500 ms内应完成ACK末字节发送。\n7 保留和导出\n断电后记录至少保留24 h。快照按采集顺序导出为UTF-8 CSV，字段device_id,timestamp,temperature，无表头、LF行尾。导出目录还应有manifest.txt，含固定行profile=QY-D1和clock=SYN-CLOCK:2026，按此顺序、UTF-8、LF行尾。\n8 验证\n沿用源标准第8章。\n9 标识\n说明书应注明实施的文件版次及时间格式版次。\n全文结束。"
    },
    "confirmed_design_intent": [
      "D1保留D0的0.30℃上限、30±2℃环境及全部三参考点；均为虚构工作组技术提议，未试验且非真实监管阈值。",
      "D1要求维护模式仍记录快照；将其定义改为可见服务状态且记录继续，不得保留D0定义冲突；工作模式可保留为非维护状态，区间要求分别明确。",
      "D1绝对示值误差仍是绝对值，D0漏绝对值是编写缺陷，不能解释为刻意放宽负误差。",
      "D1采用SYN-CLOCK:2026；保留来源版次和原记录，不能把新版自动代入冻结合同。",
      "D1强制维护事件并增加manifest；完整正文须明确事件与快照保留/顺序各自规则，manifest文件结尾有LF。",
      "D1的500 ms与源0.500 s同一限值，起止点、模式、取最大值均不得暗改。",
      "D1第8章须独立完整写出方法；不能留'沿用源标准'而令目标正文依赖未附原文。"
    ],
    "source_v2_late_arrival": {
      "id": "SYN-ORBIT-LOG:2026",
      "received": "2026-11-03（合成情节，非本次真实执行日期）",
      "status": "完整自创后到源版本；无现实发布或适用效力",
      "complete_text": "SYN-ORBIT-LOG:2026 — SYNTHETIC FULL TEXT\n1 Scope\nThis document specifies snapshot records for non-safety agricultural warehouse temperature loggers. It excludes medical use, food-safety decisions and safety control.\n2 Normative reference\nOnly SYN-CLOCK:2026, reproduced in the supplied case, applies. Later editions do not apply automatically.\n3 Terms\n3.1 Active mode: the logger is recording snapshots, including a temporary communications outage; maintenance mode is not active mode.\n3.2 Absolute indication error: the absolute value of indicated temperature minus reference temperature.\n3.3 Maintenance mode: a locally selected and visibly indicated service state in which snapshot recording continues.\n4 Snapshot records\n4.1 In active and maintenance modes, the logger shall record at least one snapshot every 60 s. A snapshot shall contain device_id (1 to 16 uppercase ASCII letters or digits), timestamp and temperature in degrees Celsius with exactly two decimal places; negative values shall have a minus sign.\n4.2 Timestamp shall conform to SYN-CLOCK:2026. The logger shall preserve acquisition order.\n4.3 The logger shall record each entry to and exit from maintenance mode in an independent events.csv file as device_id,timestamp,event; event shall be ENTER_MAINT or EXIT_MAINT. The file shall be UTF-8 with LF row endings, no header and event order preserved.\n5 Indication performance\nAt ambient (20 ± 2) °C, absolute indication error shall be no greater than 0.40 °C at each reference temperature 5.00 °C, 15.00 °C and 25.00 °C.\n6 Start response\nIn active mode, a valid START request shall receive an ACK within 0.500 s after the final request byte arrives. ACK timing ends when its final byte leaves the logger.\n7 Retention and export\nSnapshots and events shall be retained for at least 48 h after power loss. Snapshots shall be exported in acquisition order as UTF-8 comma-separated rows, fields device_id,timestamp,temperature, no header and LF row endings. For each sampling gap exceeding 60 s during powered operation, events.csv shall additionally contain one GAP event at the first resumed snapshot timestamp. GAP does not waive the interval requirement. No sampling obligation is created while power is off.\n8 Verification\nFor clause 4 inspect 120 s of active operation and 120 s of maintenance; check fields, intervals, transitions and clock syntax. For clause 5 use one logger, five readings at each reference point after 10 min stabilization, in the stated ambient range; calculate the largest absolute error and apply the supplied decision rule including uncertainty. For clause 6 measure 10 valid START requests in active mode and compare the largest elapsed time. For clause 7 power off for 48 h, restore power and compare all snapshot and event rows; separately inject a powered sampling interruption longer than 60 s and check GAP while recording the interval nonconformity. These are verification requirements, not evidence that tests occurred.\n9 Identification\nThe manual shall state the implemented document edition and clock edition.\nEND OF SYNTHETIC FULL TEXT"
    },
    "d2_proposal": "后到v2后，技术组提议D2保留D1的0.30℃、30±2℃和manifest，同时吸收48 h保留及GAP规则；profile行改QY-D2。请写出全部受影响条款替换正文及仍存偏差，不自动重标IDT，也不将预研稿更新称为正式国家标准修改单。",
    "decision_rule": "仅为合成案例预置判定：最大绝对示值误差a与该点扩展不确定度U均为℃。a+U≤限值为计划数值可满足；a−U>限值为计划数值不满足；其余为不确定。负下界按0处理。时间区间也用相同上限区间法，单位先统一。不得以中心值替代区间。数据仅为预定向量，均非实测。",
    "vectors_to_evaluate": [
      {"id":"V1","topic":"indication","indicated":14.72,"reference":15.00,"U":0.04,"ambient":30,"mode":"active"},
      {"id":"V2","topic":"indication","indicated":14.20,"reference":15.00,"U":0.02,"ambient":30,"mode":"active"},
      {"id":"V3","topic":"timing","elapsed_ms":499,"U_ms":2,"mode":"active"},
      {"id":"V4","topic":"clock","timestamp":"20261101120000Z"},
      {"id":"V5","topic":"clock","timestamp":"2026-11-01T12:00:00.000Z"},
      {"id":"V6","topic":"maintenance","powered":true,"snapshot_timestamps_seconds":[0,61,120],"events":["ENTER_MAINT@0","EXIT_MAINT@120"]},
      {"id":"V7","topic":"retention","all_rows_retained_hours":24,"evidence":"synthetic hypothetical behavior only"},
      {"id":"V8","topic":"negative_case","description":"把源v1原样实现：20℃环境误差0.45℃，维护不采样，旧时戳格式；不可据源符合性推定D1符合。"}
    ],
    "historical_record": "H-01仅为虚构历史报告索引：型号A/固件1.0，源2024、CLOCK2024、20±2℃、只工作模式、24h保留，最大绝对误差0.28℃、U=0.02℃；无原始曲线、校准证书、维护/30℃/CLOCK2026/48h证据。允许仅作为合成覆盖演练，不得声称真实报告或本轮实测。",
    "contracts": [
      {"id":"C-A","parties":"虚构买方甲/供应方甲","text":"2026-10-15签署；2027-03-31验收。验收基线固定SYN-ORBIT-LOG:2024及SYN-CLOCK:2024全文。任何技术版次替换须双方书面同意；未同意继续该基线。"},
      {"id":"C-B","parties":"虚构买方乙/供应方乙","text":"2026-10-20签署；2027-03-31验收。SYN-ORBIT-LOG版本以验收当日来源方已发布的最新完整版本为准，且只连带该版本明确注日期引用的CLOCK版本。双方本演练约定源2026于2027-01-01视为可用最新版；无其他版本。"},
      {"id":"C-C","parties":"虚构买方丙/供应方丙","text":"2026-10-25签署；2027-03-31验收。合同约定基线为双方另签的QY-ADOPT-D1完整正文，但本题未提供该已签附件原件或哈希。D2未签署不替换已签D1。11月技术讨论或收到文件不构成同意变更。本次起草的D1只是当前候选，不能默认等于已签附件；须取得签署版并逐项比较后确定合同技术基线。"}
    ],
    "proposed_transition": "内部计划候选：2026-11-15完成差异与格式核查，2026-12-15完成D1/D2样机验证，2027-01-15完成双格式导出和合同变更核查，2027-02-01拟启用D2项目配置。均非官方发布/实施/废止日期，日期不足时须重排，未获合同变更不得覆盖冻结基线。",
    "publication_and_permissions": {
      "current_authorized_action":"本地合成技术研究、起草、静态检查、协作审阅；无真实外发或正式提交。",
      "proposed_recipient":"青屿协作组外部技术顾问席位E1（虚构）",
      "purpose":"D2技术差异与验证计划讨论，非征求意见/报批/许可谈判",
      "channel":"拟议组织受控文件门户，尚未建立真实地址或账号",
      "approvers":"拟议技术负责人核正文与验证计划、材料权利负责人核合成/第三方边界、项目负责人批准固定文件包与接收者；均未签核",
      "internal_only":"合同逐方文本及谈判底线、H-01覆盖缺口、未公开研发/IP筛查、执行审计。IP资料未提供，不能断言无风险。",
      "requested_package":"单独D2正文候选、逐条差异说明、验证计划和版本过渡技术说明；不含题目JSON、整本教学示范、受限真实标准全文、内部合同和审计。"
    }
  },
  "evidence_resource": "references/standards/international-adoption-evidence-20261101.md",
  "delivery_requirements": [
    "先给D1独立完整正文，包括全部规范性依赖的自创CLOCK2026规则，不把读者送回题目找方法。",
    "保留全部源条款映射、不同性质修改和明确理由，不用中文化掩盖阈值、例外、引用和术语变化。",
    "D2须有可直接替换的全文条款，并形成独立拟外发正文文件。",
    "给每份旧结论覆盖范围、需要重验/重审的条款及接收责任，合同C-A/B/C-C逐个分流。",
    "输出限定为开发候选；专业、组织、试验和外发状态分别记录。"
  ]
}
```
<!-- END D7-ADOPTION CASE EXACT BYTES -->
