# 港湾记录整理器 v1.3 使用说明

本文件对应本项目原创合成软件v1.3，用于内部材料链验证。v1.3新增可选id排序，v1.2已提供GUI；旧版源码、文档和截图保持原样，不能将本次观察倒填到旧版本。

## 功能及运行条件

软件将UTF-8 JSON记录数组转为固定列id,label,value的CSV。id、label须为非空字符串，value须为非负整数且布尔值不算整数；最多1000条记录。整批先验证，重复id拒绝；严格模式还拒绝额外字段，非严格模式忽略额外字段。空数组输出表头，CSV使用LF及CSV转义规则。

默认保留输入顺序。勾选“按id排序”后，按原id字符串的Unicode字符序升序，不修剪空格、不折叠大小写，不作数值、自然语言或地区排序。例如“10”在“2”之前，“A”在“a”之前。排序只改变行顺序，不改记录值或固定列。

## 启动GUI

在完整包根运行：python -X utf8 skills/dyz-software/resources/harbor-demo/v1.3/gui.py --synthetic。要求Python3.11标准库和浏览器；本次实测Windows与ego-lite。服务只监听127.0.0.1，无认证、多人服务或持久存储；终端输出实际动态地址，停止服务按Ctrl+C。

打开实际本机地址，标题显示“港湾记录整理器v1.3”，状态“准备就绪”。三个当前实测截图gui-default.png、gui-sorted.png、gui-duplicate-id.png随材料提供，均为1200×900的真实页面截图；不沿用旧版或重绘界面。

## 转换记录

输入两条不同id的记录B2、A1，label分别为harbor、bridge，value分别为12、8。保留“拒绝记录中的额外字段”，点击“转换为CSV”；默认结果顺序B2、A1，对应gui-default.png。

勾选“按id排序（Unicode字符序）”后旧结果清空，重新点击转换，结果顺序A1、B2，对应gui-sorted.png。结果仅显示在当前页面，不自动保存文件；需要文件时使用CLI。

## 错误与恢复

两条记录id均为B2时，页面显示“转换失败：duplicate_id”，结果为空，对应gui-duplicate-id.png。修正第二条为A1后再次转换可恢复。改变输入或任一选项立即清空旧结果；输入版本改变后，旧请求晚到的结果不会再展示。

JSON错误为invalid_json；缺字段、额外字段、非法id/label/value有各自固定错误类别。请求体上限65536字节；网络失败提示检查本机服务，不自动重试或声称已保存。

## CLI及API

CLI：python -X utf8 skills/dyz-software/resources/harbor-demo/v1.3/cli.py input.json new-output.csv --strict --sort-by-id。去掉--sort-by-id保留输入顺序。--version报告1.3。

CLI先验证整批，再独占新建输出。退出0成功、2输入非法、3输出已存在、4输入/输出I/O错误。已有文件不覆盖；写入开始后的I/O故障可能留下部分新文件，不保证原子写入。

HTTP为POST /convert，Content-Type为application/json。查询strict=1启用严格模式，sort_by_id=1启用排序；各自缺省或0为关闭，键顺序不影响结果。未知键、重复键、空值、非0/1值或不合法查询格式返回400 invalid_query；非法记录一般422，JSON解码错误400，超限413。请求体上限65536字节。本机GUI还核Host和已提供的Origin；不是认证远程API。

## 材料一致性及未填写事实

当前五份源码共266物理行，含注释与空白。源文件hash、原行和导出行在facts.json及source-lines.json逐项绑定；source.txt只是带文件/原行前缀的内部母本。源码、截图或事实变化后需重建相关材料并另核当前版本；旧1.2审阅只属于旧版。

真实开发/权利主体、实际环境及硬件、完成日期、发表、申请人、证件和登记路线均未提供。scope-and-rights.md列主张与排除；本稿及字段候选不能替代权属、交存资格或专业签核。软件新版本不自动决定应重新登记，也未执行登记、提交、签署或外发。

## 内部核验说明

本次软件真实版本变化为1.2到1.3；公开指南与未知项分开，当前截图、事实和源码需要各自当前字节。各项工程观察另记施工台账，不能把导出成功写成已专业审阅。
