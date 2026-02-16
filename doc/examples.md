# Varlink Shell Examples

A cookbook of practical examples organized by use case.

---

## File System

### Browse and filter

```
vsh> ls
vsh> ls /etc
vsh> ls | grep type=dir
vsh> ls | grep type=file
vsh> ls | grep type=file name=.py
```

### Count files vs directories

```
vsh> ls | grep type=file | count
vsh> ls | grep type=dir | count
```

### Select specific fields

```
vsh> ls | map name type
vsh> ls | map name
```

### Create labels from fields

```
vsh> ls | map label="{name} ({type})" size
vsh> ls | map entry="{name}: {size} bytes"
```

### Filter then reshape

```
vsh> ls | grep type=file | map name size
vsh> ls | grep type=file name=.py | map name
```

---

## GitHub API

All examples use `jsexec curl -s` to fetch JSON from the GitHub API.

### List repository issues

```
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | map number title state
```

### Filter by state

```
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=open
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=open | map number title
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=closed | count
```

### List a user's repositories

```
vsh> jsexec curl -s https://api.github.com/users/varlink/repos | map name description
vsh> jsexec curl -s https://api.github.com/users/varlink/repos | map name stargazers_count language
```

### Filter repos by language

```
vsh> jsexec curl -s https://api.github.com/users/varlink/repos | grep language=Python | map name
```

### User info

```
vsh> jsexec curl -s https://api.github.com/users/varlink | map login name public_repos
```

---

## System Information (Linux JSON tools)

Many Linux tools support JSON output with `-j` or `--json`.

### Network interfaces

```
vsh> jsexec ip -j link | map ifname operstate
vsh> jsexec ip -j link | grep operstate=UP | map ifname
vsh> jsexec ip -j addr | map ifname addr_info
```

### Block devices

```
vsh> jsexec lsblk -J | map name size type mountpoint
vsh> jsexec lsblk -J | grep type=disk | map name size
```

### Sockets

```
vsh> jsexec ss -tlnH --json | map src dst state
```

---

## Data Transformation

### Select fields (projection)

```
vsh> echo a=1 b=2 c=3 | map a c
A  C
-  -
1  3
```

### Rename fields

```
vsh> echo x=hello | map greeting={x}
GREETING
--------
hello
```

### String interpolation

```
vsh> echo first=Jane last=Doe | map full="{first} {last}"
FULL
--------
Jane Doe
```

### Type preservation through map

When JSON sources provide typed values, single `{field}` references preserve the type:

```
vsh> jsexec echo '[{"name":"a","count":42},{"name":"b","count":7}]' | map count
COUNT
-----
42
7
```

The `count` values remain integers, not strings.

### Drop objects with missing fields

```
vsh> jsexec echo '[{"x":1,"y":2},{"x":3}]' | filter_map x y
X  Y
-  -
1  2
```

The second object is dropped because it lacks `y`. With `map` instead of `filter_map`, it would be kept with `y` omitted.

### Chain transformations

```
vsh> ls | grep type=file | map name size | grep name=.py
```

---

## Bulk Operations with foreach

### Run a command per object

```
vsh> echo a=hello b=world | foreach echo greeting={a}
```

### Iterate over JSON array items

```
vsh> jsexec echo '[{"url":"https://example.com"},{"url":"https://varlink.org"}]' | foreach jsexec curl -s {url}
```

### Foreach with nested pipeline

Quote the whole pipeline to run it per object:

```
vsh> echo a=hello | foreach "echo x={a} | grep x=hello"
```

### Generate commands from data

```
vsh> jsexec echo '[{"name":"a"},{"name":"b"},{"name":"c"}]' | foreach echo file={name}.txt
```

---

## Systemd via Varlink

Query systemd services directly through their varlink sockets — no JSON parsing needed.

### Hostname and system info

```
vsh> varlink unix:/run/systemd/io.systemd.Hostname Describe
vsh> varlink unix:/run/systemd/io.systemd.Hostname Describe | map Hostname KernelRelease OperatingSystemPrettyName
```

### Introspect available methods

```
vsh> varlink unix:/run/systemd/io.systemd.Hostname
vsh> varlink unix:/run/systemd/io.systemd.Manager
```

### Fully-qualified method call

```
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List
```

### Piped parameters

```
vsh> echo name=sshd.service | varlink unix:/run/systemd/io.systemd.Manager Describe
```

### Resolve DNS names

```
vsh> varlink unix:/run/systemd/io.systemd.resolve ResolveHostname name=google.com family=2
```

### Nested objects with dotted paths

Systemd's varlink APIs return nested objects. Use dotted paths to reach into them:

```
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | where context.Type=service runtime.ActiveState=active | map context.ID context.Description | head 10
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | where context.Type=service | map id={context.ID} state={runtime.ActiveState} | head 5
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | map type={context.Type} | group type | sort -count
vsh> varlink unix:/run/systemd/io.systemd.Manager io.systemd.Unit.List | where context.Type=service | sort context.ID | map context.ID runtime.ActiveState
```

---

## Combining Patterns

### Count filtered results

```
vsh> ls | grep type=file | count
vsh> jsexec curl -s https://api.github.com/repos/varlink/python/issues | grep state=open | count
```

### Filter, project, and count

```
vsh> ls | grep type=file name=.py | map name | count
```

### External tool → filter → reshape

```
vsh> jsexec ip -j link | grep operstate=UP | map ifname mtu
```

### Multi-step data pipeline

```
vsh> jsexec curl -s https://api.github.com/users/varlink/repos | grep language=Python | map name stargazers_count | grep stargazers_count=0
```

---

## Sorting and Slicing

### Sort files by size (largest first)

```
vsh> ls | sort -size
vsh> ls | sort -size | head 5
```

### Sort by multiple fields

```
vsh> ls | sort type -size
```

### Reverse a listing

```
vsh> ls | reverse
vsh> ls | sort size | reverse
```

### First and last N items

```
vsh> ls | head 3
vsh> ls | sort size | tail 5
```

---

## Aggregation

### Sum file sizes

```
vsh> ls | sum size
vsh> ls | grep type=file | sum size
```

### Find largest and smallest files

```
vsh> ls | max size
vsh> ls | min size
vsh> ls | grep type=file | max size
```

### Group by type

```
vsh> ls | group type
vsh> ls | group type | sort -count
```

---

## Advanced Filtering with where

### Numeric comparisons

```
vsh> ls | where size>1000
vsh> ls | where size>=100 size<=10000
```

### Exact and negated match

```
vsh> ls | where type=file
vsh> ls | where type!=dir
```

### Regex match

```
vsh> ls | where name~"\.py$"
vsh> ls | where name~"^test"
```

### Combined conditions

```
vsh> ls | where type=file size>1000
```

---

## Deduplication and Numbering

### Remove duplicates by field

```
vsh> ls | uniq type
```

### Number results

```
vsh> ls | enumerate
vsh> ls | sort -size | enumerate
```

---

## Pipeline Composition

### Top 3 largest files

```
vsh> ls | grep type=file | sort -size | head 3
```

### File type distribution sorted by count

```
vsh> ls | group type | sort -count
```

### Numbered list of files over 1KB

```
vsh> ls | where type=file size>1000 | sort -size | enumerate
```

### Sum of file sizes (excluding directories)

```
vsh> ls | grep type=file | sum size
```
