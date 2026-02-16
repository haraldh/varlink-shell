import json
import os
import re
import shlex
import stat
import subprocess

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
# Field interpolation helpers
# ---------------------------------------------------------------------------

_FIELD_RE = re.compile(r"\{(\w+)\}")


def _parse_mappings(args):
    """Parse map args: bare 'name' -> ('name','{name}'), 'key=tmpl' -> ('key','tmpl')."""
    mappings = []
    for arg in args:
        if "=" in arg:
            key, tmpl = arg.split("=", 1)
            mappings.append((key, tmpl))
        else:
            mappings.append((arg, "{" + arg + "}"))
    return mappings


def _eval_template(tmpl, obj):
    """Evaluate template. Single {field} preserves raw type; mixed -> string."""
    m = _FIELD_RE.fullmatch(tmpl)
    if m:
        return obj.get(m.group(1))          # raw value or None (missing)
    has_ref = _FIELD_RE.search(tmpl)
    if not has_ref:
        return tmpl                          # literal string
    def repl(match):
        return str(obj.get(match.group(1), ""))
    return _FIELD_RE.sub(repl, tmpl)


def _template_fields(tmpl):
    """Return set of field names referenced in template."""
    return set(_FIELD_RE.findall(tmpl))


def _method_name(cmd):
    """Convert command name to method name: 'filter_map' -> 'FilterMap'."""
    return "".join(part.capitalize() for part in cmd.split("_"))


def _command_name(method_name):
    """Convert method name to command name: 'FilterMap' -> 'filter_map'."""
    parts = re.findall(r'[A-Z][a-z]*', method_name)
    return "_".join(p.lower() for p in parts)


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

    def Grep(self, args, input=None, _more=True):
        filters = []
        for arg in args:
            if "=" not in arg:
                raise varlink.VarlinkError({
                    "error": "org.varlink.service.InvalidParameter",
                    "parameters": {"parameter": arg},
                })
            k, v = arg.split("=", 1)
            filters.append((k, v))

        matches = []
        if input:
            for obj in input:
                if all(pattern in str(obj.get(field, "")) for field, pattern in filters):
                    matches.append(obj)

        for i, obj in enumerate(matches):
            yield {"object": obj, "_continues": i < len(matches) - 1}

        if not matches:
            return

    def Count(self, input=None, _more=True):
        count = len(input) if input else 0
        yield {"count": count, "_continues": False}

    def Help(self, command=None, _more=True):
        interface = service.interfaces["sh.builtin"]

        if command:
            member = interface.get_method(_method_name(command))
            doc = member.doc.strip() if member.doc else ""
            lines = doc.split("\n")
            for i, line in enumerate(lines):
                yield {
                    "command": command.lower() if i == 0 else "",
                    "description": line,
                    "_continues": i < len(lines) - 1,
                }
        else:
            methods = [
                (_command_name(name), member.doc.strip().split("\n\n", 1)[0]
                 if member.doc else "")
                for name, member in interface.members.items()
                if isinstance(member, _Method)
            ]
            for i, (cmd, doc) in enumerate(methods):
                yield {
                    "command": cmd, "description": doc,
                    "_continues": i < len(methods) - 1,
                }

    def Jsexec(self, args, _more=True):
        if not args:
            raise varlink.VarlinkError({
                "error": "org.varlink.service.InvalidParameter",
                "parameters": {"parameter": "args"},
            })

        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise varlink.VarlinkError({
                "error": "sh.builtin.ExecFailed",
                "parameters": {
                    "command": args[0],
                    "exitcode": result.returncode,
                    "message": stderr,
                },
            })

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise varlink.VarlinkError({
                "error": "sh.builtin.InvalidJson",
                "parameters": {"message": str(e)},
            })

        # Auto-unwrap: single-key dict whose value is a list
        if isinstance(data, dict) and len(data) == 1:
            only_value = next(iter(data.values()))
            if isinstance(only_value, list):
                data = only_value

        if not isinstance(data, list):
            data = [data]

        objects = []
        for item in data:
            if not isinstance(item, dict):
                item = {"value": item}
            objects.append(item)

        for i, obj in enumerate(objects):
            yield {"object": obj, "_continues": i < len(objects) - 1}

    def Map(self, args, input=None, _more=True):
        if not args:
            raise varlink.VarlinkError({
                "error": "org.varlink.service.InvalidParameter",
                "parameters": {"parameter": "args"},
            })
        mappings = _parse_mappings(args)
        results = []
        if input:
            for obj in input:
                mapped = {}
                for key, tmpl in mappings:
                    val = _eval_template(tmpl, obj)
                    if val is not None:
                        mapped[key] = val
                results.append(mapped)
        for i, obj in enumerate(results):
            yield {"object": obj, "_continues": i < len(results) - 1}
        if not results:
            return

    def FilterMap(self, args, input=None, _more=True):
        if not args:
            raise varlink.VarlinkError({
                "error": "org.varlink.service.InvalidParameter",
                "parameters": {"parameter": "args"},
            })
        mappings = _parse_mappings(args)
        required = set()
        for _, tmpl in mappings:
            required |= _template_fields(tmpl)
        results = []
        if input:
            for obj in input:
                if not required.issubset(obj.keys()):
                    continue
                mapped = {}
                for key, tmpl in mappings:
                    mapped[key] = _eval_template(tmpl, obj)
                results.append(mapped)
        for i, obj in enumerate(results):
            yield {"object": obj, "_continues": i < len(results) - 1}
        if not results:
            return

    def Foreach(self, args, input=None, _more=True):
        if not args:
            raise varlink.VarlinkError({
                "error": "org.varlink.service.InvalidParameter",
                "parameters": {"parameter": "args"},
            })
        template = " ".join(args)
        all_results = []
        if input:
            for obj in input:
                line = _FIELD_RE.sub(
                    lambda m: shlex.quote(str(obj.get(m.group(1), ""))), template)
                all_results.extend(execute(line))
        for i, obj in enumerate(all_results):
            yield {"object": obj, "_continues": i < len(all_results) - 1}
        if not all_results:
            return


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
    elif args:
        # Map positional CLI args to declared parameters (excluding "input")
        positional = [name for name in declared if name != "input"]
        for name, value in zip(positional, args):
            params[name] = value
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
        method = _method_name(cmd)
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
