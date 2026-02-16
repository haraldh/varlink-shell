import json
import os
import shlex
import stat

import varlink
from varlink.scanner import _Method

# ---------------------------------------------------------------------------
# Service setup
# ---------------------------------------------------------------------------

service = varlink.Service(
    vendor="varlink-shell",
    product="varlink-shell",
    version="0.1",
    url="https://varlink.org",
    interface_dir=os.path.dirname(__file__),
)


# ---------------------------------------------------------------------------
# Builtins
# ---------------------------------------------------------------------------


@service.interface("sh.builtin")
class Builtins:
    def Echo(self, args, input=None, _more=True):
        if input:
            for i, obj in enumerate(input):
                yield {"object": obj, "_continues": i < len(input) - 1}
        else:
            obj = {}
            for arg in args:
                if "=" in arg:
                    k, v = arg.split("=", 1)
                    obj[k] = v
                else:
                    obj[arg] = True
            yield {"object": obj, "_continues": False}

    def Ls(self, args, _more=True):
        path = args[0] if args else "."
        entries = sorted(os.listdir(path))
        for i, name in enumerate(entries):
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                ftype = "dir"
            elif stat.S_ISLNK(st.st_mode):
                ftype = "link"
            else:
                ftype = "file"
            yield {
                "name": name, "type": ftype, "size": st.st_size,
                "_continues": i < len(entries) - 1,
            }

    def Count(self, input=None, _more=True):
        count = len(input) if input else 0
        yield {"count": count, "_continues": False}

    def Help(self, _more=True):
        interface = service.interfaces["sh.builtin"]
        methods = [
            (name.lower(), member.doc.strip() if member.doc else "")
            for name, member in interface.members.items()
            if isinstance(member, _Method)
        ]
        for i, (cmd, doc) in enumerate(methods):
            yield {
                "command": cmd, "description": doc,
                "_continues": i < len(methods) - 1,
            }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(line):
    """Parse a command line into pipeline stages: [(cmd, [args]), ...]."""
    tokens = shlex.split(line)
    if not tokens:
        return []

    stages = []
    current_cmd = None
    current_args = []

    for token in tokens:
        if token == "|":
            if current_cmd is None:
                raise ValueError("empty pipeline stage")
            stages.append((current_cmd, current_args))
            current_cmd = None
            current_args = []
        elif current_cmd is None:
            current_cmd = token
        else:
            current_args.append(token)

    if current_cmd is None:
        raise ValueError("empty pipeline stage")
    stages.append((current_cmd, current_args))
    return stages


# ---------------------------------------------------------------------------
# Pipeline executor
# ---------------------------------------------------------------------------

def _call_method(method, args, input_objects=None):
    """Call a varlink method via in-process service.handle() and return output objects."""
    interface = service.interfaces["sh.builtin"]
    method_def = interface.get_method(method)
    declared = method_def.in_type.fields

    params = {}
    if "args" in declared:
        params["args"] = args
    if "input" in declared and input_objects is not None:
        params["input"] = input_objects

    request = json.dumps({
        "method": f"sh.builtin.{method}",
        "more": True,
        "parameters": params,
    }).encode("utf-8")

    objects = []
    for reply_bytes in service.handle(request):
        reply = json.loads(reply_bytes)
        if "error" in reply:
            raise RuntimeError(f"{reply['error']}: {reply.get('parameters', {})}")
        params = reply.get("parameters", {})
        if params:
            # Unwrap methods that return a single "object" typed field
            if list(params.keys()) == ["object"]:
                params = params["object"]
            objects.append(params)
    return objects


def execute(line):
    """Parse and execute a pipeline, returning the list of output objects."""
    stages = parse(line)
    if not stages:
        return []

    objects = None
    for cmd, args in stages:
        method = cmd.capitalize()
        objects = _call_method(method, args, objects)
    return objects


# ---------------------------------------------------------------------------
# Pretty-printer
# ---------------------------------------------------------------------------

def pretty_print(objects):
    """Print objects as a table if keys are uniform, otherwise as JSON lines."""
    if not objects:
        return

    keys_list = [list(o.keys()) for o in objects]
    if all(k == keys_list[0] for k in keys_list):
        _print_table(objects, keys_list[0])
    else:
        for obj in objects:
            print(json.dumps(obj))


def _print_table(objects, keys):
    headers = [k.upper() for k in keys]
    rows = [[str(obj.get(k, "")) for k in keys] for obj in objects]

    widths = [
        max(len(h), *(len(r[i]) for r in rows))
        for i, h in enumerate(headers)
    ]

    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    separator = "  ".join("-" * w for w in widths)

    print(header_line)
    print(separator)
    for row in rows:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))
