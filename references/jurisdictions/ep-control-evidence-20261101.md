# EP计算机实现控制技术：有限规则研究

核验日：2026-11-01。研究状态：`not_professionally_reviewed`。适配：EP发明、计算机实现的液冷泵反馈控制、申请后内部修改候选；不是EPO正式意见、真实检索或全领域规则包。关联既有ANALYSIS-02—05、DRAFT-02/03、REVIEW-01/02、WP-05/10。原规则JSON与工具选择器未改。

本页仅用官方公开页面确认下表所列命题。2026版指南的适用依据是EPO公告，不由URL年份或搜索引擎时间推断；EPC网页路径的`2020`是该在线编排路径，不表示法律在2020年失效。没有穷尽核查2026年全部判例、程序决定、优先权或任何真实案件。指南是审查实践指引，与EPC条文和具体决定的职责分别记录。

## 来源、定位与本次用途

下列页面均于2026-11-01经web工具实际读取；英文材料只作中文原创研究摘要，不复刻长篇原文。每一行的适用限度同时适用其研究命题。

| 研究ID | 官方来源、版本/日期与位置 | 必要命题及适用限度 |
| --- | --- | --- |
| EPCTL-01 | [OJ EPO 2026 A4](https://www.epo.org/en/legal/official-journal/2026/01/a4)，2025-12-02通知，2026-01-30线上公布，首段 | 2026年4月版指南自2026-04-01生效、取代2025年4月版；本研究采用正式2026页面，未用2月预览或草案代替。 |
| EPCTL-02 | [EPC Art.52](https://www.epo.org/en/legal/epc/2020/a52.html)，在线现行编排，(1)—(3) | 发明仍需新颖、创造性和工业应用；程序、数学方法及商业方法的列举排除针对其本身。不能把技术性门槛当成授权结论。 |
| EPCTL-03 | [Guidelines 2026 G-II 3.6](https://www.epo.org/en/legal/guidelines-epc/2026/g_ii_3_6.html)，Programs for computers，前段及Computer-implemented inventions | 程序本身须产生超出正常软硬件交互的进一步技术效果，该门槛不以现有技术比较为前提；涉及技术手段的方法/装置与程序本身须区分。后续新颖性和创造性仍分别评价。 |
| EPCTL-04 | [Guidelines 2026 G-II 3.3](https://www.epo.org/en/legal/guidelines-epc/2026/g_ii_3_3.html)，Technical applications及Technical implementations | 数学步骤须与具体技术目的具有功能联系；仅给数据贴技术标签不足。本案可分析压力测量、状态计算、变频命令和液路之间的因果关系，不能把“控制系统”四字当作贡献。 |
| EPCTL-05 | [Guidelines 2026 G-VII 5.4](https://www.epo.org/en/legal/guidelines-epc/2026/g_vii_5_4.html)，COMVIK说明及(i)—(iii)(c) | 全部特征先在整体语境中检查；仅不贡献技术性的区别不能支撑创造性。由技术贡献选起点、识别区别及效果，再形成客观技术问题；非技术目标可成为给定约束，不能预塞具体技术解法。孤立非技术特征若在组合中产生技术作用，也不能机械删除。 |
| EPCTL-06 | [EPC Art.54](https://www.epo.org/en/legal/epc/2020/a54.html)，(1)—(3)；[Art.56](https://www.epo.org/en/legal/epc/2020/a56.html)，正文 | 公开日/有效关键日与技术对应是不同问题；Art.54(3)材料不用于Art.56判断。本案D1/D2仅为合成集合，公开日期是题设假定，未形成真实可用文献证明。 |
| EPCTL-07 | [Guidelines 2026 G-VII 5.2](https://www.epo.org/en/legal/guidelines-epc/2026/g_vii_5_2.html)，客观技术问题；[G-VII 5.3](https://www.epo.org/en/legal/guidelines-epc/2026/g_vii_5_3.html)，Could-would approach | 问题不应带入解法；组合分析要说明为何技术人员会作该改动及预期优点，不能只说能够拼接。无据的“行业不同所以不结合”与事后寻找零件同样不足。 |
| EPCTL-08 | [EPC Art.123](https://www.epo.org/en/legal/epc/2020/a123.html)，(2)；[Guidelines 2026 H-IV 2.1](https://www.epo.org/en/legal/guidelines-epc/2026/h_iv_2_1.html)，Basic principle | 增加、改变或删除后的整体信息不得超出原始申请可直接且无歧义导出的内容，含技术人员可隐含理解之处。资料名称叫“交底汇编”不证明它属于实际原始申请。 |
| EPCTL-09 | [Guidelines 2026 H-V 3.2.1](https://www.epo.org/en/legal/guidelines-epc/2026/h_v_3_2_1.html)，首段及两条件后总规则 | 原始申请不是随意抽取不同实施方式特征的储库；中间概括需检查抽出特征与被省略内容的结构/功能关系及整体公开，最后仍回到Art.123(2)。仅缩小字面范围不足以证明组合支持。 |
| EPCTL-10 | [EPC Art.83](https://www.epo.org/en/legal/epc/2020/a83.html)，正文；[Art.84](https://www.epo.org/en/legal/epc/2020/a84.html)，正文 | 可实施公开、权项清楚/简洁及说明书支持各有要求；本研究仅识别缺参数/术语/组合的风险，不以写得详细代替法律审阅，也不将Art.84支持与Art.123(2)修改依据混为一项。 |
| EPCTL-11 | [G 2/21，OJ EPO 2023 A85](https://www.epo.org/en/legal/official-journal/2023/09/a85)，2023-03-23决定、2023-09-29公布，Headnote I/II及Order 1/2；[Guidelines 2026 G-VII 11](https://www.epo.org/en/legal/guidelines-epc/2026/g_vii_11.html)，前3段 | 后提交的效果证据不能仅因时间晚就被忽略；效果仍须落在原技术教导中并由同一原始发明体现。是否可用作效果证据与是否可把新结构写回申请是两条问题。本案后到手算不等于实验，更不能补入原申请没有的预测模型。 |
| EPCTL-12 | [EPO网站使用条件](https://www.epo.org/en/terms-of-use/terms-and-conditions-use-website-european-patent-office)，2026-11-01读取版本，§6.1—6.7 | 网站区分官方出版物、EPO自身信息与第三方内容，并对再使用、改编、实质性数据库提取等规定边界。读取公开页面不等于任意复制第三方材料或提供数据库服务；此处仅保留必要事实、定位和链接。 |

## 规则核验的实际边界

- 已读：表中条文、2026指南对应段落、A4适用通知、G2/21要旨和网站§6条款；只依据这些位置作有限工作分析。
- 未读/未完成：T641/00、T1173/97、G1/19、G2/10完整事实与全部理由；它们在指南中出现，不据此声称已经逐案研究。未作2026全部变更穷尽排查、各缔约国法院/UPC分析、权利要求形式/翻译/审查程序时限、真实申请或专利数据库搜索。
- 页面提取问题：H-V 2.2的web抽取出现新旧修订措辞粘连，未把该混合文本当最终规则；后到效果边界改用G2/21官方决定及清楚的2026 G-VII 11核对。未下载并逐页校验整个指南PDF。
- 资料获取失败与零命中不混用：本次所采用来源可读；网站`legal-notice`只给机构信息，未用它证明复制许可，另查实际网站使用条件。

## 许可与再使用

来源署名：European Patent Office / European Patent Organisation；G2/21为其扩大申诉委员会官方决定。本页中文内容是项目研究摘要和适用分析，不是EPO批准译文。仅本页原创分析适用项目许可；EPC、官方出版物、网站文本及第三方权利不被本项目重新许可。未复制EPO标识、照片、图表、数据库或完整指南。

如本页某项摘要被视为EPO自身信息的改编，该部分明确区别于原文，并按上述网站§6条件允许第三方复制和分发该改编；项目非商业条款不额外限制原材料及其网站条件所保留的权利。未来扩大复制范围或制作正式译文时须另核相应权利，不从本页推导已获授权。

## 对本候选链的约束

先读实际控制材料和逐版本的原始申请证明，再决定技术贡献与支持。A/B两路线必须分别作整体技术链、单篇对应、COMVIK、范围取舍、组合支持和最强反证。后到事实改变原始支持时保留旧候选、写完整替换稿并使受影响评价待重审。该工作仍是合成开发示范，不能提升独立专业验收或其他地区组合的状态。
