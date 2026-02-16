# varlink shell

An object-oriented shell built on the [varlink](https://varlink.org) protocol. Commands produce and consume typed objects — not text — connected by pipelines.

## Quick start

```bash
nix develop
python -m varlink_shell
```

```
vsh> ls
NAME        TYPE  SIZE
----------  ----  ----
flake.nix   file  820
tests       dir   4096
varlink_shell  dir   4096

vsh> ls | grep type=file | count
COUNT
-----
3

vsh> help
COMMAND      DESCRIPTION
-----------  -----------
echo         Emit key=value pairs as an object, or pass through piped input
ls           List directory entries
count        Consume input objects and emit their count
grep         Filter input objects by matching field values
help         Show available commands and their descriptions
jsexec       Execute an external command and parse its JSON output as objects
map          Transform input objects by selecting, renaming, or interpolating fields
filter_map   Like map, but drop objects where any referenced field is missing
foreach      Run a command for each input object with {field} substitution
sort         Sort input objects by one or more fields
head         Take the first N input objects
tail         Take the last N input objects
uniq         Remove duplicate objects
reverse      Reverse the order of input objects
sum          Sum a numeric field across all input objects
min          Find the object with the smallest value for a field
max          Find the object with the largest value for a field
where        Filter objects using comparison operators
group        Group objects by a field and count occurrences
enumerate    Add a zero-based index field to each object
print        Pretty-print input objects as a table and pass them through
varlink      Connect to an external varlink service and call methods
```

## Core idea

Every command returns a stream of typed objects (dicts with known fields). Pipelines (`|`) pass objects between commands. When output objects share the same keys, the shell renders them as an aligned table; otherwise it prints one JSON object per line.

## Examples

Filter directory listings:

```
vsh> ls | grep type=file name=.py | map name size
```

Pull JSON from external tools and work with it as objects:

```
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | map number title state
NUMBER  TITLE                       STATE
------  --------------------------  ------
42      Support Python 3.14         open
38      Add type stubs              closed

vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=open | count
COUNT
-----
5
```

Reshape objects with `map` and string interpolation:

```
vsh> ls | map label="{name} ({type})" size
```

Run a command per object with `foreach`:

```
vsh> ls | grep type=file | foreach echo file={name}
```

Work with nested objects using dotted paths (e.g. systemd varlink APIs):

```
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | where context.Type=service runtime.ActiveState=active | map context.ID context.Description | head 10
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | map type={context.Type} | group type | sort -count
```

## Commands

| Command | Description |
|---|---|
| `echo` | Emit key=value pairs as an object, or pass through piped input |
| `ls` | List directory entries (name, type, size) |
| `count` | Count input objects |
| `grep` | Filter by field=pattern substring match (AND logic) |
| `help` | List commands or describe a specific one |
| `jsexec` | Run external command, parse JSON stdout into objects |
| `map` | Select, rename, or interpolate fields (missing fields omitted) |
| `filter_map` | Like map, but drop objects where any referenced field is missing |
| `foreach` | Run a command for each input object with `{field}` substitution |
| `sort` | Sort input objects by one or more fields |
| `head` | Take the first N input objects (default 10) |
| `tail` | Take the last N input objects (default 10) |
| `uniq` | Remove duplicate objects (by field or whole object) |
| `reverse` | Reverse the order of input objects |
| `sum` | Sum a numeric field across all input objects |
| `min` | Find the object with the smallest value for a field |
| `max` | Find the object with the largest value for a field |
| `where` | Filter objects using comparison operators (`=`, `!=`, `>`, `<`, `>=`, `<=`, `~`) |
| `group` | Group objects by a field and count occurrences |
| `enumerate` | Add a zero-based index field to each object |
| `print` | Pretty-print input objects as a table and pass them through |
| `varlink` | Connect to an external varlink service and call methods |

## Documentation

See [doc/guide.md](doc/guide.md) for the full user guide and [doc/examples.md](doc/examples.md) for a cookbook of practical examples.

## Tests

```bash
pytest tests/
```
