# Varlink Protocol & Python Library Reference

## Protocol Overview

Varlink is a plain-text, type-safe, discoverable, self-documenting interface description format and protocol. All messages are JSON objects terminated by a single NUL byte (`\0`). Services are point-to-point over connection-oriented transports (Unix sockets, TCP, etc.). No multiplexing — requests are processed strictly in order per connection, though pipelining is supported.

Key design principles: simplicity over performance, discoverability (services describe themselves), remotability (no local side-effects like file descriptors), and testability.

---

## Interface Definition Language (IDL)

Interface files use `.varlink` suffix and reverse-domain naming.

### Type System

| Varlink Type | Python Type | Description |
|---|---|---|
| `bool` | `bool` | Boolean |
| `int` | `int` | Signed integer (usually 64-bit) |
| `float` | `float` | IEEE754 floating point |
| `string` | `str` | Text |
| `object` | `dict` | Untyped/foreign object (passed through as-is) |
| `[]T` | `list` | Array of T |
| `[string]T` | `dict` | String-keyed map |
| `[string]()` | `set` | Set (string-keyed empty-value map) |
| `?T` | `None` or T | Nullable/optional |
| `(field: T, ...)` | `dict` or `SimpleNamespace` | Struct/record |
| `(val1, val2, ...)` | `str` | Enum (serialized as JSON string) |

### IDL Syntax

```
# Comments start with #

interface org.example.myservice

type MyRecord (
  name: string,
  count: int,
  tags: []string,
  metadata: ?[string]string,
  state: (active, inactive, pending)
)

method DoSomething(input: MyRecord) -> (result: string, items: []MyRecord)

error ActionFailed (reason: string)
error NotFound ()
```

**Naming rules:**
- Interface names: reverse-domain (`org.example.service`)
- Types/methods/errors: uppercase first letter, alphanumeric
- Fields: lowercase first letter, alphanumeric, underscores allowed in middle

### Documentation Comments

`#` comments preceding a member (method, type, error) or the interface itself are captured as documentation strings by the parser and stored in the `.doc` attribute of the corresponding object.

```
# The main management interface
interface org.example.myservice

# A record describing an item
type Item (name: string, value: int)

# Look up an item by its identifier
method GetItem(id: int) -> (item: Item)

# Raised when the requested item does not exist
error NotFound (id: int)
```

Comments accumulate: multiple consecutive `#` lines before a member are joined with newlines into a single doc string. Comments not immediately preceding a member attach to whatever member the scanner encounters next.

---

## Wire Protocol

### Call Object (client → server)

```json
{
  "method": "org.example.myservice.DoSomething",
  "parameters": {"input": {"name": "foo", "count": 1, "tags": [], "state": "active"}},
  "oneway": false,
  "more": false,
  "upgrade": false
}
```

- `method` (required): fully-qualified `interface.Method`
- `parameters`: input object (omit if method takes no args). **Must only contain fields declared in the method's input type** — the server rejects unknown fields with `org.varlink.service.InvalidParameter`
- `oneway`: suppress reply
- `more`: request streaming (multiple replies)
- `upgrade`: switch to custom protocol after reply

### Reply Object (server → client)

```json
{"parameters": {"result": "ok", "items": []}}
```

Error reply:
```json
{"error": "org.example.myservice.ActionFailed", "parameters": {"reason": "disk full"}}
```

Streaming reply (`more=true` was set):
```json
{"parameters": {"item": "a"}, "continues": true}
{"parameters": {"item": "b"}, "continues": true}
{"parameters": {"item": "c"}, "continues": false}
```

---

## Service Discovery (org.varlink.service)

Every varlink service implements this built-in interface:

```
interface org.varlink.service

method GetInfo() -> (
  vendor: string, product: string, version: string,
  url: string, interfaces: []string
)
method GetInterfaceDescription(interface: string) -> (description: string)

error InterfaceNotFound (interface: string)
error MethodNotFound (method: string)
error MethodNotImplemented (method: string)
error InvalidParameter (parameter: string)
error PermissionDenied ()
error ExpectedMore ()
```

---

## Address Formats

| Transport | Format | Example |
|---|---|---|
| Unix socket | `unix:/path/to/socket` | `unix:/run/org.example.service` |
| Unix abstract | `unix:@name` | `unix:@org.example.service` |
| Unix with mode | `unix:/path;mode=0660` | `unix:/run/svc;mode=0660` |
| TCP | `tcp:host:port` | `tcp:127.0.0.1:12345` |
| TCP IPv6 | `tcp:[::1]:port` | `tcp:[::1]:12345` |

---

## Python Library (`varlink`)

**Install:** `pip install varlink`
**Python:** >= 3.9, zero external dependencies

### Public API

```python
import varlink

# Core classes
varlink.Service          # Server-side service handler
varlink.RequestHandler   # TCP/Unix request handler (subclass of StreamRequestHandler)
varlink.Server           # Single-connection server
varlink.ThreadingServer  # Multi-threaded server
varlink.ForkingServer    # Multi-process server (Unix only)

varlink.Client                        # Client connection manager
varlink.ClientInterfaceHandler        # Base client handler (abstract)
varlink.SimpleClientInterfaceHandler  # Socket/stream client handler

varlink.Interface   # Parsed .varlink interface
varlink.Scanner     # IDL parser

varlink.VarlinkError       # Base exception
varlink.InterfaceNotFound  # org.varlink.service.InterfaceNotFound
varlink.MethodNotFound     # org.varlink.service.MethodNotFound
varlink.MethodNotImplemented
varlink.InvalidParameter

varlink.VarlinkEncoder  # JSON encoder (handles set, SimpleNamespace, VarlinkError)
varlink.get_listen_fd() # systemd socket activation helper
```

---

### Creating a Server

**Step 1:** Write the `.varlink` interface file (e.g., `org.example.echo.varlink`):
```
interface org.example.echo

method Echo(message: string) -> (reply: string)
method Monitor() -> (status: string)

error EmptyMessage ()
```

**Step 2:** Implement in Python:
```python
import varlink
import os

service = varlink.Service(
    vendor='Example',
    product='Echo',
    version='1.0',
    url='https://example.org',
    interface_dir=os.path.dirname(__file__),  # directory containing .varlink files
    namespaced=False,           # False=dicts, True=SimpleNamespace
    json_encoder_cls=None,      # optional custom JSON encoder
)

class EchoRequestHandler(varlink.RequestHandler):
    service = service  # required class variable

@service.interface('org.example.echo')  # filename without .varlink suffix
class EchoImpl:
    def Echo(self, message):
        if not message:
            raise varlink.VarlinkError({
                "error": "org.example.echo.EmptyMessage",
                "parameters": {}
            })
        return {"reply": message}

    def Monitor(self, _more=True):
        # Streaming: yield multiple results
        yield {"status": "starting", "_continues": True}
        yield {"status": "running", "_continues": True}
        yield {"status": "done", "_continues": False}  # or just omit _continues

server = varlink.ThreadingServer("unix:@echo", EchoRequestHandler)
server.serve_forever()
```

**Special handler method parameters:**

| Parameter | Type | Purpose |
|---|---|---|
| `_more` | `bool` | Streaming mode — method becomes a generator yielding dicts with `_continues` |
| `_oneway` | `bool` | One-way call (no reply expected) |
| `_upgrade` | `bool` | Protocol upgrade requested |
| `_raw` | `bytes` | Raw UTF-8 message bytes |
| `_message` | `dict` | Parsed JSON message |
| `_interface` | `Interface` | Interface definition object |
| `_method` | method def | Method definition from IDL |
| `_server` | `Server` | Server instance |
| `_request` | socket | Client socket |

**Socket activation (systemd):**
```python
listen_fd = varlink.get_listen_fd()
if listen_fd is not None:
    server = varlink.Server(listen_fd, EchoRequestHandler)
else:
    server = varlink.ThreadingServer("unix:@echo", EchoRequestHandler)
server.serve_forever()
```

The `get_listen_fd()` function checks `LISTEN_FDS`, `LISTEN_PID`, and `LISTEN_FDNAMES` env vars and returns the fd named "varlink", or falls back to fd 3 if a single fd is passed.

---

### Creating a Client

**Direct connection:**
```python
with varlink.Client.new_with_address("unix:@echo") as client:
    with client.open("org.example.echo") as con:
        result = con.Echo(message="hello")
        # result is dict: {"reply": "hello"}
        # or SimpleNamespace if namespaced=True
```

**With service resolver:**
```python
with varlink.Client.new_with_resolved_interface("org.example.echo") as client:
    with client.open("org.example.echo") as con:
        result = con.Echo(message="hello")
```

**Socket activation (exec on demand):**
```python
with varlink.Client.new_with_activate(
    ["python3", "server.py", "--varlink=$VARLINK_ADDRESS"]
) as client:
    with client.open("org.example.echo") as con:
        result = con.Echo(message="hello")
```

**Bridge mode (SSH tunnel, etc.):**
```python
with varlink.Client.new_with_bridge(
    ["ssh", "remote-host", "varlink", "bridge"]
) as client:
    with client.open("org.example.echo") as con:
        result = con.Echo(message="hello")
```

**Streaming (monitoring):**
```python
with varlink.Client.new_with_address("unix:@echo") as client:
    with client.open("org.example.echo") as con:
        for status in con.Monitor(_more=True):
            print(status)  # {"status": "starting"}, {"status": "running"}, ...
```

**One-way call:**
```python
con.SomeMethod(param="value", _oneway=True)  # returns None immediately
```

**Introspection:**
```python
with varlink.Client.new_with_address("unix:@echo") as client:
    interfaces = client.get_interfaces()          # list of interface names
    iface = client.get_interface("org.example.echo")  # Interface object
    print(iface.get_description())                # .varlink text
```

**Namespaced mode** (attribute access instead of dict keys):
```python
with client.open("org.example.echo", namespaced=True) as con:
    result = con.Echo(message="hello")
    print(result.reply)  # "hello" — attribute access
```

---

### Error Handling

**Standard errors** (raised automatically by the library):
```python
try:
    con.NonExistent()
except varlink.MethodNotFound as e:
    print(e.error())       # "org.varlink.service.MethodNotFound"
    print(e.parameters())  # {"method": "NonExistent"}
```

**Custom errors — server side:**
```python
class ActionFailed(varlink.VarlinkError):
    def __init__(self, reason):
        super().__init__({
            "error": "org.example.ActionFailed",
            "parameters": {"reason": reason},
        })

# In a handler method:
raise ActionFailed("disk full")
```

**Custom errors — client side:**
```python
try:
    con.DoAction()
except varlink.VarlinkError as e:
    print(e.error())       # "org.example.ActionFailed"
    print(e.parameters())  # {"reason": "disk full"}
    # or with namespaced=True:
    print(e.parameters(namespaced=True).reason)
```

---

### Interface Parsing & Introspection

```python
description = """
interface org.example.test

# A record describing an item
type Item (name: string, value: int)

# Look up an item by its identifier
method GetItem(id: int) -> (item: Item)

# Raised when the requested item does not exist
error NotFound (id: int)
"""

iface = varlink.Interface(description)
print(iface.name)                # "org.example.test"
print(iface.doc)                 # doc comment above the interface line (or "")
print(iface.get_description())   # full .varlink text
method = iface.get_method("GetItem")  # method definition (_Method)
```

**Interface attributes:**

| Attribute | Type | Description |
|---|---|---|
| `iface.name` | `str` | Fully-qualified interface name |
| `iface.doc` | `str` | Doc comment preceding the `interface` line |
| `iface.members` | `OrderedDict` | All members keyed by name (methods, types, errors) |
| `iface.get_description()` | `str` | Original `.varlink` source text |
| `iface.get_method(name)` | `_Method` | Look up a method (raises `MethodNotFound`) |

**Iterating members:**

`iface.members` is an `OrderedDict[str, _Method | _Alias | _Error]` preserving declaration order.

```python
from varlink.scanner import _Method, _Alias, _Error

for name, member in iface.members.items():
    if isinstance(member, _Method):
        print(f"method {name}: {member.doc}")
    elif isinstance(member, _Alias):   # type definition
        print(f"type {name}: {member.doc}")
    elif isinstance(member, _Error):
        print(f"error {name}: {member.doc}")
```

**Member object attributes:**

All member types (`_Method`, `_Alias`, `_Error`) share:

| Attribute | Type | Description |
|---|---|---|
| `.name` | `str` | Member name (e.g. `"GetItem"`) |
| `.doc` | `str \| None` | `#` comment text preceding the member, or `None` |

`_Method` additionally has:

| Attribute | Type | Description |
|---|---|---|
| `.in_type` | parsed type | Input parameter struct |
| `.out_type` | parsed type | Output parameter struct |
| `.signature` | `str` | Raw signature string `(params) -> (params)` |

`_Alias` (type definition) additionally has:

| Attribute | Type | Description |
|---|---|---|
| `.type` | parsed type | The defined type |

`_Error` additionally has:

| Attribute | Type | Description |
|---|---|---|
| `.type` | parsed type | Error parameter struct |

**Server-side introspection** (in-process, no network):

```python
# service.interfaces is a dict[str, Interface]
iface = service.interfaces["org.example.echo"]

# List all methods with their documentation
from varlink.scanner import _Method
for name, member in iface.members.items():
    if isinstance(member, _Method):
        print(f"{name}: {member.doc}")
```

---

### Mock/Test Framework

```python
from varlink import mock

types = """
type Item (name: string, count: int)
"""

class FakeService:
    def GetItems(self) -> dict:
        """return items: []Item"""
        return {"items": [{"name": "a", "count": 1}]}

@mock.mockedservice(
    fake_service=FakeService,
    fake_types=types,
    name="org.example.items",
    address="unix:@test"
)
def test_client():
    with varlink.Client.new_with_address("unix:@test") as client:
        with client.open("org.example.items") as con:
            result = con.GetItems()
            assert result["items"][0]["name"] == "a"
```

The mock framework auto-generates a `.varlink` interface from the Python class: method names, parameter type annotations, return type annotations, and docstring hints for complex return types.

---

### Custom JSON Encoding

```python
import datetime

class MyEncoder(varlink.VarlinkEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super().default(obj)

service = varlink.Service(..., json_encoder_cls=MyEncoder)
```

`VarlinkEncoder` already handles: `set` → `{k: {} for k in set}`, `SimpleNamespace` → `dict`, `VarlinkError` → error dict.

---

### CLI Tool

```bash
python -m varlink.cli info unix:@echo
python -m varlink.cli help org.example.echo
python -m varlink.cli call org.example.echo.Echo '{"message": "hi"}'
python -m varlink.cli --more call org.example.echo.Monitor '{}'
python -m varlink.cli bridge
python -m varlink.cli --activate 'python server.py --varlink=$VARLINK_ADDRESS' \
    call org.example.echo.Echo '{"message": "hi"}'
```

---

## Protocol Patterns Summary

| Pattern | Client sets | Server behavior |
|---|---|---|
| Normal call | (nothing special) | Single reply |
| One-way | `oneway: true` | No reply |
| Streaming | `more: true` | Multiple replies with `continues: true`, last with `continues: false` |
| Upgrade | `upgrade: true` | Single reply, then connection switches to custom protocol |
| Pipelining | Multiple `oneway` calls, then one normal | Queued processing |

---

## Interface Versioning

- No version numbers. Clients introspect available methods/types.
- Extend safely: add optional (`?type`) fields, new methods, new types.
- Never remove fields/types/methods/errors.
- Breaking changes: create new interface with version suffix (e.g., `org.example.service2`).

---

## Key Files in Python Library

| File | Purpose |
|---|---|
| `varlink/__init__.py` | Public API exports |
| `varlink/server.py` | Service, RequestHandler, Server, ThreadingServer, ForkingServer |
| `varlink/client.py` | Client, ClientInterfaceHandler, SimpleClientInterfaceHandler |
| `varlink/scanner.py` | Interface, Scanner (IDL parser) |
| `varlink/error.py` | VarlinkError subclasses, VarlinkEncoder |
| `varlink/mock.py` | MockedService, mockedservice decorator |
| `varlink/cli.py` | Command-line tool |
| `varlink/org.varlink.service.varlink` | Built-in service interface definition |
