import readline  # noqa: F401 — enables line editing in input()
import sys

from varlink_shell.shell import execute, parse, pretty_print


def main():
    while True:
        try:
            line = input("vsh> ")
        except (EOFError, KeyboardInterrupt):
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
            pretty_print(objects)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
