# EPO第二来源：访问、数据许可与实际范围

核对日2026-11-03。本页记录已选网关主题的第二来源，不是专利规则、官方登记簿或全库查新。原Google公开网页窗口、美国原件及原合成设计分别保留；新增来源不改变原案事实或专业状态。

## 来源选择和执行条件

| 服务 | 本轮实际依据与处理 |
| --- | --- |
| [Espacenet](https://www.epo.org/en/searching-for-patents/technical/espacenet) | 官方条件不支持机器人检索，本轮未执行其搜索。不能把免费访问理解为自动检索许可。 |
| [OPS](https://www.epo.org/en/searching-for-patents/data/web-services/ops) | 官方起步流程要求注册凭据及OAuth。本轮未注册、未读凭据、未调用认证接口，不借其免费额度推定本项目已有账户或费用授权。 |
| Justia | 首页和条款可读；robots经网页工具取得失败，条款含商业服务复用限制。本轮没有据此建立可复用检索后端或执行站内主题查询。 |
| [Linked open EP data](https://www.epo.org/en/searching-for-patents/data/linked-open-data) | 官方允许偶发、小规模API／SPARQL查询，数据许可为CC BY 4.0。按该范围执行两次LIMIT10摘要索引查询及两次已知URI读取，无账户、cookie或付费调用。不是生产数据库后端或批量镜像。 |

2019版[用户指南](https://link.epo.org/web/linked_open_ep_data_user_guide_en.pdf)和2020版[示例查询](https://link.epo.org/web/SampleQueries_v1.2.pdf)只作背景；指南首次读到，后续两次网页工具取回超时，未无限重试。当前入口经固定ego-lite真实无头配置读取，界面／数据转换版本均显示2.0.0；当前About及同源查询iframe实际给出`/linked-data/query`与命名空间。不能以旧手册取代这份当前观察。

## 传输、标识与材料层次

查询使用HTTPS，结果中的RDF标识仍为`http://data.epo.org/linked-data/...`；命名空间和资源身份不因传输改HTTPS而改写。当前查询表单在同源iframe内，顶层没有输入控件不表示页面空白；已实际看截图及iframe文字。本次没有登录验收或任意宿主隔离结论。

两查询只读英语摘要索引，返回4和10条版本记录；没有分页、排序或全库命中总量核验。具体输入、来源哈希、取得时间和所选字段见[研究记录](../../skills/dyz-patent/resources/cn-epo-search-record.json)。原始HTTP数据在开发侧保全，不是运行包依赖。服务端Date与本地UTC取回时间都不是公开日、优先权日或数据集最新装载时点。

两次已知URI读取限EP01119968申请和EP1197856A2公开数据。申请JSON给出一个简单同族URI及代表申请，不是全部同族清单；公开JSON另给EP00120362优先引用，未取得其日期或原文。原返回没有本轮可据以认定当前权利有效性的官方登记簿记录。未请求、未取得、未知和事实不存在分开。

## 数据归属和复制边界

[研究记录](../../skills/dyz-patent/resources/cn-epo-search-record.json)中的EPO原字段和英文摘要来自European Patent Office Linked open EP data，保留[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)；来源、取得窗口、选择及日期转换说明随记录提供。它们不改为项目仅非商用许可。查询组织和作者比较属于本项目原创，根许可另适用。

本轮没有复制EPO界面／客户端实现、整页HTML、官方完整专利全文或PDF进入分发包；记录中全文表示链接未被读取。CC BY的数据许可不在这里外推到全部网页、界面或完整文献。EPO不因此认可本项目或其分析。更多边界见[第三方说明](../../THIRD-PARTY-NOTICES.md)。

## 可以继续和仍需补齐的工作

这份证据补上第二个实际可访问索引来源及版本／日期有限交叉核对。后续仍须取得所选具体全文、核优先原件及范围、核全部相关同族／官方状态和原案逐要素比较；没有相应原文，不将摘要当完整权项或原始支持。前一个来源的排名／召回、其他法域和专业通过均不迁用。原业务CLI仍只支持合成资料，本次研究不是联网适配器或真实案件出口。
