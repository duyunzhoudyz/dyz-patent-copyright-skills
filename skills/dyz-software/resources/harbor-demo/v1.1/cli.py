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
