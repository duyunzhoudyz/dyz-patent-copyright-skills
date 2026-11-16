# 美国软件版权登记：港湾程序三阶段适配示范

先读[美国登记方法](us-registration-method.md)及[US官方来源研究](../../../references/jurisdictions/us-software-evidence-20261101.md)，返回[软件技能](../SKILL.md)。对应SW-01/02/03/05/07/08、WP-06、WP-10。本资源自含完整案卷和完整答卷，六源码按包内相对路径可读，不依赖开发评测目录。

源码：[v1.0 core](harbor-demo/v1.0/core.py)、[v1.0 CLI](harbor-demo/v1.0/cli.py)、[v1.0 API](harbor-demo/v1.0/api.py)、[v1.1 core](harbor-demo/v1.1/core.py)、[v1.1 CLI](harbor-demo/v1.1/cli.py)、[v1.1 API](harbor-demo/v1.1/api.py)。实际源码和本项目仍按PolyForm Noncommercial 1.0.0及单独商业授权；下述虚构公司、人物、签署、出版与AI过程只属于US演练，不改变真实权属或许可，也不继承旧CN案事实。

版本D5-SW-draft1，作者开发作答。案卷/8项复合检查对作者可见，根代理预检后开始写作；不是盲测、独立专业签核或版权局决定。作者实际复读六源码并核字节/哈希/物理原行，没有运行程序、登录eCO、生成正式交存分页或执行对外动作。全文正文中的R01—R13对应US来源研究US-SW-R01—R13。

下面标记范围是完整内部交付示范，含阶段正文、源码、内部审计和行动表；不能整体当外发包。V1潜在秘密阶段只允许选V1指定内容，不能夹带V2的全码。原始合成案卷保全在末尾标记之外。

<!-- BEGIN D5-SW WORK PRODUCT -->
# D5-US-SW-01 内部适配交付

当前交付有三种不同用途：N及V2的英文候选正文、源码候选；中文来源/权利/版本内部审计；逐动作交接表。它们以逻辑分包ID互相关联，尚未生成独立外发文件。所有人物、地址、合约、权限和出版事件均为本案模拟事实。英文稿不是已提交表单，不含有权人认证。

## 1. 适用依据和范围

美国候选按Standard Application的Literary Work准备。代码是计算机程序表达；不以本材料取得JSON转换功能、算法、API模式或所有同功能实现的排他权。三文件共同交付，CLI与API共用core，没有独立API商品或版本，建议一个程序版本作为本次工作对象，不因两个入口拆两份主张。没有GUI、游戏、CD-ROM、独立手册或其他作品一并登记；演示服务的部署记录不能让这三文件多出服务器或鉴权代码。

R01的17 USC §101/102/103用于对象、出版和新旧表达；R02 §201/204用于职务作品及转让；R03为37 CFR §202.20(c)(2)(vii)(A)交存要求；R05的§721.7—721.9与R06的§1509.1(F)是2021-01-28版行政手册。Circular 61（R04，rev 3/2021）仍引用旧(C)，实际2021手册位置是(F)，本稿按实际章节处理。eCFR当日显示Title 37截至2026-10-29、全Title末次修订2026-08-26，不能写成该条8月新修订。

AI部分依2023-03-16生效的登记政策R09及2025-01-29发布的报告R10。报告的人类表达控制分析不是修改法律，也不替代申请披露要求。线上出版结合R07/R08；字段语义用R05/R11/R12及§409（R13），未登录真实账户核实时控件、费用、字符限制或上传格式。中国的60页/每页50行、开发方式表式不用于本美国案。

普通短程序规则为≤50页交全部；秘密短程序选项R03为≤50页、R04/R06写&lt;50页，边界差异保留。本案选择完整极短源码，不借临界边界取巧；实际正式页式尚未生成。登记交存与§407的mandatory deposit不同，本案未核后者豁免，不把本次候选解释为已履行该义务。

## 2. N阶段：v1.0正常材料分析

N截至2026-06-02，只使用N01—N05。完成日期给定为2026-05-15，英文完成年填2026。N03给足有权批准、美国地域限制、公众取得并保留全部三源码、无更早/同时外国分发的事实，所以首次出版候选为2026-06-01、United States。它不是仅在线使用，也不用文件修改时间推出版。目标本身首次出版并不使整个v1.0成为需要排除的“既有旧版”；本案没有更早版本、原登记或第三方复制表达。

| 组件/贡献 | 作者候选与依据 | claimant和本次主张 | 处理决定 |
| --- | --- | --- | --- |
| v1.0 core/CLI | NQ为雇员职务作品的法定作者；EL在常规职责内创作，工资/福利、设备、任务及控制事实已给定 | NQ依职务关系；本版具体程序与非执行注释列候选 | 完整内部选材，不因还需现实验原件把模拟正常案全部待核 |
| v1.0 API | MC为独立承包作者，US公民/US domicile；不是NQ雇员，无特别委托类别及WMFH约定 | N02的2026-05-18签署书面全部版权转让覆盖v1.0 API和注释，NQ为候选claimant | 作者仍是MC，transfer按written agreement；不因付款改作者身份 |
| 标准库 | csv/io/json/argparse/pathlib/sys只是依赖引用 | 未复制标准库源码、不主张其表达 | 不收集或拼入其文件；不是因库名出现在import就声称整个程序第三方所有 |
| AI/旧内容 | N01明确本阶段独立人类创作、没有AI生成内容；N04无旧登记 | 本案不给不存在的AI/旧版排除 | 不借旧CN演练的AI摘要推翻本案事实 |

NQ的虚构权利关系只用于本案字段，不能证明真实harbor代码归这家公司。真实文件行1的原创合成/NC提示及中文标题保留，英文Harbor Record Formatter是演练约定译名。N01—N04支持内部正常候选，版权局实际判断和真实权属核验没有发生。

## 3. N英文候选正文：N-FIELDS-v1

# Harbor Record Formatter v1.0 — Internal US Registration Draft

This is a fictional training draft for internal review only. It has not been filed, certified, or paid for. The names, ownership history, address, and publication events below are scenario facts, not assertions about ownership of the actual repository assets.

| Field | Candidate entry |
| --- | --- |
| Application | Standard Application |
| Type of Work | Literary Work |
| Title of Work | Harbor Record Formatter v1.0 |
| Alternative title | 港湾记录整理器 v1.0; English working title shown above is the scenario translation |
| Year of Completion | 2026 |
| Publication Status | Published |
| Date of First Publication | June 1, 2026 |
| Nation of First Publication | United States |
| Author 1 | North Quay Tools LLC, the scenario employer-author of core.py and cli.py |
| Author 1 nationality/domicile | Domiciled in the United States; Washington-organized entity in this scenario |
| Author 1 Work Made for Hire | Yes; employee-created material within the scope of employment |
| Author 1 Author Created | Computer program: core.py and cli.py, including their nonexecuting comments |
| Author 2 | Maya Chen |
| Author 2 nationality/domicile | United States citizen; domiciled in the United States |
| Author 2 Work Made for Hire | No; independent contractor |
| Author 2 Author Created | Computer program: api.py, including its nonexecuting comments |
| Claimant | North Quay Tools LLC |
| Claimant address | 100 Example Quay, Seattle, WA 98101, United States — fictional training address only; not verified and never to be used for service or filing |
| Transfer Statement | By written agreement: Maya Chen assigned all copyright in the v1.0 api.py contribution and its comments to North Quay Tools LLC on May 18, 2026. The company is itself the work-made-for-hire author of the core.py and cli.py material. |
| Material Excluded | None identified in the supplied scenario for this first version. Python standard-library source is not included in the deposit or claimed as the applicant's authorship. |
| New Material Included | Computer program as identified above, including human-authored nonexecuting comments. No claim to algorithms, methods of operation, or the general JSON-to-CSV function. |
| Previous Registration | None. No earlier application, pending application, or registration is supplied for this work. |
| Rights and Permissions contact | No verified real contact supplied. Director to designate the authorized contact and details before any real filing. |
| Correspondent | No real correspondent or correspondence address supplied. Director to designate and verify. |
| Certificate mailing details | Not established. Director to confirm the actual recipient and address. The training address is not a filing address. |
| Certification | Not executed. An authorized certifier must review the actual application and attest personally if a real filing is later approved. |
| Fee/payment | Not approved or paid. Finance-manager must confirm the current fee, budget, payer, and authorized payment method for a separately approved application. |

## Note to Copyright Office — candidate text for internal discussion

The work identified in this draft is Harbor Record Formatter v1.0, also identified in the source comments as 港湾记录整理器 v1.0. The program consists of core.py, cli.py, and api.py released together as one version. Completion occurred in 2026. Under the supplied scenario, authorized members of the US public first obtained and were permitted to retain copies of all three source files on June 1, 2026. No earlier or simultaneous foreign distribution is supplied.

The claim described here concerns the computer-program expression and nonexecuting comments created by the two authors identified above. The employer-author created the core and CLI contributions through its employee acting within the scope of employment. Maya Chen created the API contribution as an independent contractor and assigned all copyright in that v1.0 contribution by a signed written agreement. No AI-generated material is identified for this version in the supplied facts. Standard-library implementation source is neither included nor claimed.

The proposed source-code material is the entire code of this short version, in the order core.py, cli.py, api.py. The three files contain 163 physical source lines in total, including blank lines and comments. This is a source-line count, not a claim about official page formatting. The actual deposit layout and upload file have not yet been produced or reviewed. The supplied files have no Copyright/©/Copr. notice identifying the fictional claimant; original repository notices and comments are retained, and no claimant notice has been invented. The internal source record below is the proposed material, not an uploaded deposit. No separate claim in a user manual, website, or screen-display artwork is proposed.

This text is an internal training candidate and must not be submitted as a representation that the fictional rights facts apply to the actual repository code.

## 4. N源码候选：N-SOURCE-v1

本段为完整实际三源码的内部母本候选，包含所有原行。拟美国短程序路线为完整源码，不遮盖；没有把依赖源码、说明书、重复core或凑数片段加入。物理原行按UTF-8解码后的splitlines()，含空行/注释；末尾LF属于字节，标题和围栏不算源码。源码母本、展示逻辑行与正式交存页数分账：本稿163选中去重原行；未调用分页/渲染工具，正式页数及页式未核。

| 文件ID | 原行 | 累计选材原行 | 字节 | SHA-256 |
| --- | --- | --- | --- | --- |
| US10-CORE | 1—63 | 1—63 | 2198 | 2ad5c9d389a7abbdb105c545d4ab2f72fdb4167aa728dbdb64dfb5df02f7bbe1 |
| US10-CLI | 1—46 | 64—109 | 1457 | 8929d151347f22ea23a3ace676e60ad0242da028577305198b1a36282883d86d |
| US10-API | 1—54 | 110—163 | 2491 | f954b7b976992b45d601d8d22215c0a2308ee4b7f9f9fdcfc0734395e5a2aad7 |

总计6146字节，163物理原行，163去重选中原行。选材区间可直接重建，不把三文件的串接当成一个可执行Python文件。首行是core原行1的v1.0说明；选材行63是core原行63，下一行64为CLI原行1；109为CLI原行46，110为API原行1；末行163为API原行54。以下三块分别保留文件边界，作为可核全文。

### v1.0 core.py 完整选材原文

US10-CORE，原行1—63，累计选材原行1—63。以下代码块内为源文件全文，文件标题不计源行，保留原注释与末尾换行。

```python
"""港湾记录整理器 v1.0：原创合成核心；沿用项目NC许可。"""

import csv
import io
import json

VERSION = "1.0"
FIELDS = ("id", "label", "value")
MAX_RECORDS = 1000


class InputError(ValueError):
    """只携带固定错误类别，不回显用户记录。"""


def decode_payload(raw):
    """UTF-8 JSON只解码，不在此决定字段是否合法。"""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputError("invalid_json") from error


def validate_records(records):
    """保持输入顺序；v1.0允许重复ID并忽略额外字段。"""
    if not isinstance(records, list):
        raise InputError("records_must_be_array")
    if len(records) > MAX_RECORDS:
        raise InputError("too_many_records")
    cleaned = []
    for record in records:
        if not isinstance(record, dict):
            raise InputError("record_must_be_object")
        if not all(field in record for field in FIELDS):
            raise InputError("missing_field")
        record_id, label, value = (record[field] for field in FIELDS)
        if not isinstance(record_id, str) or not record_id.strip():
            raise InputError("invalid_id")
        if not isinstance(label, str) or not label.strip():
            raise InputError("invalid_label")
        try:
            (record_id + label).encode("utf-8")
        except UnicodeEncodeError as error:
            raise InputError("invalid_text_encoding") from error
        if type(value) is not int or value < 0:
            raise InputError("invalid_value")
        cleaned.append({"id": record_id, "label": label, "value": value})
    return cleaned


def render_csv(records):
    """输出固定列和LF换行；引号、逗号等由csv模块转义。"""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def convert(raw):
    """返回CSV正文与记录数，空数组仍产生表头。"""
    records = validate_records(decode_payload(raw))
    return render_csv(records), len(records)
```

### v1.0 cli.py 完整选材原文

US10-CLI，原行1—46，累计选材原行64—109。以下代码块内为源文件全文，文件标题不计源行，保留原注释与末尾换行。

```python
"""港湾记录整理器 v1.0 CLI；原创合成，沿用项目NC许可。"""

import argparse
from pathlib import Path
import sys

from core import InputError, VERSION, convert


def parser():
    command = argparse.ArgumentParser(description="Convert JSON records to CSV")
    command.add_argument("input", type=Path, help="UTF-8 JSON input file")
    command.add_argument("output", type=Path, help="new UTF-8 CSV output file")
    command.add_argument("--version", action="version", version=VERSION)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        raw = args.input.read_bytes()
    except OSError:
        print("input_io_error", file=sys.stderr)
        return 4
    try:
        text, count = convert(raw)
    except InputError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        # 先完成全部输入验证，再以独占新建模式打开；绝不覆盖已有文件。
        with args.output.open("x", encoding="utf-8", newline="") as destination:
            destination.write(text)
    except FileExistsError:
        print("output_exists", file=sys.stderr)
        return 3
    except OSError:
        # 写入开始后的I/O故障可能留有部分新文件，不承诺原子写入。
        print("output_io_error", file=sys.stderr)
        return 4
    print(f"wrote {count} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### v1.0 api.py 完整选材原文

US10-API，原行1—54，累计选材原行110—163。以下代码块内为源文件全文，文件标题不计源行，保留原注释与末尾换行。

```python
"""港湾记录整理器 v1.0 WSGI；仅提供函数，不启动服务器。"""

import json

from core import InputError, convert

MAX_BODY_BYTES = 65536


def respond(start_response, status, body, content_type, extra=()):
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
    start_response(status, headers + list(extra))
    return [body]


def error_response(start_response, status, code, extra=()):
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    return respond(start_response, status, body, "application/json", extra)


def application(environ, start_response):
    """POST /convert：WSGI environ由调用者构造；无鉴权或网络入口。"""
    if environ.get("PATH_INFO") != "/convert":
        return error_response(start_response, "404 Not Found", "not_found")
    if environ.get("REQUEST_METHOD") != "POST":
        return error_response(start_response, "405 Method Not Allowed", "method_not_allowed",
                              [("Allow", "POST")])
    if environ.get("QUERY_STRING", ""):
        return error_response(start_response, "400 Bad Request", "invalid_query")
    content_type = environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return error_response(start_response, "415 Unsupported Media Type", "invalid_content_type")
    try:
        length = int(environ.get("CONTENT_LENGTH", ""))
    except (TypeError, ValueError):
        return error_response(start_response, "400 Bad Request", "invalid_length")
    if length <= 0:
        return error_response(start_response, "400 Bad Request", "invalid_length")
    if length > MAX_BODY_BYTES:
        return error_response(start_response, "413 Payload Too Large", "payload_too_large")
    stream = environ.get("wsgi.input")
    if stream is None:
        return error_response(start_response, "400 Bad Request", "missing_body")
    try:
        raw = stream.read(length)
    except (OSError, ValueError):
        return error_response(start_response, "400 Bad Request", "body_read_error")
    if not isinstance(raw, bytes) or len(raw) != length:
        return error_response(start_response, "400 Bad Request", "body_length_mismatch")
    try:
        text, _ = convert(raw)
    except InputError as error:
        return error_response(start_response, "400 Bad Request", str(error))
    return respond(start_response, "200 OK", text.encode("utf-8"), "text/csv; charset=utf-8")
```

## 5. V1阶段：保留冲突、继续已授权工作

V1截至2026-10-19，尚未收到V201—V205。v1.1源树已完成且可读，EL的core/CLI人工职务新增表达已有具体记录，可以继续做其范围、差异、候选字段和内部选材。MC的新API合同V102仅为非独占使用/修改/分发及内部准备/拟交存复制品许可；N02的旧API转让不能扩展到新表达，财务“付款所以全归公司”摘要不能代替转让。

V103给出经理“全纯人工”与开发日志“用生成工具”的冲突；现阶段只对API新增的具体人类贡献、AI保留范围及本次主张待补。向MC索取生成记录、逐段差异和实际改写；向CR核权限、作者及限制范围。不能让这个局部冲突把EL已给定的人类记录也改成未知。

V105仅有10-18公众调用转换服务并取得CSV的事实，未分发程序副本、源码或发行要约，不能据“上线”认定程序出版。基于当时记录可写未出版的内部暂定候选，同时请RM核有无其他复制品分发。保留该时点记录，不能以后得知10-20下载便说10-19当时故意漏报。

| 原V1草稿/问题 | V1内部替换候选 | 依据、责任及未决部分 |
| --- | --- | --- |
| all code original; no exclusions | Previously published v1.0 code is excluded. Proposed claim is limited to identified new human-authored revisions; the API revision provenance remains under review. | 旧版06-01已出版；CR处理新旧主张，不因v1.0未登记便纳入全部 |
| all authors NQ | NQ is the employer-author of the identified core.py/cli.py employee revisions. API authorship and any claim to API revisions are not yet settled. | MC是独立承包者；未取得新增全部权利与AI段落记录，不能直接填公司为全部作者 |
| unpublished | Unpublished on the facts supplied as of October 19, 2026; the October 18 service permits use of functionality without retaining program copies. Release-manager must check for any separate distribution. | 当时可说明已知事实，不填伪造出版日期/国家；不是永远不出版的保证 |
| full public deposit; no secret issue | Internal full-code master retained. Proposed short-program trade-secret option requires separate redacted-copy review before any external deposit. | V104提出CORE 50—52潜在秘密；DM/CR核实际版式及可见表达，不外发内部母本 |
| 旧v1.0代码目录换标题 | Rebuild a v1.1 source candidate against the three US11 hashes; do not reuse the old 163-line selection as v1.1. | 新版173行，全部文件哈希变化，技术行为和选材范围都须重建 |

### V1限定的英文说明候选：V1-NOTE

This internal draft concerns Harbor Record Formatter v1.1, completed in 2026. Code already published in v1.0 on June 1, 2026 is excluded from the proposed new claim. The documented employee-created revisions in core.py and cli.py may be described separately as new human-authored program revisions, subject to review of whether they contain sufficient original expression for derivative-work registration. No claim to the general duplicate-ID or strict-validation functions is proposed.

The new API contribution is not presently included in the proposed affirmative claim. Its contractor license is not an assignment of all copyright, and the records conflict as to the use and retention of AI-generated content. Specific authorship and provenance records have been requested. This issue does not negate the separate records supporting the employee's core and CLI revisions.

On the facts available as of October 19, 2026, the program has not been distributed in copies to the public. An online conversion demonstration began on October 18, but it does not supply program copies to users. The release history remains subject to the specific distribution check described in the internal audit.

The supplied internal material raises a potential trade-secret issue. A short-program deposit option consisting of the entire source code with only qualifying trade-secret portions blocked out is being considered. No redacted deposit has been finalized or submitted, and no representation of compliance or confidentiality is made. The precise locations and unredacted master remain in the internal audit rather than this prospective external note.

### V1秘密选材决定：内部审计V1-SECRET

V104的拟遮位置仅为US11-CORE原行50—52，绑定b91ea1a3cc3df01aa06d6c0f1f15bd15286821e750b7914e539f6f505f66f7cb；在V1拟交正文不复述该段原文。它是假定商业秘密的教学标签，真实文件没有秘密，但本阶段按给定用途限制演练。母本仍为三文件173行，不在原文件上删码。

可评估R03/R06的短程序全码遮秘密选项，同时告知Office材料含trade secret。DM须先生成可读完整版式，记录实际遮盖范围/所占比例和可见内容；CR判断可见部分是否仍有足量可版权原创表达，尤其本案新增人类部分很短，遮住核心新增后不能只凭旧代码或imports很多就称够用。遮盖部分须少于未遮部分，且后一项表达条件独立满足。3/173行只是定位统计，不能宣告法律比例/表达合格。

不要遮掉只是旧版、AI或非主张的新内容来使材料“看起来原创”。没有核完实际页式、秘密事实、可见表达、有效遮盖及用途批准，不形成可提交遮盖包。若无法保留足够表达，转CR评估special relief或其他有依据方案并由DIR决定，未提出/未获准特别救济；不能随意多删几行继续报通过。版权局交存不是绝对保密保险箱。V1整份审计和原码不随V1-NOTE外发；本示范的后阶段全码也不属于V1外发范围。

## 6. V2阶段：后补事实后的具体取舍

V2截至2026-10-28接收V201—V205。10-23签署转让仅解决MC拥有的新API人类表达权利链，不能给AI输出创造版权，也不能让MC追溯变成雇员。生成记录把US11-API 28—31及55—56定位为原样输出；53只是手工参数传递。旧API其他表达为US10或行位移，版本注释变化本身不当成足够新作品。

本次推荐候选主张限于EL在core/CLI中实际写出的新版人类程序表达；法定作者候选仍为NQ。对于MC的API原样生成段不主张，53的机械调用衔接在本案记录下不足以支持单独提出有原创性的新增API作者主张，故本候选不新增MC为v1.1所主张材料的作者。该取舍不是认定MC在任何其他作品中均无权利，V201及旧N02照常保留。若后续补出真正人类创造性表达，要重审作者/claimant/限制字段；不能先猜有未给定贡献。

AI六行是否达到de minimis不按行数裁定。本候选选择明确披露并在Material Excluded中排除这些已识别原样生成段，不声称法规规定“六行必然超过阈值”；这避免把它们包含在本次积极主张中。NQ仍可准备人类贡献部分的材料，含AI不使整个软件自动没有保护。

| 变化位置 | v1.0原行/内容 | v1.1原行/内容 | V2表达与主张处理 |
| --- | --- | --- | --- |
| 版本与签名 | CORE 7、24、60；各文件1 | CORE 7、24、66及各文件1变更 | 版本字面、参数名和功能性接口不能独立证明原创性 |
| 重复ID处理 | CORE 24—48无seen_ids分支 | CORE 31、50—52；循环其他位置随之变化 | EL人工实现记录支持候选，具体表达需与旧码及功能约束区分，不把拒绝重复ID这个功能本身主张为版权 |
| strict校验/组织 | CORE 24—48、60—63 | CORE 24—54、66—69，特别37—38及68 | 只拟主张新的人类表达及有依据的改写；旧解码/CSV表达仍排除新主张 |
| CLI开关及调用 | CLI 10—15、26 | CLI 10—16、27，特别14 | EL人工记录支持候选；--strict名称、机械传参不是自动可版权材料 |
| API query | API 28—29 | API 28—31 | MC原样保留AI输出，本次明确排除；后续32—33源自旧30—31的位移，不误当新增AI |
| API调用 | API 51 | API 53 | MC机械strict参数衔接，不在本次积极新增主张内 |
| API错误分流 | API 52—53均固定400 | API 54—56，其中55—56原样生成 | AI段明确排除，旧异常结构/共有行为不因位移变新 |

这份升级只有10行净增加、570字节净增加，真正新增表达范围又受上述限制，不能保证满足R05 §721.8的足够原创新表达门槛。CR应逐段核人类实际表达、功能必然约束和是否超出轻微例行修改；本稿是限定候选，登记可行性仍待专业审查，不能靠字段填齐或取得转让代替。这不阻碍继续形成准确的英文稿与全码母本。

V203证明10-20已经获权向美国公众发放可保留的完整US11源码，现有5名公众取得副本、美国地域限制及无更早/同时外国分发事实。候选出版状态改为Published、October 20, 2026、United States，不能继续援引10-18仅调用的旧结论。NQ在10-20依V102已有分发许可，不用10-23转让倒填当时权限。

V204撤销同字节潜在秘密标记，CORE 50—52已在获权完整下载中公开；当前没有其他秘密，推荐当前完整源码不遮盖。保留V1当时记录，不能删掉曾有秘密顾虑的历史。出版历史与本智能体的再次上传、发布、云处理授权仍分开；本轮只在内部准备。

## 7. V2英文完整候选正文：V2-FIELDS-v1

# Harbor Record Formatter v1.1 — Internal US Registration Draft

This is the complete revised internal training candidate as of October 28, 2026. It has not been filed, certified, or paid for. It is not a statement that the fictional company owns the actual repository assets. The limited new claim also requires substantive review of whether the identified revisions contain sufficient original authorship for registration.

| Field | Candidate entry |
| --- | --- |
| Application | Standard Application |
| Type of Work | Literary Work |
| Title of Work | Harbor Record Formatter v1.1 |
| Alternative title | 港湾记录整理器 v1.1; the English title is the scenario translation |
| Year of Completion | 2026; the v1.1 version was completed October 15, 2026 in the scenario |
| Publication Status | Published |
| Date of First Publication | October 20, 2026 |
| Nation of First Publication | United States |
| Author | North Quay Tools LLC, the employer-author of the identified employee-created revisions in core.py and cli.py |
| Author nationality/domicile | Domiciled in the United States; Washington-organized entity in this scenario |
| Work Made for Hire | Yes, for the employee-created material affirmatively claimed in this draft |
| Author Created | Revised computer program: identified new human-authored revisions in core.py and cli.py, including qualifying human-authored nonexecuting comments. Functional ideas and routine elements are not asserted as independently protectable authorship. |
| Claimant | North Quay Tools LLC |
| Claimant address | 100 Example Quay, Seattle, WA 98101, United States — fictional training address only; actual filing/service details must be independently supplied and verified |
| Transfer Statement | No transfer is relied upon for the authorship affirmatively claimed in this v1.1 draft: the claimant is the employer-author of that material. The separate May 18 and October 23 assignments concerning Maya Chen's API contributions are retained in the internal rights record, but are not used to claim excluded prior-version or AI-generated material. |
| Material Excluded | Previously published source code from Harbor Record Formatter v1.0; AI-generated API revisions retained verbatim at api.py source lines 28–31 and 55–56. No new claim is asserted in the contractor's mechanical parameter-forwarding change at api.py line 53. |
| New Material Included | Revised computer program expression created by the employee in core.py and cli.py, limited to the identified new human-authored revisions and qualifying comments. No new authorship in the API revision is affirmatively claimed in this candidate. |
| Previous Registration | None. Neither v1.0 nor v1.1 has a submitted, pending, or completed US registration in the supplied scenario. |
| Rights and Permissions contact | Not supplied for a real filing. Director must designate and verify the authorized contact. |
| Correspondent | Not appointed or verified. Director must approve the actual person and correspondence details. |
| Certificate mailing details | Not established. Director must verify the real recipient/address; the training address must not be used. |
| Certification | Not executed. The actual final claim, facts, source package, and authority must be reviewed by a human authorized certifier before any certification. |
| Fee/payment | Not approved or paid. Current amount, payer, budget, and payment channel remain for finance-manager to confirm for a separately approved filing. |

## Note to Copyright Office — revised candidate text for internal discussion

This draft identifies Harbor Record Formatter v1.1, also identified in the supplied source comments as 港湾记录整理器 v1.1. The three source files, core.py, cli.py, and api.py, form one jointly released program version. The version was completed in 2026. The first authorized distribution of copies of this version to members of the public occurred in the United States on October 20, 2026 under the supplied scenario. Those users were permitted to retain complete source copies. An earlier online conversion service did not distribute program copies. No earlier or simultaneous foreign distribution is supplied.

The proposed new claim is limited to identified employee-created revisions in core.py and cli.py. Source expression already published in v1.0 on June 1, 2026 is excluded from this new claim. The program's general function, duplicate-ID policy, strict-field policy, algorithms, and methods of operation are not claimed as such. The sufficiency of the limited new human expression for derivative-program registration remains a substantive review issue; this candidate does not represent that the Office has accepted it.

The supplied provenance record identifies api.py lines 28–31 and 55–56 as AI-generated revisions incorporated without human expressive revision. This material is expressly excluded from the proposed claim. No AI system or provider is named as an author. The only additional human API change identified in the record is mechanical parameter forwarding at line 53; no new copyrightable API authorship is affirmatively claimed here. This disclosure does not rely on an arbitrary line-count threshold for de minimis material. The independent employee-created revisions are separately documented. The API contractor's later assignment does not create copyright in excluded AI-generated content.

The proposed source material contains all three files for this short version, in the order core.py, cli.py, api.py: 173 physical source lines in total, including blank lines and comments. Previously published and AI-generated code remains in that complete source material for identification and context even though it is excluded from the affirmative claim. The source-line count is not an official deposit page count; a final readable deposit layout/upload file has not yet been prepared or approved. Original repository comments and notices remain unchanged. No fictional claimant copyright notice has been added.

The complete same-version source was made publicly available through the authorized distribution described above. The earlier internal proposal to treat a particular segment as a potential trade secret has therefore been withdrawn for this version and these bytes. No trade-secret redaction is proposed in the current source candidate. This is not a claim that registration deposit provides absolute confidentiality, nor authorization to perform a new upload. No user manual, website, or independent screen-display artwork is included in the proposed claim.

This is an internal training candidate only. Its fictional ownership and identity facts must not be presented as facts about the actual repository assets.

## 8. V2源码候选：V2-SOURCE-v1

本候选完整保留US11三文件，当前不遮盖；即使旧表达、AI段和机械衔接不在积极主张中，也不从短程序母本删掉。源量6716字节、173物理原行；去重选材173原行。展示标题/围栏不计源量，源文件未修改。尚未实际分页，未报官方页数/页式通过，也没有把173行假写成50页。

| 文件ID | 新原行 | 新累计选材原行 | 字节 | SHA-256 |
| --- | --- | --- | --- | --- |
| US11-CORE | 1—69 | 1—69 | 2463 | b91ea1a3cc3df01aa06d6c0f1f15bd15286821e750b7914e539f6f505f66f7cb |
| US11-CLI | 1—47 | 70—116 | 1572 | 127ffaef609a6e5a7c23bd66da43302aca88b4e63609c056c693f162da367c9a |
| US11-API | 1—57 | 117—173 | 2681 | bdcb73959c61dbec97980323008fd457ef6277e6cd9c09682a3bece93480f005 |

首行是CORE原行1；接缝69/70分别为CORE原行69和CLI原行1；116/117分别为CLI原行47和API原行1；末行173为API原行57。旧N的64/110起点不再适用。下列完整原文可按文件边界直接对应源文件；另生成独立交存文件时DM仍需核首页标题/版本、可读性、原行到输出行/页、实际文件类型及内容完整性。

### v1.1 core.py 完整选材原文

US11-CORE，原行1—69，累计选材原行1—69。以下代码块内为源文件全文，文件标题不计源行，保留原注释与末尾换行。

```python
"""港湾记录整理器 v1.1：原创合成核心；沿用项目NC许可。"""

import csv
import io
import json

VERSION = "1.1"
FIELDS = ("id", "label", "value")
MAX_RECORDS = 1000


class InputError(ValueError):
    """只携带固定错误类别，不回显用户记录。"""


def decode_payload(raw):
    """UTF-8 JSON只解码，不在此决定字段是否合法。"""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputError("invalid_json") from error


def validate_records(records, strict=False):
    """v1.1始终拒绝重复ID；strict还拒绝额外字段。"""
    if not isinstance(records, list):
        raise InputError("records_must_be_array")
    if len(records) > MAX_RECORDS:
        raise InputError("too_many_records")
    cleaned = []
    seen_ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise InputError("record_must_be_object")
        if not all(field in record for field in FIELDS):
            raise InputError("missing_field")
        if strict and set(record) != set(FIELDS):
            raise InputError("unknown_field")
        record_id, label, value = (record[field] for field in FIELDS)
        if not isinstance(record_id, str) or not record_id.strip():
            raise InputError("invalid_id")
        if not isinstance(label, str) or not label.strip():
            raise InputError("invalid_label")
        try:
            (record_id + label).encode("utf-8")
        except UnicodeEncodeError as error:
            raise InputError("invalid_text_encoding") from error
        if type(value) is not int or value < 0:
            raise InputError("invalid_value")
        if record_id in seen_ids:
            raise InputError("duplicate_id")
        seen_ids.add(record_id)
        cleaned.append({"id": record_id, "label": label, "value": value})
    return cleaned


def render_csv(records):
    """输出固定列和LF换行；引号、逗号等由csv模块转义。"""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def convert(raw, strict=False):
    """返回CSV正文与记录数，空数组仍产生表头。"""
    records = validate_records(decode_payload(raw), strict=strict)
    return render_csv(records), len(records)
```

### v1.1 cli.py 完整选材原文

US11-CLI，原行1—47，累计选材原行70—116。以下代码块内为源文件全文，文件标题不计源行，保留原注释与末尾换行。

```python
"""港湾记录整理器 v1.1 CLI；原创合成，沿用项目NC许可。"""

import argparse
from pathlib import Path
import sys

from core import InputError, VERSION, convert


def parser():
    command = argparse.ArgumentParser(description="Convert JSON records to CSV")
    command.add_argument("input", type=Path, help="UTF-8 JSON input file")
    command.add_argument("output", type=Path, help="new UTF-8 CSV output file")
    command.add_argument("--strict", action="store_true", help="reject unknown record fields")
    command.add_argument("--version", action="version", version=VERSION)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        raw = args.input.read_bytes()
    except OSError:
        print("input_io_error", file=sys.stderr)
        return 4
    try:
        text, count = convert(raw, strict=args.strict)
    except InputError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        # 先完成全部输入验证，再以独占新建模式打开；绝不覆盖已有文件。
        with args.output.open("x", encoding="utf-8", newline="") as destination:
            destination.write(text)
    except FileExistsError:
        print("output_exists", file=sys.stderr)
        return 3
    except OSError:
        # 写入开始后的I/O故障可能留有部分新文件，不承诺原子写入。
        print("output_io_error", file=sys.stderr)
        return 4
    print(f"wrote {count} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### v1.1 api.py 完整选材原文

US11-API，原行1—57，累计选材原行117—173。以下代码块内为源文件全文，文件标题不计源行，保留原注释与末尾换行。

```python
"""港湾记录整理器 v1.1 WSGI；仅提供函数，不启动服务器。"""

import json

from core import InputError, convert

MAX_BODY_BYTES = 65536


def respond(start_response, status, body, content_type, extra=()):
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
    start_response(status, headers + list(extra))
    return [body]


def error_response(start_response, status, code, extra=()):
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    return respond(start_response, status, body, "application/json", extra)


def application(environ, start_response):
    """POST /convert：WSGI environ由调用者构造；无鉴权或网络入口。"""
    if environ.get("PATH_INFO") != "/convert":
        return error_response(start_response, "404 Not Found", "not_found")
    if environ.get("REQUEST_METHOD") != "POST":
        return error_response(start_response, "405 Method Not Allowed", "method_not_allowed",
                              [("Allow", "POST")])
    query = environ.get("QUERY_STRING", "")
    if query not in ("", "strict=0", "strict=1"):
        return error_response(start_response, "400 Bad Request", "invalid_query")
    strict = query == "strict=1"
    content_type = environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return error_response(start_response, "415 Unsupported Media Type", "invalid_content_type")
    try:
        length = int(environ.get("CONTENT_LENGTH", ""))
    except (TypeError, ValueError):
        return error_response(start_response, "400 Bad Request", "invalid_length")
    if length <= 0:
        return error_response(start_response, "400 Bad Request", "invalid_length")
    if length > MAX_BODY_BYTES:
        return error_response(start_response, "413 Payload Too Large", "payload_too_large")
    stream = environ.get("wsgi.input")
    if stream is None:
        return error_response(start_response, "400 Bad Request", "missing_body")
    try:
        raw = stream.read(length)
    except (OSError, ValueError):
        return error_response(start_response, "400 Bad Request", "body_read_error")
    if not isinstance(raw, bytes) or len(raw) != length:
        return error_response(start_response, "400 Bad Request", "body_length_mismatch")
    try:
        text, _ = convert(raw, strict=strict)
    except InputError as error:
        status = "400 Bad Request" if str(error) == "invalid_json" else "422 Unprocessable Entity"
        return error_response(start_response, status, str(error))
    return respond(start_response, "200 OK", text.encode("utf-8"), "text/csv; charset=utf-8")
```

## 9. 内部审计：版本影响与待审事项

| 对象 | 保留的历史 | 当前影响/重审 | 责任及恢复条件 |
| --- | --- | --- | --- |
| N-FIELDS/N-SOURCE | v1.0事实、163行、两个作者及N02；只是正常内部候选，从未提交 | 不直接改标题当v1.1；新版主张需排除已出版旧表达 | EL/CR/DM按US11和新贡献重建，旧稿仍保留 |
| V1权利草稿 | 当时V102只有非独占许可，付款摘要不能替代转让 | V201补齐所拥有的新API人类表达转让；不改变独立承包作者身份，不扩大为AI版权 | CR核具体范围，API新主张仍按实际贡献取舍 |
| V1 AI未知 | 经理和开发日志冲突曾存在 | V202使六行AI和53机械衔接可定位；替换作者/Author Created/Material Excluded/New Material Included/Note | CR审是否需进一步披露/是否存在未给定贡献；当前不主张API新增 |
| V1未出版暂定 | 10-19只知10-18在线调用，未据其填写出版日 | V203证明10-20授权公众复制品分发，出版字段/Note和阶段说明重审 | RM确认版本哈希、首次日期/国家与无更早分发；本合成事实已足够支持候选 |
| V1秘密方案 | CORE 50—52潜在秘密及未完成遮盖方案保留，未伪造实际合格遮盖包 | V204撤销同字节秘密依据，当前全码不遮；旧秘密说明不能随新包使用 | DM核新输出内容，CR核当前分类；不删掉旧记录 |
| 源文件/行映射 | US10与US11六哈希及两份全量母本保留 | N→V1全部哈希、累计范围不同；V1→V2字节不变但出版/来源事实变化须重审字段与动作 | EL核技术差异；DM核当前选材，不能以hash相同免除事实重审 |
| 页式/渲染 | 本次尚未实际生成正式页式、可提交PDF或截图 | 当前英文稿/全码才是待排版版本；后续排版绑定当前字节，旧阶段截图即使存在也不能继承 | DM及rendering执行实际排版/可读性核对后另记证据 |
| 外部审批 | N/V1内部准备授权，不含外部委托/上传 | V2内容、主张、公开/秘密状态变化后要对具体外发子包重新批准 | DIR批准对象/用途/渠道/有效条件，必要专业审查和发送前复核完成 |
| 无需被改成未知的事实 | 两个入口共用core的同版产品关系；EL人工职务记录；旧版06-01出版；标准库无复制源码 | 后补API材料不推翻这些已经给定的事实；不把全部产品“重新待核” | 保留事实来源；如出现实际相反材料再定位重审 |

未决的实质点是这份小幅升级是否含足够可版权新表达，以及最终排版/申请内容/账户字段与权限的真实审查。它们不抹掉现有可用分析。两版都未实际提交，故当前只是内部候选修订，不是假定收到补正通知、pending更正或补充登记，更没有注册号、官方期限或回执。将来若事实变成已提交或已登记，才依据对应真实状态另核更正路线；不从本案预建期限。

## 10. 分包边界与具体行动

下列包ID是本文具名章节的逻辑分包，独立文件尚未导出。N-FIELDS-v1只指第3节英文候选；N-SOURCE-v1只指第4节全码和映射；V1-NOTE只指第5节限定英文说明；V1-SECRET只指该节内部秘密审计；V2-FIELDS-v1只指第7节；V2-SOURCE-v1只指第8节；D5-SW-AUDIT包含第2、5、6、9节中文来源/权利/变更分析及案卷。正文、代码、内部审计不是同一用途包，完整示范不默认进入eCO或外部邮件。

| 拟动作/具体版本与材料 | 接收对象及用途 | 渠道 | 有权角色/当前状态 | 恢复或完成条件 |
| --- | --- | --- | --- | --- |
| 内部交接N-FIELDS-v1/N-SOURCE-v1、当前V2-FIELDS-v1/V2-SOURCE-v1及单列D5-SW-AUDIT | EL核技术，CR核主张/权利，DM核选材；三类材料明确分开 | 本机outputs/adaptation-d5/；本资源为当前可读底稿，独立子包尚未导出 | DIR已批内部准备，作者已完成此稿；角色实际签核未发生 | 可继续内部修改/导出；交接时记录具体文件哈希和每个接收角色，不能把“稿已写”当签核 |
| 向MC补证/确认：V1问题单所列新API许可/转让及生成段落；V2只剩是否还有未供人类创造性改写记录 | MC，确定API来源/所拥权利和潜在新增作者事实 | V1内部由CR经本机问题单转交DIR指定的实际联络人；真实联系方式未提供，不发信 | CR整理问题已授权；外部联系未授权；V201/V202在演练中已收到 | 保留已补证结果，不再次索取同一事实；若主张新API贡献再由CR明确段落和证据需求，DIR补具体联络渠道并授权 |
| 向RM补证/核当前发布事实：V203记录、三US11哈希、首次美国分发与是否更早/海外记录 | RM，核Publication字段与秘密分类的事实基础 | 本机outputs/adaptation-d5/内部发行事实表 | 内部核对允许；本案V203已给足候选事实，真实角色未签核 | RM确认实际记录及覆盖范围；新反证只重审对应字段，不把本案已知复制品分发当未知 |
| 外部美国版权律师审阅：拟V2-FIELDS-v1、V2-SOURCE-v1和另制最小权利/AI摘要；不含整份案卷/旧潜在秘密审计 | 尚未确定的实际美国版权律师/机构；审查新增表达、作者/claimant、AI披露和交存 | 由DIR确认受控文件渠道、接收账户与保密条件；目前无可执行地址/渠道 | DIR未批准外部处理/委托，CR准备摘要可继续；未发送 | DIR确认具体人/机构、包版本与渠道/用途/期限；必要许可、数据路径、最小范围及发送前复核齐备，不虚构律师姓名 |
| USCO登记/交存：仅当前获准英文申请字段及据V2-SOURCE-v1制作的最终可读交存文件 | US Copyright Office；登记本版明确的新的人类表达，非上传内部审计 | 官方电子登记入口的经授权真实账户；本轮未登录，DIR指定账户操作人，DM核当期格式 | DIR未批准提交，专业门槛/页式未完成，未上传 | CR完成新表达可登记性/限制主张审查；DM生成并核实际文件/页式；DIR批准具体包/账户/用途；提交前复核并随后记录真实回执 |
| 认证：上述最终具体申请的事实声明，不含预签名空白稿 | 由DIR指定的有权真人认证人，经版权局申请渠道作真实认证 | 真实最终申请内的认证步骤；当前没有登录或已签字文件 | 未指定/未执行；智能体不能代替个人作事实认证 | 认证人审阅实际范围、作者、日期、来源、包及其权限后亲自确认；无真实身份/权限不填名字代签 |
| 付款：仅DIR批准的特定v1.1申请及当期费用，不与内部稿写作合并 | Copyright Office规定的收款流程；支付具体申请费 | finance-manager核官方支付流程/付款工具，当前账户/金额/付款方式未知 | finance-manager未批预算/付款，未发生扣款 | DIR先定申请，finance-manager核当前金额、预算及有权付款人/渠道，另行批准；不凭R04历史费率猜金额 |
| 新源码公开：US11完整三文件或任一拟新发布包，附真实适用许可/通知 | DIR确定的公众或特定接收人；具体发布目的待其说明 | DIR/发布负责人确定实际站点、版本与账号；本轮不操作 | 演练10-20历史下载不授权智能体再发布；真实代码NC许可不因故事变更 | 核真实权利/许可、实际包和目的，DIR给具体发布授权；若新秘密/未公开技术出现先核对应披露边界 |
| 新云/外部模型处理：拟送的V2字段、代码或摘要逐一列入新包，不默认含审计/全部源码 | 具体新服务商、模型/存储接收方尚未选；目的和最小材料由CR提出 | 先由DIR核实际工具/账号、索引/日志/存储/保留路径；当前无授权渠道 | 当前宿主处理公开教学资产已准，新云处理未授权，未上传 | 先明确服务商/数据路径/许可和最小包，再取得该用途具体授权；“代码曾公开”不能替代动作授权 |

本轮已经完成的是内部分析、英文候选、完整实际源码选材及行动条件。未发生外部律师联系、USCO提交/交存、认证、付款、新发布或新云上传。八项开发检查、代码计数或日后渲染也不能升级为版权局接受、独立专业验收或稳定交付。

<!-- END D5-SW WORK PRODUCT -->

## 原始合成案卷（完整输入，非外发正文）

下列JSON原样保留本轮题目，包括原始实际diff和依赖清单。其path是来源定位，包内使用上面的六源码及US规则资源，不要求安装开发evals目录。字段status=input_only_no_answer_yet是冻结题目原有状态，保留原文，不表示本资源没有上面的作者答卷。人物和权利事实只在此演练成立。

```json
{
  "id": "D5-US-SW-01",
  "batch": "adaptation-d5",
  "kind": "synthetic_staged_development_case_not_real_registration",
  "prepared_on": "2026-11-01",
  "status": "input_only_no_answer_yet",
  "capability_ids": [
    "SW-01",
    "SW-02",
    "SW-03",
    "SW-05",
    "SW-07",
    "SW-08"
  ],
  "work_packages": [
    "WP-06",
    "WP-10"
  ],
  "acceptance_references": [
    "AC-SW-01",
    "AC-SW-02",
    "AC-SW-03",
    "AC-SW-05",
    "AC-SW-07",
    "AC-SW-08",
    "DG-08",
    "DG-17"
  ],
  "task": "以美国版权登记为目标，完成同一产品v1.0正常材料、v1.1升级初报及后补事实后的分阶段内部工作稿。交中文判断和可直接讨论的英文Standard Application字段/说明、真实源码全量选材与原行映射、版本影响及逐动作具体交接。不得真实提交、认证、付款、联系外部或声称登记成功。每阶段独立说明当时可作与不可作，后补材料不倒填到最初已知。",
  "synthetic_boundary": [
    "六个harbor-demo源码文件是实际可读原创合成资产；本案所有作者、主体、合同、出版、AI生成、保密标记、批准和日期都是为US适配另造的模拟事实，与D2/D4及其他CN案互不继承。",
    "真实源码仍按项目PolyForm Noncommercial 1.0.0及单独商业授权使用；North Quay Tools LLC、Maya Chen等是虚构演练角色，模拟签署或转让不是对真实仓库的权属证明、许可替换或版权转让。",
    "六文件原行1中的中文名称、原创合成/NC提示、函数docstring不改写、不删；英文候选用约定译名作为本演练标题，不把真实注释重写成虚构公司版权通知。没有实际Copyright/©/Copr.通知就不伪造通知页。",
    "软件字节许可与本轮合成案卷内部准备授权分开。实际材料不含私人案件、真实秘密或真实凭证；本轮允许在当前宿主与本地工具读取这些公开教学资产，不称离线处理。外部AI新上传、真实登记、公开代码、邮件、律师委托及账户操作均未授权。"
  ],
  "local_input_dependencies": [
    "AGENTS.md",
    "README.md",
    "docs/development-standards.md",
    "docs/capability-contracts.md",
    "skills/dyz-software/SKILL.md",
    "skills/dyz-software/resources/cn-core-method.md",
    "skills/dyz-software/resources/harbor-example.md",
    "LICENSE",
    "COMMERCIAL-LICENSE.md",
    "skills/dyz-software/resources/harbor-demo/v1.0/core.py",
    "skills/dyz-software/resources/harbor-demo/v1.0/cli.py",
    "skills/dyz-software/resources/harbor-demo/v1.0/api.py",
    "skills/dyz-software/resources/harbor-demo/v1.1/core.py",
    "skills/dyz-software/resources/harbor-demo/v1.1/cli.py",
    "skills/dyz-software/resources/harbor-demo/v1.1/api.py",
    "references/jurisdictions/us-software-evidence-20261101.md"
  ],
  "source_reading_limits": "旧CN方法/示范只供了解字节资产与历史演练隔离，不作美国法源或本案权属/AI/发表证据；不读取其他未授权源码、目录、私有案件或参考仓库。未运行程序，不编运行截图或通过状态。",
  "code_manifest": [
    {
      "id": "US10-CORE",
      "path": "skills/dyz-software/resources/harbor-demo/v1.0/core.py",
      "version": "v1.0",
      "bytes": 2198,
      "sha256": "2ad5c9d389a7abbdb105c545d4ab2f72fdb4167aa728dbdb64dfb5df02f7bbe1",
      "encoding": "UTF-8, no BOM; LF with final LF",
      "physical_lines": 63,
      "full_source_range": [
        1,
        63
      ],
      "ordered_selection_range": [
        1,
        63
      ]
    },
    {
      "id": "US10-CLI",
      "path": "skills/dyz-software/resources/harbor-demo/v1.0/cli.py",
      "version": "v1.0",
      "bytes": 1457,
      "sha256": "8929d151347f22ea23a3ace676e60ad0242da028577305198b1a36282883d86d",
      "encoding": "UTF-8, no BOM; LF with final LF",
      "physical_lines": 46,
      "full_source_range": [
        1,
        46
      ],
      "ordered_selection_range": [
        64,
        109
      ]
    },
    {
      "id": "US10-API",
      "path": "skills/dyz-software/resources/harbor-demo/v1.0/api.py",
      "version": "v1.0",
      "bytes": 2491,
      "sha256": "f954b7b976992b45d601d8d22215c0a2308ee4b7f9f9fdcfc0734395e5a2aad7",
      "encoding": "UTF-8, no BOM; LF with final LF",
      "physical_lines": 54,
      "full_source_range": [
        1,
        54
      ],
      "ordered_selection_range": [
        110,
        163
      ]
    },
    {
      "id": "US11-CORE",
      "path": "skills/dyz-software/resources/harbor-demo/v1.1/core.py",
      "version": "v1.1",
      "bytes": 2463,
      "sha256": "b91ea1a3cc3df01aa06d6c0f1f15bd15286821e750b7914e539f6f505f66f7cb",
      "encoding": "UTF-8, no BOM; LF with final LF",
      "physical_lines": 69,
      "full_source_range": [
        1,
        69
      ],
      "ordered_selection_range": [
        1,
        69
      ]
    },
    {
      "id": "US11-CLI",
      "path": "skills/dyz-software/resources/harbor-demo/v1.1/cli.py",
      "version": "v1.1",
      "bytes": 1572,
      "sha256": "127ffaef609a6e5a7c23bd66da43302aca88b4e63609c056c693f162da367c9a",
      "encoding": "UTF-8, no BOM; LF with final LF",
      "physical_lines": 47,
      "full_source_range": [
        1,
        47
      ],
      "ordered_selection_range": [
        70,
        116
      ]
    },
    {
      "id": "US11-API",
      "path": "skills/dyz-software/resources/harbor-demo/v1.1/api.py",
      "version": "v1.1",
      "bytes": 2681,
      "sha256": "bdcb73959c61dbec97980323008fd457ef6277e6cd9c09682a3bece93480f005",
      "encoding": "UTF-8, no BOM; LF with final LF",
      "physical_lines": 57,
      "full_source_range": [
        1,
        57
      ],
      "ordered_selection_range": [
        117,
        173
      ]
    }
  ],
  "actual_diff": [
    {
      "file": "core.py",
      "algorithm": "difflib.SequenceMatcher(..., autojunk=False), splitlines(), exact lines",
      "changes": [
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            1,
            1
          ],
          "new_range_1based_inclusive": [
            1,
            1
          ],
          "old_lines": [
            "\"\"\"港湾记录整理器 v1.0：原创合成核心；沿用项目NC许可。\"\"\""
          ],
          "new_lines": [
            "\"\"\"港湾记录整理器 v1.1：原创合成核心；沿用项目NC许可。\"\"\""
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            7,
            7
          ],
          "new_range_1based_inclusive": [
            7,
            7
          ],
          "old_lines": [
            "VERSION = \"1.0\""
          ],
          "new_lines": [
            "VERSION = \"1.1\""
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            24,
            25
          ],
          "new_range_1based_inclusive": [
            24,
            25
          ],
          "old_lines": [
            "def validate_records(records):",
            "    \"\"\"保持输入顺序；v1.0允许重复ID并忽略额外字段。\"\"\""
          ],
          "new_lines": [
            "def validate_records(records, strict=False):",
            "    \"\"\"v1.1始终拒绝重复ID；strict还拒绝额外字段。\"\"\""
          ]
        },
        {
          "operation": "insert",
          "old_range_1based_inclusive": null,
          "new_range_1based_inclusive": [
            31,
            31
          ],
          "old_lines": [],
          "new_lines": [
            "    seen_ids = set()"
          ]
        },
        {
          "operation": "insert",
          "old_range_1based_inclusive": null,
          "new_range_1based_inclusive": [
            37,
            38
          ],
          "old_lines": [],
          "new_lines": [
            "        if strict and set(record) != set(FIELDS):",
            "            raise InputError(\"unknown_field\")"
          ]
        },
        {
          "operation": "insert",
          "old_range_1based_inclusive": null,
          "new_range_1based_inclusive": [
            50,
            52
          ],
          "old_lines": [],
          "new_lines": [
            "        if record_id in seen_ids:",
            "            raise InputError(\"duplicate_id\")",
            "        seen_ids.add(record_id)"
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            60,
            60
          ],
          "new_range_1based_inclusive": [
            66,
            66
          ],
          "old_lines": [
            "def convert(raw):"
          ],
          "new_lines": [
            "def convert(raw, strict=False):"
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            62,
            62
          ],
          "new_range_1based_inclusive": [
            68,
            68
          ],
          "old_lines": [
            "    records = validate_records(decode_payload(raw))"
          ],
          "new_lines": [
            "    records = validate_records(decode_payload(raw), strict=strict)"
          ]
        }
      ]
    },
    {
      "file": "cli.py",
      "algorithm": "difflib.SequenceMatcher(..., autojunk=False), splitlines(), exact lines",
      "changes": [
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            1,
            1
          ],
          "new_range_1based_inclusive": [
            1,
            1
          ],
          "old_lines": [
            "\"\"\"港湾记录整理器 v1.0 CLI；原创合成，沿用项目NC许可。\"\"\""
          ],
          "new_lines": [
            "\"\"\"港湾记录整理器 v1.1 CLI；原创合成，沿用项目NC许可。\"\"\""
          ]
        },
        {
          "operation": "insert",
          "old_range_1based_inclusive": null,
          "new_range_1based_inclusive": [
            14,
            14
          ],
          "old_lines": [],
          "new_lines": [
            "    command.add_argument(\"--strict\", action=\"store_true\", help=\"reject unknown record fields\")"
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            26,
            26
          ],
          "new_range_1based_inclusive": [
            27,
            27
          ],
          "old_lines": [
            "        text, count = convert(raw)"
          ],
          "new_lines": [
            "        text, count = convert(raw, strict=args.strict)"
          ]
        }
      ]
    },
    {
      "file": "api.py",
      "algorithm": "difflib.SequenceMatcher(..., autojunk=False), splitlines(), exact lines",
      "changes": [
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            1,
            1
          ],
          "new_range_1based_inclusive": [
            1,
            1
          ],
          "old_lines": [
            "\"\"\"港湾记录整理器 v1.0 WSGI；仅提供函数，不启动服务器。\"\"\""
          ],
          "new_lines": [
            "\"\"\"港湾记录整理器 v1.1 WSGI；仅提供函数，不启动服务器。\"\"\""
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            28,
            28
          ],
          "new_range_1based_inclusive": [
            28,
            29
          ],
          "old_lines": [
            "    if environ.get(\"QUERY_STRING\", \"\"):"
          ],
          "new_lines": [
            "    query = environ.get(\"QUERY_STRING\", \"\")",
            "    if query not in (\"\", \"strict=0\", \"strict=1\"):"
          ]
        },
        {
          "operation": "insert",
          "old_range_1based_inclusive": null,
          "new_range_1based_inclusive": [
            31,
            31
          ],
          "old_lines": [],
          "new_lines": [
            "    strict = query == \"strict=1\""
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            51,
            51
          ],
          "new_range_1based_inclusive": [
            53,
            53
          ],
          "old_lines": [
            "        text, _ = convert(raw)"
          ],
          "new_lines": [
            "        text, _ = convert(raw, strict=strict)"
          ]
        },
        {
          "operation": "replace",
          "old_range_1based_inclusive": [
            53,
            53
          ],
          "new_range_1based_inclusive": [
            55,
            56
          ],
          "old_lines": [
            "        return error_response(start_response, \"400 Bad Request\", str(error))"
          ],
          "new_lines": [
            "        status = \"400 Bad Request\" if str(error) == \"invalid_json\" else \"422 Unprocessable Entity\"",
            "        return error_response(start_response, status, str(error))"
          ]
        }
      ]
    }
  ],
  "code_scope": {
    "ordered_files": [
      "core.py",
      "cli.py",
      "api.py"
    ],
    "one_product": "两个入口共用core，三文件共同交付、同一版本；没有独立API商品、GUI、数据库、服务器启动器、CD-ROM、外部手册或游戏。",
    "imports": "仅引用csv/io/json/argparse/pathlib/sys等Python标准库；未复制标准库源码，不收集/提交其文件，也不把这些模块表达主张为自有。",
    "counts_are": "实际字节和含注释空行的物理原行，非原创性数量、官方行数或页数；两版各3文件，原文件不修改。",
    "version_facts": "v1.0允许重复ID且忽略额外字段；v1.1总是拒绝重复ID，并提供可选strict字段校验、CLI开关、API查询开关和InputError状态分流。具体行为以源码为准。"
  },
  "actors": [
    {
      "id": "NQ",
      "name": "North Quay Tools LLC",
      "synthetic": true,
      "role": "美国华盛顿州成立、domiciled in United States的模拟公司；内部委托人/拟claimant",
      "address": "100 Example Quay, Seattle, WA 98101, United States — fictional training address, never use for service",
      "authority": "director可批准登记包/外部交付，finance-manager另批准实际付款，copyright-reviewer审核主张；目前只批内部准备"
    },
    {
      "id": "EL",
      "name": "Evan Lin",
      "synthetic": true,
      "role": "NQ全职软件雇员；技术负责人；v1.0 core/CLI及v1.1相应改动创作记录负责人",
      "employment_facts": "NQ薪资/福利、提供设备及工作地点、日常控制任务与工作时间；在常规开发职责内按NQ任务完成所述代码；无相反权利保留约定，模拟原始笔记及逐段草稿可用"
    },
    {
      "id": "MC",
      "name": "Maya Chen",
      "synthetic": true,
      "role": "美国公民、domiciled in United States的独立承包开发者；API贡献人",
      "employment_facts": "自备设备、独立决定工作时间/方式、按项目收款、无NQ雇员福利；合同不称work made for hire，也无九类特别委托事实"
    },
    {
      "id": "CR",
      "name": "copyright-reviewer",
      "synthetic": true,
      "role": "内部版权材料负责人，审核作者/权利/原创性门槛；不是本答卷的实际执业签核人"
    },
    {
      "id": "RM",
      "name": "release-manager",
      "synthetic": true,
      "role": "确认具体版本首次复制品分发与地域记录"
    },
    {
      "id": "DM",
      "name": "deposit-manager",
      "synthetic": true,
      "role": "源码母本、映射、页式和秘密/可见表达核对"
    },
    {
      "id": "DIR",
      "name": "director",
      "synthetic": true,
      "role": "NQ有权人；有权决定具体未来申请/外发；没有在本案授权实际执行"
    }
  ],
  "stages": [
    {
      "stage": "N",
      "as_of": "2026-06-02",
      "purpose": "v1.0正常材料，可完整准备内部英文候选和全源码选材，不提交",
      "materials": [
        {
          "id": "N01",
          "kind": "synthetic_product_and_completion_record",
          "facts": "Harbor Record Formatter v1.0，完成2026-05-15；核心与CLI由EL在上述职务事实内独立人工创作，API由MC独立人工创作；本阶段没有AI生成内容。三文件字节正对应US10清单。"
        },
        {
          "id": "N02",
          "kind": "synthetic_signed_assignment",
          "facts": "MC于2026-05-18签署、NQ同日接受的书面assignment明确把v1.0 api.py及其注释的全部版权转让给NQ，含重制、改编、分发及登记；非仅nonexclusive license，无权利保留、无第三方复制。本案视该模拟条款/签署事实已充分给定，不以未见现实原件把正常案全部待核；现实办理仍须验原件。"
        },
        {
          "id": "N03",
          "kind": "synthetic_authorized_public_distribution",
          "facts": "NQ有权director于2026-06-01批准v1.0三份完整Python源码向美国公众下载并长期保留，US限定下载入口当天已有3名美国公众用户成功取得全部三文件；当日只在美国可取得复制品，无其他国家同时或更早分发。下载字节与US10一致，非只在线调用。首次出版日期/国家候选由此判断，不靠仓库mtime。"
        },
        {
          "id": "N04",
          "kind": "synthetic_prior_registration_and_secret_record",
          "facts": "从未对v1.0或更早版本申请/登记、无待决申请或注册号；没有另标秘密，无外部手册/显示作品并入请求。"
        },
        {
          "id": "N05",
          "kind": "synthetic_internal_authorization",
          "facts": "DIR允许EL/CR/DM经本机outputs/adaptation-d5/内部讨论两份包：英文字段和说明、完整US10源码与来源映射。公开下载历史是模拟事实，不是本智能体发布授权；本轮不登录或提交eCO。"
        }
      ]
    },
    {
      "stage": "V1",
      "as_of": "2026-10-19",
      "purpose": "v1.1完成后内部升级初报，保留相对N的变更和冲突",
      "materials": [
        {
          "id": "V101",
          "kind": "synthetic_completion_and_version",
          "facts": "v1.1于2026-10-15完成，字节为US11；EL人工写出core.py新代码/注释及CLI更新，逐段草稿显示为本人表达而非AI粘贴。旧US10在06-01已出版。N阶段从未真正提交，至今两版无任何US登记或pending申请。"
        },
        {
          "id": "V102",
          "kind": "synthetic_contract_conflict",
          "facts": "MC承接v1.1 API更新的09-25合同只给NQ运行、修改、分发和内部准备/拟交存复制品的非独占许可，保留新增表达版权；N02只转让v1.0，不覆盖以后新增。财务摘要写“已付款所以全部版权都归NQ”，没有新签署转让。本阶段版权不足问题不影响EL已给定职务创作事实。"
        },
        {
          "id": "V103",
          "kind": "synthetic_ai_ambiguity",
          "facts": "项目经理摘要称三组件均纯人工；MC开发日志称API升级使用生成工具，未说明哪些输出原样保留，也无逐段人类改写证据。没有理由把经理摘要当优先事实，须具体补证；不得把未知AI范围扩张到EL已有独立人工记录的core/CLI。"
        },
        {
          "id": "V104",
          "kind": "synthetic_internal_secret_request",
          "facts": "DM收到将US11-CORE 50—52行的重复ID检查作为潜在商业秘密的内部请求：当时未向公众释放v1.1，限制内部访问；实际本仓库这些行只是公开合成资产，本案按假定秘密做路线分析。要求先拟短程序秘密路线/遮盖位置与可见新表达分析，不把行数百分比当法律已满足；不在拟外发正文重复被遮段。"
        },
        {
          "id": "V105",
          "kind": "synthetic_online_service_only",
          "facts": "10-18启用演示站点允许公众上传JSON并拿CSV；没有提供程序副本、下载、源码展示或向中间人发行的要约，只有调用功能。RM当时称v1.1未出版。旧表单初稿误写“2026完成；unpublished；all code original; all authors NQ; no exclusions”。它不是已提交的表单。"
        },
        {
          "id": "V106",
          "kind": "synthetic_internal_authorization",
          "facts": "继续准许内部读取US10/US11、统计差异、写限定主张及秘密方案，渠道仍为本机outputs/adaptation-d5/交EL/CR/DM；无MC额外转让签署、外部律师/云处理、付款、认证、提交或公开授权。"
        }
      ]
    },
    {
      "stage": "V2",
      "as_of": "2026-10-28",
      "purpose": "后补权属/AI与新增出版证据到达；形成完整更新候选，保留V1历史",
      "materials": [
        {
          "id": "V201",
          "kind": "synthetic_signed_new_assignment",
          "facts": "MC于2026-10-23签署书面assignment，将其拥有的v1.1 API新增人类表达全部版权转给NQ，并允许相应内部准备和未来经批准的登记交存；不声称转让AI输出中不存在的版权，不反向改变MC是独立承包人或N02只覆盖旧版的事实。"
        },
        {
          "id": "V202",
          "kind": "synthetic_ai_segment_provenance",
          "facts": "补交完整模拟生成记录/逐段diff：US11-API 28—31及55—56行为生成工具直接输出，MC只原样粘贴；US11-API 53行是MC手工将strict参数传给convert的机械调用衔接。其余API表达来自旧US10或行位移，行1仅更新版本。MC没有其他新增选择/排列或表达改写证据。EL确认core/CLI新增仍由其人工创作，不与该生成记录混同。提供这些事实后不能继续称API全纯人工、AI只排版，也不能把MC签字变成人类创作证明。AI六行是否超过de minimis及余下新表达充分性由本案规则与具体分析处理，不给固定行数阈值或预设专业结论。"
        },
        {
          "id": "V203",
          "kind": "synthetic_release_and_public_download_records",
          "facts": "RM提交10-20补充发布批准及下载记录：DIR当日批准向美国公众下载并保留完整v1.1三文件，NQ依V102已有分发许可执行；限定美国地域且当日无海外复制品分发，已有5名美国公众成功取得与US11完全一致的源码。没有更早v1.1副本分发。不是只有SaaS/API调用，也不是未授权泄露；无需推定全球首次出版国。"
        },
        {
          "id": "V204",
          "kind": "synthetic_secret_reclassification",
          "facts": "完整公开下载已包含US11-CORE 50—52，DM确认V104潜在秘密请求对同字节不再维持，无其他秘密。保留V104为当时内部记录但当前不可据此遮码；并不因此自动批准本次登记外发。"
        },
        {
          "id": "V205",
          "kind": "synthetic_target_and_permission",
          "facts": "当前拟讨论的主包对象为Harbor Record Formatter v1.1，不把v1.0正常样稿直接改版本号；NQ可候选主张已取得的本版新的人类表达，必须分析这份很短升级是否足以支持衍生作品登记，不因10行净增量或公司取得权利就保证可登记。当前允许形成完整英文内部字段、Note to CO及全源码选材；DIR尚未批准eCO提交/认证，finance-manager未批准费用，外部美国律师姓名/机构/渠道均未提供。"
        }
      ]
    }
  ],
  "required_deliverables": [
    "按N、V1、V2三阶段交中文范围/作者/claimant/新旧表达/AI/出版/秘密/路线分析，明确哪些判断已可作，哪些缺口影响哪些字段或动作；不以全部待核回避正常案。",
    "为N及V2分别给完整可独立读的英文Standard Application候选字段表与Note to Copyright Office草稿。至少含Type of Work、Title、Year of Completion、Publication status/date/nation、各作者/职务作品、Author Created、claimant、transfer、Material Excluded、New Material Included、Previous Registration，以及联系/认证/付款的真实状态。无事实字段不造值；不将模拟地址当可服务地址，不替人签名认证。V1给必要差异/暂定文本及补件。",
    "六文件各报实际bytes/SHA-256/UTF-8 splitlines原行；固定core→CLI→API全量顺序，N与V2的短程序真实源码完整候选和原行对应至少有可重建全区间清单及首末/接缝例；需要实际源文本时保留字节/原行，不复写伪代码、不删除旧或AI代码凑主张。实际页面数与原行数分账，未排版则明确未生成，后续由DM核页式。",
    "V1给具体秘密位置及适用短程序选项、实际母本/可见表达待核和停止条件；V2根据授权公开全字节事实更新路线。主张排除/秘密遮盖/来源保留分别解释。真实文件不改。",
    "实际逐文件差异定位到新旧行，至少覆盖重复ID、strict、CLI传递、API查询与错误状态；新表达归属/AI与差异关联，不把所有changed lines视为可版权表达；原有core/API不凭升级变新。",
    "给版本影响表：N旧材料、V1未出版/权利/AI/秘密草稿、V2新证据各保留，明确受影响字段/选材/正文/页式/外发批准与不受影响事实；都未提交，所以不虚构补正通知、期限或补充登记号。",
    "正文、内部权利/来源/秘密审计、行动表分开。逐行绑定内部继续、向MC/RM补证、外部律师审阅、USCO登记/交存、认证、付款、源码发布与新云处理的具体拟包/接收方/用途/渠道/有权者/状态/恢复条件。未知外部联系方式由DIR补齐，不虚构律师或账户，不执行动作。"
  ],
  "non_goals": [
    "真实账户或提交",
    "费用数字和处理时长预测",
    "法院侵权/损害赔偿意见",
    "把本代码判成已达到法律原创性门槛",
    "修改原源文件/规则JSON/业务工具/历史记录",
    "将US单案扩大成全球支持或稳定验收"
  ],
  "review_note": "题目与rubric由开发作者预设并对其可见；本案不是隐藏题或独立专业验收。依赖字节与规则研究需根代理冻结预检后才进入方法/答卷阶段。"
}
```
