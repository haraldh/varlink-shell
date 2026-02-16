import json

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

    def test_help_pipe_count(self):
        result = execute("help | count")
        assert result[0]["count"] >= 4


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

    def test_count_wire(self):
        replies = self._call("Count", {
            "input": [{"a": 1}, {"b": 2}],
        })
        assert len(replies) == 1
        assert replies[0]["parameters"] == {"count": 2}
