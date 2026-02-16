import json
import readline  # noqa: F401 — enables line editing in input()
import sys

from varlink_shell.shell import execute, parse, pretty_print


def main():
    interactive = sys.stdin.isatty()

    while True:
        try:
            line = input("vsh> ") if interactive else input()
        except (EOFError, KeyboardInterrupt):
            if interactive:
                print()
            break

        line = line.strip()
        if not line:
            continue
        if line == "exit":
            break

        try:
            stages = parse(line)
            if not stages:
                continue
            objects = execute(line)
            if interactive or stages[-1][0] == "print":
                if not stages[-1][0] == "print":
                    pretty_print(objects)
            else:
                for obj in objects:
                    print(json.dumps(obj))
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
