# Varlink Shell User Guide

## Getting Started

### Prerequisites

- Python 3.9+
- The `varlink` Python package

### Installation

The easiest way to get a working environment is via Nix:

```bash
nix develop
```

This creates a virtualenv with Python 3.14, installs `varlink`, `pytest`, and other dev tools, then activates it.

Without Nix, install manually:

```bash
pip install varlink
```

### Running the shell

```bash
python -m varlink_shell
```

You'll see the `vsh>` prompt. Type commands and press Enter. Use `exit` or Ctrl-D to quit. Ctrl-C also exits cleanly. Readline line-editing and history are available.

Errors are printed to stderr and don't crash the shell — you can keep working after a mistake.

```
vsh> nonexistent
error: org.varlink.service.MethodNotFound: {'method': 'Nonexistent'}
vsh> ls
NAME   TYPE  SIZE
-----  ----  ----
...
```

---

## Core Concepts

### Object streams

Every command produces a list of **typed objects** — Python dicts with named fields. This is fundamentally different from traditional shells where everything is text. An `ls` produces objects like `{"name": "foo.py", "type": "file", "size": 1234}`, not a line of whitespace-separated text.

Values are typed: strings, integers, floats, and booleans are all preserved through the pipeline (not flattened to text).

### Pipelines

Commands are connected with `|`. The output objects of one command become the input of the next:

```
vsh> ls | grep type=file | count
```

This is three stages: `ls` produces directory entries, `grep` filters to files, `count` tallies them. Each stage runs to completion before the next begins.

### Table display

When all output objects share the same keys (in the same order), the shell renders them as an aligned table with uppercase headers:

```
vsh> ls
NAME        TYPE  SIZE
----------  ----  ----
flake.nix   file  820
tests       dir   4096
```

When objects have different keys, each one is printed as a single JSON line:

```
{"name": "foo", "type": "file", "size": 100}
{"error": "permission denied"}
```

### Types

Values flowing through pipelines can be:

- **string** — `"hello"`, `"42"` (note: `echo count=42` produces the string `"42"`)
- **int** — `42` (preserved from JSON sources like `jsexec`)
- **float** — `3.14`
- **bool** — `True`, `False` (bare `echo` args produce `True`)

Type matters for `map`: a single `{field}` reference preserves the original type, while string interpolation converts everything to strings.

---

## Builtin Commands

### echo

Create objects from key=value pairs, or pass piped input through unchanged.

**Syntax:** `echo [key=value ...] [flag ...]`

```
vsh> echo name=alice age=30
NAME   AGE
-----  ---
alice  30

vsh> echo verbose
VERBOSE
-------
True
```

Key=value pairs become string fields. Bare arguments become boolean `True` fields.

When used in a pipeline, `echo` passes input objects through unchanged (ignoring any args):

```
vsh> ls | echo | count
COUNT
-----
5
```

### ls

List directory entries with name, type, and size.

**Syntax:** `ls [path]`

```
vsh> ls
NAME          TYPE  SIZE
------------  ----  ----
flake.nix     file  820
tests         dir   4096
varlink_shell dir   4096

vsh> ls /tmp
```

Each entry has three fields:
- `name` — file/directory name
- `type` — `file`, `dir`, or `link`
- `size` — size in bytes

Entries are sorted alphabetically. Entries that can't be stat'd are silently skipped.

### count

Count the number of input objects.

**Syntax:** `count`

```
vsh> ls | count
COUNT
-----
12

vsh> ls | grep type=dir | count
COUNT
-----
3

vsh> count
COUNT
-----
0
```

With no input, returns `{"count": 0}`.

### grep

Filter input objects by substring match on field values.

**Syntax:** `grep field=pattern [field=pattern ...]`

```
vsh> ls | grep type=file
vsh> ls | grep type=file name=.py
```

Each argument must be `field=pattern`. The pattern is matched as a substring against `str(value)`. Multiple filters use AND logic — all must match for an object to pass through.

```
vsh> ls | grep type=file name=.txt
```

This keeps only objects where `type` contains `"file"` AND `name` contains `".txt"`.

Returns empty output if nothing matches. Raises an error if an argument doesn't contain `=`.

### help

List all commands or get help for a specific one.

**Syntax:** `help [command]`

Without arguments, shows a concise listing with one-line summaries:

```
vsh> help
COMMAND     DESCRIPTION
----------  -------------------------------------------------------
echo        Emit key=value pairs as an object, or pass through piped input
ls          List directory entries
count       Consume input objects and emit their count
...
```

With a command name, shows the full documentation including detailed description and examples:

```
vsh> help grep
COMMAND  DESCRIPTION
-------  ---------------------------------------------------
grep     Filter input objects by matching field values

         Each argument must be field=pattern.  The pattern is
         matched as a substring against str(value) of the named
         field.  Multiple filters use AND logic -- all must match
         for an object to pass through.  Returns empty output if
         nothing matches.

         Examples:
           ls | grep type=file
           ls | grep type=file name=.py
```

Help text comes from the `#` documentation comments in the varlink interface definition.

### jsexec

Execute an external command and parse its JSON stdout into objects.

**Syntax:** `jsexec command [args ...]`

```
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues
```

This is the primary bridge to external tools. The command is run as a subprocess, its stdout is parsed as JSON, and the result is converted to a stream of objects.

**JSON conversion rules:**

| JSON output | Result |
|---|---|
| `{"a": 1, "b": 2}` | Single object `[{"a": 1, "b": 2}]` |
| `[{"x": 1}, {"x": 2}]` | Two objects as-is |
| `{"items": [{"n": 1}]}` | Auto-unwrap: `[{"n": 1}]` (single-key dict with list value) |
| `[1, "hello"]` | Wrapped: `[{"value": 1}, {"value": "hello"}]` |
| `{"a": [1], "b": [2]}` | Single object (multi-key dict, no unwrap) |

**Auto-unwrap**: Many APIs return `{"results": [...]}` or `{"data": [...]}`. When the JSON output is a dict with exactly one key whose value is a list, the list is extracted automatically.

**Non-dict primitives** in arrays are wrapped as `{"value": item}`.

**Errors:**

- No arguments: `InvalidParameter`
- Non-zero exit code: `ExecFailed` with command name, exit code, and stderr
- Invalid JSON output: `InvalidJson`

```
vsh> jsexec false
error: sh.builtin.ExecFailed: {'command': 'false', 'exitcode': 1, 'message': ''}

vsh> jsexec echo "not json"
error: sh.builtin.InvalidJson: {'message': 'Expecting value: line 1 column 1 (char 0)'}
```

### map

Transform objects by selecting, renaming, or interpolating fields.

**Syntax:** `map field [key=template ...]`

Three forms of mapping arguments:

| Form | Meaning | Example |
|---|---|---|
| `field` | Select field, keep name | `map name size` |
| `key={field}` | Rename field | `map label={name}` |
| `key="{a} and {b}"` | String interpolation | `map desc="{name} ({type})"` |

```
vsh> ls | map name type
NAME        TYPE
----------  ----
flake.nix   file
tests       dir

vsh> ls | map label="{name} ({type})" size
LABEL              SIZE
-----------------  ----
flake.nix (file)   820
tests (dir)        4096
```

**Type preservation:** A single `{field}` reference preserves the original type (int stays int). String interpolation with literals or multiple fields always produces a string.

**Missing fields:** If a field referenced by a mapping doesn't exist in the input object, that key is omitted from the output (the object is still emitted, just without that key).

```
vsh> echo a=1 | map a b
A
-
1
```

Here `b` is missing, so the output object only has `a`.

### filter_map

Like `map`, but drops objects entirely when any referenced field is missing.

**Syntax:** `filter_map field [key=template ...]`

```
vsh> echo a=1 b=2 | filter_map a b
A  B
-  -
1  2

vsh> echo a=1 | filter_map a b
(no output — object dropped because b is missing)
```

This is useful when you know some objects won't have the fields you need and you want to silently skip them rather than getting incomplete rows.

### foreach

Run a command for each input object, substituting `{field}` references with values from that object.

**Syntax:** `foreach command [args with {field} refs ...]`

```
vsh> echo a=hello | foreach echo x={a}
X
-----
hello
```

For each input object, `{field}` placeholders in the command template are replaced with the object's field values (shell-escaped for safety), and the resulting command line is executed as a full pipeline.

```
vsh> echo a=hello | foreach "echo x={a} | grep x=hello"
```

Foreach can run any pipeline per object, including nested pipelines with `|` (quote the whole thing).

Missing fields are substituted as empty strings.

### sort

Sort input objects by one or more fields.

**Syntax:** `sort [field ...] [-field ...]`

```
vsh> ls | sort name
vsh> ls | sort -size
vsh> ls | sort type -size
```

Prefix a field name with `-` for descending order. Numeric values are compared numerically. Multiple fields create a multi-key sort (first field is primary, second is tiebreaker, etc.).

### head

Take the first N input objects.

**Syntax:** `head [N]`

```
vsh> ls | head
vsh> ls | head 5
vsh> ls | sort -size | head 3
```

Default is 10 when no argument is given.

### tail

Take the last N input objects.

**Syntax:** `tail [N]`

```
vsh> ls | tail
vsh> ls | tail 5
vsh> ls | sort size | tail 3
```

Default is 10 when no argument is given.

### uniq

Remove duplicate objects.

**Syntax:** `uniq [field ...]`

```
vsh> ls | uniq type
vsh> ls | map type | uniq type
```

With field arguments, uniqueness is determined by the values of those fields only. Without arguments, the entire object is compared. Preserves the first occurrence.

### reverse

Reverse the order of input objects.

**Syntax:** `reverse`

```
vsh> ls | reverse
vsh> ls | sort size | reverse
```

Takes no arguments.

### sum

Sum a numeric field across all input objects.

**Syntax:** `sum field`

```
vsh> ls | sum size
vsh> ls | grep type=file | sum size
```

Requires exactly one field name. Non-numeric or missing values are treated as 0. Emits a single object with `{"sum": total}`.

### min

Find the object with the smallest value for a field.

**Syntax:** `min field`

```
vsh> ls | min size
vsh> ls | grep type=file | min size
```

Returns the full input object that has the smallest value for the given field. With empty input, returns nothing.

### max

Find the object with the largest value for a field.

**Syntax:** `max field`

```
vsh> ls | max size
vsh> ls | grep type=file | max size
```

Returns the full input object that has the largest value for the given field. With empty input, returns nothing.

### where

Filter objects using comparison operators.

**Syntax:** `where condition [condition ...]`

Supported operators:

| Operator | Meaning | Example |
|---|---|---|
| `=` | Exact string match | `where type=file` |
| `!=` | Not equal | `where type!=dir` |
| `>` | Greater than | `where size>1000` |
| `<` | Less than | `where size<100` |
| `>=` | Greater or equal | `where size>=100` |
| `<=` | Less or equal | `where size<=1000` |
| `~` | Regex match | `where name~"\.py$"` |

```
vsh> ls | where size>1000
vsh> ls | where type=file size>=100
vsh> ls | where name~"\.py$"
```

Numeric comparisons are used when both sides are numeric; otherwise string comparison applies. Multiple conditions use AND logic.

### group

Group objects by a field and count occurrences.

**Syntax:** `group field`

```
vsh> ls | group type
TYPE  COUNT
----  -----
file  8
dir   3

vsh> ls | group type | sort -count
```

Requires exactly one field name. Emits one object per group with the field value and a `count` field.

### enumerate

Add a zero-based index field to each object.

**Syntax:** `enumerate`

```
vsh> ls | enumerate
INDEX  NAME        TYPE  SIZE
-----  ----------  ----  ----
0      flake.nix   file  820
1      tests       dir   4096

vsh> ls | sort -size | enumerate
```

Takes no arguments.

### print

Pretty-print input objects as a table and pass them through.

**Syntax:** `print`

```
vsh> ls | sort -size | print
vsh> ls | print | count
```

In interactive mode, the shell always pretty-prints the final result, so `print` is most useful mid-pipeline to inspect intermediate values.

In non-interactive mode (piped stdin), the shell outputs JSON by default — one object per line. Ending a pipeline with `| print` switches to table output instead:

```bash
echo 'ls /tmp' | python -m varlink_shell              # JSON lines
echo 'ls /tmp | print' | python -m varlink_shell       # table
```

### varlink

Connect to an external varlink service and call methods.

**Syntax:** `varlink address [method] [key=value ...]`

The first argument is a varlink address (`unix:/path` or `tcp:host:port`).

**Introspect mode** — list all methods on a service:

```
vsh> varlink unix:/run/systemd/io.systemd.Hostname
INTERFACE              METHOD    SIGNATURE
---------------------  --------  -----------------------------------------
io.systemd.Hostname    Describe  () -> (Hostname: string, ...)
```

**Call mode** — invoke a method and stream results as objects:

```
vsh> varlink unix:/run/systemd/io.systemd.Hostname Describe
HOSTNAME      KERNELRELEASE  ...
------------  -------------  ---
my-machine    6.12.69        ...

vsh> varlink unix:/run/systemd/io.systemd.Hostname Describe | map Hostname
HOSTNAME
--------
my-machine
```

**Parameters** — pass as key=value with smart type coercion (42→int, true→bool, JSON objects detected automatically):

```
vsh> varlink unix:/run/systemd/io.systemd.resolve ResolveHostname name=google.com family=2
```

**Fully-qualified method names** — specify the interface explicitly:

```
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List
```

**Piped input** — when no key=value args are given, each input object is used as call parameters:

```
vsh> echo name=sshd.service | varlink unix:/run/systemd/io.systemd.Manager Describe
```

**Auto-discovery:** Unqualified method names (like `Describe`) are resolved by introspecting all interfaces on the service. If the method name is ambiguous (exists in multiple interfaces), an error is raised.

**Errors:**

- `VarlinkConnectionFailed` — cannot connect to the address
- `VarlinkCallFailed` — the remote method returned an error
- `VarlinkMethodNotFound` — the method doesn't exist on any interface

---

## Field Templates

The `{field}` template syntax is used by `map`, `filter_map`, and `foreach`.

### Syntax

`{field}` references a field name from the input object. Field names are `\w+` (letters, digits, underscores). **Dotted paths** like `{context.ID}` traverse nested objects — `{a.b.c}` resolves to `obj["a"]["b"]["c"]`.

### Type behavior

| Template | Type of result | Example |
|---|---|---|
| `{field}` (entire value) | Original type preserved | `{count}` → `42` (int) |
| `prefix{field}` | String | `item_{id}` → `"item_42"` |
| `{a}...{b}` | String | `{name}: {age}` → `"bob: 30"` |
| `literal` (no refs) | String | `hello` → `"hello"` |

### Missing field behavior

| Command | Missing field behavior |
|---|---|
| `map` | Key omitted from output, object still emitted |
| `filter_map` | Entire object dropped |
| `foreach` | Replaced with empty string |

### Nested objects (dotted paths)

Dotted paths work everywhere a field name is accepted: `map`, `where`, `grep`, `sort`, `group`, `sum`, `min`, `max`, `uniq`, and `foreach`.

```
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | where context.Type=service runtime.ActiveState=active | map context.ID context.Description | head 5
```

In `map`, a bare dotted path like `context.ID` becomes the output key `context.ID`. Use renaming to flatten:

```
vsh> ... | map id={context.ID} state={runtime.ActiveState}
```

String interpolation also works with dotted paths:

```
vsh> ... | map label="{context.ID} ({runtime.ActiveState})"
```

---

## Real-World Examples with jsexec

### GitHub API

List open issues with selected fields:

```
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=open | map number title
```

Count closed issues:

```
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=closed | count
```

### JSON-outputting system tools

Many Linux tools support JSON output:

```
vsh> jsexec ip -j link | map ifname operstate
IFNAME  OPERSTATE
------  ---------
lo      UNKNOWN
eth0    UP

vsh> jsexec ip -j link | grep operstate=UP | map ifname

vsh> jsexec lsblk -J | map name size type

vsh> jsexec ss -tljnH --json | map src dst state
```

### Chaining with foreach

Fetch data for each object:

```
vsh> jsexec curl -s https://api.github.com/users/varlink/repos | map name | foreach jsexec curl -s https://api.github.com/repos/varlink/{name}
```

---

## Architecture

### Built on varlink

The shell is built on the [varlink](https://varlink.org) protocol. Every builtin command is a varlink method defined in `sh.builtin.varlink`:

```
interface sh.builtin

method Echo(args: []string, input: ?[]object) -> (object: object)
method Ls(args: []string) -> (name: string, type: string, size: int)
method Count(input: ?[]object) -> (count: int)
...
```

This makes the command set typed, self-documenting, and introspectable. The `help` command reads documentation directly from the interface definition.

### In-process execution

Commands are not separate processes. The shell runs a varlink `Service` in-process and calls methods via `service.handle()`, which takes a JSON request and returns JSON replies — the same wire format used over sockets, but without the network.

### Streaming protocol

All methods use varlink's streaming mode (`more: true` in the request). The server yields multiple replies with `continues: true`, ending with `continues: false` (or no `continues` field) on the last reply. This is how `ls` can emit one object per directory entry.

### Pipeline execution

Pipelines are processed strictly left to right. Each stage runs to completion, collecting all output objects, before the next stage begins with those objects as input. This is simple but means the entire intermediate result is held in memory.
