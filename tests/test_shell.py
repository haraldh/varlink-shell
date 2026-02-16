import json
import sys

import pytest

from varlink_shell.shell import execute, parse, service


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_single_command(self):
        assert parse("echo hello") == [("echo", ["hello"])]

    def test_pipeline(self):
        assert parse("ls | count") == [("ls", []), ("count", [])]

    def test_key_value_args(self):
        assert parse("echo name=alice age=30") == [
            ("echo", ["name=alice", "age=30"])
        ]

    def test_empty_stage_leading_pipe(self):
        with pytest.raises(ValueError, match="empty pipeline stage"):
            parse("| ls")

    def test_empty_stage_trailing_pipe(self):
        with pytest.raises(ValueError, match="empty pipeline stage"):
            parse("ls |")

    def test_empty_line(self):
        assert parse("") == []

    def test_multi_stage_pipeline(self):
        assert parse("ls | echo | count") == [
            ("ls", []),
            ("echo", []),
            ("count", []),
        ]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

class TestExecution:
    def test_echo_kv(self):
        result = execute("echo name=alice age=30")
        assert result == [{"name": "alice", "age": "30"}]

    def test_echo_passthrough(self):
        result = execute("echo name=bob | echo")
        assert result == [{"name": "bob"}]

    def test_ls_count(self, tmp_path, monkeypatch):
        # Create some files in a temp directory
        for name in ["a.txt", "b.txt", "c.txt"]:
            (tmp_path / name).touch()

        result = execute(f"ls {tmp_path} | count")
        assert result == [{"count": 3}]

    def test_count_no_input(self):
        result = execute("count")
        assert result == [{"count": 0}]

    def test_ls_returns_entries(self, tmp_path):
        (tmp_path / "hello.txt").write_text("hi")
        (tmp_path / "subdir").mkdir()

        result = execute(f"ls {tmp_path}")
        names = {obj["name"] for obj in result}
        assert names == {"hello.txt", "subdir"}

        for obj in result:
            assert "type" in obj
            assert "size" in obj

    def test_echo_bare_arg(self):
        result = execute("echo verbose")
        assert result == [{"verbose": True}]

    def test_help(self):
        result = execute("help")
        commands = {obj["command"] for obj in result}
        assert {"echo", "ls", "count", "help"} <= commands
        for obj in result:
            assert "description" in obj

    def test_help_single_command(self):
        result = execute("help grep")
        assert len(result) >= 1
        assert result[0]["command"] == "grep"
        assert result[0]["description"] != ""

    def test_help_pipe_count(self):
        result = execute("help | count")
        assert result[0]["count"] >= 4

    def test_grep_type_dir(self, tmp_path):
        (tmp_path / "file.txt").write_text("hi")
        (tmp_path / "subdir").mkdir()

        result = execute(f"ls {tmp_path} | grep type=dir")
        assert all(obj["type"] == "dir" for obj in result)
        assert {obj["name"] for obj in result} == {"subdir"}

    def test_grep_multiple_filters(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hi")
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "script.py").write_text("pass")
        (tmp_path / "subdir").mkdir()

        result = execute(f"ls {tmp_path} | grep type=file name=.txt")
        assert all(obj["type"] == "file" for obj in result)
        assert all(".txt" in obj["name"] for obj in result)
        assert {obj["name"] for obj in result} == {"notes.txt", "readme.txt"}

    def test_grep_no_input(self):
        result = execute("echo | grep type=dir")
        assert result == []

    def test_grep_no_matches(self, tmp_path):
        (tmp_path / "file.txt").write_text("hi")

        result = execute(f"ls {tmp_path} | grep type=dir")
        assert result == []


# ---------------------------------------------------------------------------
# Raw service.handle() wire-format tests
# ---------------------------------------------------------------------------

class TestWireFormat:
    def _call(self, method, params):
        request = json.dumps({
            "method": f"sh.builtin.{method}",
            "more": True,
            "parameters": params,
        }).encode("utf-8")

        replies = []
        for reply_bytes in service.handle(request):
            replies.append(json.loads(reply_bytes))
        return replies

    def test_echo_wire(self):
        replies = self._call("Echo", {"args": ["x=1"]})
        assert len(replies) == 1
        assert replies[0]["parameters"]["object"] == {"x": "1"}
        assert replies[0].get("continues") is not True

    def test_ls_wire_continues(self, tmp_path):
        for name in ["a", "b"]:
            (tmp_path / name).touch()

        replies = self._call("Ls", {"args": [str(tmp_path)]})
        assert len(replies) == 2
        assert replies[0]["continues"] is True
        assert replies[0]["parameters"]["name"] == "a"
        assert replies[1].get("continues", False) is False

    def test_grep_wire(self):
        replies = self._call("Grep", {
            "args": ["color=red"],
            "input": [
                {"color": "red", "size": 1},
                {"color": "blue", "size": 2},
                {"color": "darkred", "size": 3},
            ],
        })
        assert len(replies) == 2
        assert replies[0]["parameters"]["object"] == {"color": "red", "size": 1}
        assert replies[0]["continues"] is True
        assert replies[1]["parameters"]["object"] == {"color": "darkred", "size": 3}
        assert replies[1].get("continues", False) is False

    def test_count_wire(self):
        replies = self._call("Count", {
            "input": [{"a": 1}, {"b": 2}],
        })
        assert len(replies) == 1
        assert replies[0]["parameters"] == {"count": 2}

    def test_jsexec_wire(self):
        replies = self._call("Jsexec", {
            "args": [sys.executable, "-c",
                     "import json; print(json.dumps({'a': 1}))"],
        })
        assert len(replies) == 1
        assert replies[0]["parameters"]["object"] == {"a": 1}
        assert replies[0].get("continues", False) is False


# ---------------------------------------------------------------------------
# Jsexec tests
# ---------------------------------------------------------------------------

class TestJsexec:
    def test_single_object(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps({'a': 1, 'b': 2}))\"")
        assert result == [{"a": 1, "b": 2}]

    def test_array_output(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps([{'x': 1}, {'x': 2}]))\"")
        assert result == [{"x": 1}, {"x": 2}]

    def test_auto_unwrap_single_key_list(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps({'items': [{'n': 1}, {'n': 2}]}))\"")
        assert result == [{"n": 1}, {"n": 2}]

    def test_non_dict_elements_wrapped(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps([1, 'hello']))\"")
        assert result == [{"value": 1}, {"value": "hello"}]

    def test_pipeline_with_grep(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps([{'color': 'red'}, {'color': 'blue'}]))\" "
            "| grep color=red")
        assert result == [{"color": "red"}]

    def test_error_no_args(self):
        with pytest.raises(RuntimeError, match="InvalidParameter"):
            execute("jsexec")

    def test_error_nonzero_exit(self):
        with pytest.raises(RuntimeError, match="ExecFailed"):
            execute(f"jsexec {sys.executable} -c \"raise SystemExit(1)\"")

    def test_error_invalid_json(self):
        with pytest.raises(RuntimeError, match="InvalidJson"):
            execute(f"jsexec {sys.executable} -c \"print('not json')\"")

    def test_dict_multi_key_not_unwrapped(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps({'a': [1], 'b': [2]}))\"")
        assert result == [{"a": [1], "b": [2]}]


# ---------------------------------------------------------------------------
# Map tests
# ---------------------------------------------------------------------------

class TestMap:
    def test_projection(self):
        result = execute("echo a=1 b=2 c=3 | map a c")
        assert result == [{"a": "1", "c": "3"}]

    def test_rename(self):
        result = execute("echo x=1 | map y={x}")
        assert result == [{"y": "1"}]

    def test_interpolation(self):
        result = execute('echo name=bob age=30 | map label="{name} is {age}"')
        assert result == [{"label": "bob is 30"}]

    def test_type_preservation(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps({'a': 42, 'b': 'hello'}))\" "
            "| map val={a}")
        assert result == [{"val": 42}]

    def test_missing_field_omitted(self):
        result = execute("echo a=1 | map a b")
        assert result == [{"a": "1"}]

    def test_no_args_error(self):
        with pytest.raises(RuntimeError, match="InvalidParameter"):
            execute("echo a=1 | map")

    def test_no_input_empty(self):
        result = execute("map a")
        assert result == []

    def test_multiple_objects(self):
        result = execute(
            f"jsexec {sys.executable} -c "
            "\"import json; print(json.dumps([{'x': 1, 'y': 2}, {'x': 3, 'y': 4}]))\" "
            "| map x")
        assert result == [{"x": 1}, {"x": 3}]


# ---------------------------------------------------------------------------
# FilterMap tests
# ---------------------------------------------------------------------------

class TestFilterMap:
    def test_all_fields_present(self):
        result = execute("echo a=1 b=2 | filter_map a b")
        assert result == [{"a": "1", "b": "2"}]

    def test_missing_field_drops_object(self):
        result = execute("echo a=1 | filter_map a b")
        assert result == []

    def test_mixed_some_pass_some_dropped(self):
        prog = "import json; print(json.dumps([{'x': 1, 'y': 2}, {'x': 3}]))"
        result = execute(
            f'jsexec {sys.executable} -c "{prog}" '
            "| filter_map x y")
        assert result == [{"x": 1, "y": 2}]

    def test_rename(self):
        result = execute("echo a=1 b=2 | filter_map c={a} d={b}")
        assert result == [{"c": "1", "d": "2"}]

    def test_no_args_error(self):
        with pytest.raises(RuntimeError, match="InvalidParameter"):
            execute("echo a=1 | filter_map")

    def test_no_input_empty(self):
        result = execute("filter_map a")
        assert result == []


# ---------------------------------------------------------------------------
# Foreach tests
# ---------------------------------------------------------------------------

class TestForeach:
    def test_simple_command(self):
        result = execute("echo a=1 b=2 | foreach echo x={a}")
        assert result == [{"x": "1"}]

    def test_multiple_inputs(self):
        prog = """import json; print(json.dumps([{'n': 'a'}, {'n': 'b'}]))"""
        result = execute(
            f'jsexec {sys.executable} -c "{prog}" '
            "| foreach echo val={n}")
        assert result == [{"val": "a"}, {"val": "b"}]

    def test_sub_pipeline(self):
        result = execute(
            'echo a=hello | foreach "echo x={a} | grep x=hello"')
        assert result == [{"x": "hello"}]

    def test_no_args_error(self):
        with pytest.raises(RuntimeError, match="InvalidParameter"):
            execute("echo a=1 | foreach")

    def test_no_input_empty(self):
        result = execute("foreach echo x=1")
        assert result == []


# ---------------------------------------------------------------------------
# Wire-format tests for Map and Foreach
# ---------------------------------------------------------------------------

class TestWireFormatMapForeach(TestWireFormat):
    def test_map_wire(self):
        replies = self._call("Map", {
            "args": ["x", "y"],
            "input": [{"x": 1, "y": 2, "z": 3}],
        })
        assert len(replies) == 1
        assert replies[0]["parameters"]["object"] == {"x": 1, "y": 2}

    def test_map_wire_empty_input(self):
        replies = self._call("Map", {"args": ["x"]})
        assert len(replies) == 0

    def test_foreach_wire(self):
        replies = self._call("Foreach", {
            "args": ["echo", "v={a}"],
            "input": [{"a": "hello"}],
        })
        assert len(replies) == 1
        assert replies[0]["parameters"]["object"] == {"v": "hello"}

    def test_filter_map_wire(self):
        replies = self._call("FilterMap", {
            "args": ["a"],
            "input": [{"a": 1, "b": 2}, {"b": 3}],
        })
        assert len(replies) == 1
        assert replies[0]["parameters"]["object"] == {"a": 1}
