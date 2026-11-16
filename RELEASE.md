# 首个公开试用版

当前代码版本为 **0.1.0a1**，拟发布标签 **v0.1.0-alpha.1**，状态为未发布候选。它提供六入口的方法型工作流和有限可追溯本地工具；83项能力等级仍为synthetic_helper_only。本页不是正式发布、专业认证或外发授权。

## 许可与参与

原创内容采用[PolyForm Noncommercial 1.0.0](LICENSE)＋[单独商业授权](COMMERCIAL-LICENSE.md)，属于Source Available，不使用OSI开源标记。用户原有材料与生成结果、第三方内容分别判断；EPO有限数据继续适用其CC BY 4.0说明。

欢迎外部Issues和PR。按[贡献指南](CONTRIBUTING.md)提交；原创贡献须由有权贡献者明确同意[贡献许可](CONTRIBUTOR-LICENSE.md)，保留版权并允许项目商业再许可。真实接收主体明确前可以讨论审阅，不能先合并需授予权利的外部补丁。敏感报告走[安全流程](SECURITY.md)。

## 发布前必须由维护者填写

唯一机器可读记录为根目录[release.json](release.json)。当前下列值为null，不能由工具虚构：

| 字段 | 需要的事实 |
| --- | --- |
| license_holder | 有权对项目原创内容及接收贡献作出授权的真实自然人或组织 |
| repository_url | 实际拟公开仓库的HTTPS地址，不默认创建远端 |
| commercial_contact | 实际可用的商业授权联系渠道 |
| security_contact | 实际可用且已确认私密性的安全报告渠道；公开Issue不满足 |

这四项未齐时，候选可以构建、检查和审阅，公开前元数据检查必须拒绝。不把非空字符串视为身份、权属或渠道真实性认证；维护者仍须核实实际事实及贡献者授权。

## 支持环境与使用范围

已验证基线为Windows和Python 3.11标准库。先确认 `python --version`；默认是其他版本时改用已安装3.11解释器的完整路径。本版不宣称其他Python版本、操作系统、任意Agent宿主或办公软件已经通过。

根目录的`README.md`提供文字加载、合成演练及Word生成三个快速入口。六Skill需要保持完整共享树，不能仅复制某个SKILL.md；明确文件加载、本地工具使用、宿主自动发现与模型实际调用分别核验。PDF可选，需要获准的本地工具，不自动下载或安装。

专利final只接受有限句法。原申请从属继承、复杂数量／逻辑、公式、表格和图等超出子集时可被阻断，不能据此认定没有法律支持。OA答复论证与技术替换稿当前共用原申请门禁，不能保证通常完整OA通过。保留原文和问题报告，交明确的内部工作稿及分类专业审阅；不改原文、删论证或伪造来源换通过。

软件真实权利链、运行及截图、标准命题／组织要求、正式格式、专业签核、期限和真实行动均需相应证据。机器checked、零issues或成件成功不表示专业通过。该版本不执行真实提交、自动外发、签署或付款，也不提供完整宿主或OS隔离。

## 源码范围与完整运行包

源码仓库保留六Skill及其必要资源、原创工具、获准规则与来源索引、合成夹具、可运行测试、CI、使用／许可说明，以及`.gitignore`白名单内的稳定规格和来源归属文档。根目录与`docs/`新增内容默认不进入Git，须明确加入白名单。成套运行示例及其Word／PDF／图像属于必要资源，与本地临时生成产物分别管理。

施工台账、迭代／修复计划、阶段评审、本地AGENTS.md、整个`竞品对比/`、`.references/`、受限标准全文、private、outputs、临时目录和evals/workflows历史模型归档保持本地。公开文档中的历史本地路径只提供来源线索，不是运行依赖，也不保证公开可下载；不得为修链接公开这些归档。可重复的技术检查使用公开测试和合成夹具，PDF／视觉及模型历史另按实际条件声明。

忽略规则不清除原件，也不证明秘密已清除；已被跟踪或强制暂存的内容仍可进入提交，推送前须核查Git实际清单。运行包之外的测试、CI和维护文件按源码范围管理，不直接使用运行包白名单代替整个Git仓库。

完整运行包只复制tools/bundle.py的当前固定白名单。构建和校验不提交Git、不安装宿主、不建立远端、不公开发布。以下在可信完整根目录执行；包目标不存在且父目录存在：

```powershell
python -B -X utf8 -m tools.bundle --destination D:/dyz-review-package
$dyzManifestSha = (Get-FileHash -LiteralPath D:/dyz-review-package/bundle-manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
python -B -X utf8 -m tools.bundle --verify D:/dyz-review-package --manifest-sha256 $dyzManifestSha
```

第一次可信构建后，把清单SHA-256、代码来源和检查结果保存于包外；其他人下载时使用发布者提供并独立核实的依据，不能从待核包重新算“预期”证明其可信。清单内部一致不认证来源、许可或专业质量。修改包内源、说明、许可或元数据后须在新目录重建，不复用旧pin。

## 开发仓库的发布检查

本节命令只适用于包含evals和Git元数据的完整源码仓库，运行包不附带开发检查器或CI。先按贡献指南运行受影响测试，必要时使用原生unittest全仓入口；不要在无main保护的临时Python脚本顶层运行带spawn的全仓测试。

```powershell
python -B -X utf8 evals/release_check.py
python -B -X utf8 evals/release_check.py --publication
```

默认检查核元数据结构、版本、资源、Git范围、Python语法及完整包布局，并列出尚缺的发布事实；它不执行模型、联网、Office或全套测试。`--publication`要求四项元数据齐备，缺项退出2。两种成功都不代表已经公开、获得授权或验证全部专业能力。

随仓CI定义只在Windows／Python 3.11执行检查及本地测试，权限只读，不带发布凭证，不自动合并或发版。可选PDF工具未安装的skip需保留；CI不证明真实PDF／视觉或跨平台通过。实际托管CI尚未执行，须在具体仓库配置和贡献权限条件下另核。

本版最终本地结果与包外pin由维护者本地台账记录，该台账不随源码分发；本页不嵌入自身包清单hash，避免循环变化。公开发布、创建远端、Git暂存提交和打标签均为独立动作，须在具体授权下执行。
