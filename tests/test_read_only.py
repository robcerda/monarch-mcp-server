"""Tests for opt in read only mode."""

import asyncio
import subprocess
import sys

import pytest

from monarch_mcp_server import read_only


class TestIsReadOnly:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " y "])
    def test_truthy_values_enable_it(self, monkeypatch, value):
        monkeypatch.setenv(read_only.ENV_VAR, value)
        assert read_only.is_read_only() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
    def test_everything_else_leaves_it_off(self, monkeypatch, value):
        monkeypatch.setenv(read_only.ENV_VAR, value)
        assert read_only.is_read_only() is False

    def test_unset_leaves_it_off(self, monkeypatch):
        """Off by default, so existing setups are unaffected."""
        monkeypatch.delenv(read_only.ENV_VAR, raising=False)
        assert read_only.is_read_only() is False


class TestRegistration:
    """Registration is skipped, not just guarded at call time.

    A tool that is never registered cannot be invoked at all, which is
    stronger than a client side approval prompt: the threat in the README's
    approval section is a model influenced by a memo or merchant name it read
    back, and that model cannot call what it cannot see.
    """

    def test_mutating_tools_are_not_registered(self, monkeypatch):
        registered = []

        class FakeMCP:
            def tool(self, *args, **kwargs):
                def decorator(fn):
                    registered.append(fn.__name__)
                    return fn

                return decorator

        monkeypatch.setenv(read_only.ENV_VAR, "1")
        fake = FakeMCP()
        read_only.install(fake)

        def delete_transaction():
            pass

        def get_accounts():
            pass

        assert fake.tool()(delete_transaction) is delete_transaction
        fake.tool()(get_accounts)

        assert "delete_transaction" not in registered
        assert "get_accounts" in registered

    def test_nothing_is_skipped_when_disabled(self, monkeypatch):
        registered = []

        class FakeMCP:
            def tool(self, *args, **kwargs):
                def decorator(fn):
                    registered.append(fn.__name__)
                    return fn

                return decorator

        monkeypatch.delenv(read_only.ENV_VAR, raising=False)
        fake = FakeMCP()
        read_only.install(fake)

        def delete_transaction():
            pass

        fake.tool()(delete_transaction)
        assert registered == ["delete_transaction"]


class TestMutatingToolList:
    async def test_every_named_tool_actually_exists(self):
        """A typo here would silently leave a mutating tool exposed."""
        from monarch_mcp_server.app import mcp

        registered = {t.name for t in await mcp.list_tools()}
        # Only meaningful when read only is off, which is the default in tests.
        if not read_only.is_read_only():
            unknown = read_only.MUTATING_TOOLS - registered
            assert not unknown, f"MUTATING_TOOLS names no such tools: {sorted(unknown)}"

    async def test_it_matches_the_readme_approval_list(self):
        """The two lists answer the same question and must not diverge."""
        from pathlib import Path

        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
        section = readme[readme.index("### Recommended: require approval") :]
        missing = {n for n in read_only.MUTATING_TOOLS if f"`{n}`" not in section}
        assert not missing, f"in MUTATING_TOOLS but not the README list: {sorted(missing)}"


class TestGateCannotSilentlyMissANewWriteTool:
    """The direction that actually matters.

    Asserting every name in MUTATING_TOOLS exists catches a typo. It cannot
    catch a newly added writing tool that nobody put in the set, which is the
    failure that exposes a write in a deployment whose whole premise is that it
    cannot write. This derives the mutating set from the code instead.
    """

    # Library calls that write. Derived from the upstream client surface.
    # Leading verbs that mark a library call as a write. Used for calls that
    # are resolved by name rather than written out, where there is no literal
    # client.<method>( for the check below to find.
    WRITING_VERBS = frozenset(
        {"create", "update", "delete", "set", "bulk", "add", "remove", "reorder"}
    )

    WRITING_CLIENT_METHODS = frozenset(
        {
            "create_transaction",
            "update_transaction",
            "delete_transaction",
            "set_transaction_tags",
            "create_transaction_tag",
            "update_transaction_splits",
            "create_transaction_category",
            "delete_transaction_category",
            "set_budget_amount",
            "update_account",
            "delete_account",
            "request_accounts_refresh",
            "request_accounts_refresh_and_wait",
            "upload_account_balance_history",
        }
    )

    @staticmethod
    def _is_mutation_document(obj):
        """Whether a module level gql constant is a mutation.

        Read from the parsed AST rather than the source text. gql 4.x wraps the
        DocumentNode in a GraphQLRequest, so both shapes are handled; a text
        match would also be fooled by the word "mutation" in a comment.
        """
        from graphql.language.ast import DocumentNode, OperationDefinitionNode

        doc = getattr(obj, "document", obj)
        if not isinstance(doc, DocumentNode):
            return False
        return any(
            isinstance(d, OperationDefinitionNode)
            and getattr(d.operation, "value", d.operation) == "mutation"
            for d in doc.definitions
        )

    def _mutating_from_source(self):
        import inspect
        import re

        from monarch_mcp_server import read_only as ro
        from monarch_mcp_server import server as srv

        mutating = set()
        for name in dir(srv):
            fn = getattr(srv, name)
            if not callable(fn) or not hasattr(fn, "__module__"):
                continue
            if not str(fn.__module__).startswith("monarch_mcp_server.tools"):
                continue
            try:
                source = inspect.getsource(fn)
            except (OSError, TypeError):
                continue

            module = __import__(fn.__module__, fromlist=["x"])

            for const in re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", source):
                if self._is_mutation_document(getattr(module, const, None)):
                    mutating.add(name)

            for method in self.WRITING_CLIENT_METHODS:
                if f"client.{method}(" in source:
                    mutating.add(name)

            # The two checks above only see a mutation held in an UPPERCASE
            # module constant or sent through a named client method. gql_call
            # accepts an arbitrary document, so a mutation written inline, or
            # held in a lowercase or local name, would slip past both and
            # register ungated with this test still green.
            inline_mutation = r"gql\(\s*[\"']{1,3}\s*mutation\b"
            if re.search(inline_mutation, source, re.I):
                mutating.add(name)
            for ident in re.findall(
                r"graphql_query\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", source
            ):
                if self._is_mutation_document(getattr(module, ident, None)):
                    mutating.add(name)

            # A tool can also reach a writing library call without ever
            # writing client.<method>( literally, by resolving it first:
            #     updater = getattr(client, "update_flexible_budget", None)
            #     await updater(...)
            # The literal check above sees nothing, and the name need not be
            # in WRITING_CLIENT_METHODS to be a write, so the verb decides.
            # Keeping this heuristic separate means a new writing method does
            # not have to be added to the list by hand to be caught.
            for resolved in re.findall(
                r"getattr\(\s*client\s*,\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']",
                source,
            ):
                if resolved.split("_")[0] in self.WRITING_VERBS:
                    mutating.add(name)
        return mutating, ro

    async def test_every_writing_tool_is_gated(self):
        from monarch_mcp_server.app import mcp

        mutating, ro = self._mutating_from_source()
        registered = {t.name for t in await mcp.list_tools()}
        ungated = sorted((mutating & registered) - ro.MUTATING_TOOLS)
        assert not ungated, (
            "these tools write but are not in MUTATING_TOOLS, so read only "
            f"mode would still expose them: {ungated}"
        )

    async def test_the_detector_actually_detects_something(self):
        """Guard against the check above silently matching nothing."""
        mutating, _ = self._mutating_from_source()
        assert len(mutating) >= 25, (
            f"detector found only {len(mutating)} writing tools, so it is "
            "probably broken rather than the code being clean"
        )


class TestPositionalToolName:
    def test_a_positionally_named_mutating_tool_is_still_gated(self, monkeypatch):
        """FastMCP.tool() takes name as its first positional parameter.

        Comparing only fn.__name__ would let @mcp.tool("delete_transaction")
        register under a gated name while slipping past the gate.
        """
        registered = []

        class FakeMCP:
            def tool(self, *args, **kwargs):
                def decorator(fn):
                    registered.append(args[0] if args else fn.__name__)
                    return fn

                return decorator

        monkeypatch.setenv(read_only.ENV_VAR, "1")
        fake = FakeMCP()
        read_only.install(fake)

        def some_helper():
            pass

        fake.tool("delete_transaction")(some_helper)
        assert registered == []


class TestDockerDefault:
    """The container serves HTTP with no authentication, so it must default to
    read only: otherwise anything reaching the port could call monarch_logout
    or monarch_login_with_token and replace the stored session (issue #154)."""

    @staticmethod
    def _dockerfile_env():
        from pathlib import Path

        dockerfile = Path(__file__).resolve().parent.parent / "Dockerfile"
        env = {}
        in_env = False
        for raw in dockerfile.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("ENV "):
                in_env, line = True, line[4:]
            if not in_env:
                continue
            continued = line.endswith("\\")
            for pair in line.rstrip("\\").split():
                key, _, value = pair.partition("=")
                env[key] = value.strip('"')
            in_env = continued
        return env

    def test_dockerfile_turns_read_only_on(self):
        env = self._dockerfile_env()
        assert env.get(read_only.ENV_VAR) == "1"

    def test_session_tools_are_not_exposed_under_the_docker_env(self, tmp_path):
        """Registration, not just the ENV line: the server started with the
        image's setting must not list the tools that change the session."""
        import os

        env = {**os.environ, read_only.ENV_VAR: self._dockerfile_env()[read_only.ENV_VAR]}
        env["HOME"] = str(tmp_path)
        # conftest's keyring isolation only covers this process, and importing
        # the app in the subprocess constructs SecureMonarchSession at module
        # scope, which probes the keyring. With HOME pointed at an empty temp
        # dir, macOS finds no login keychain there and prompts the developer to
        # create or reset one, which also hangs an unattended run. Pin a null
        # backend so the probe never reaches a real keychain.
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        script = (
            "import asyncio\n"
            "from monarch_mcp_server.app import mcp\n"
            "names = {t.name for t in asyncio.run(mcp.list_tools())}\n"
            "print(','.join(sorted(names)))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True
        )
        names = set(result.stdout.strip().split(","))
        assert names, "no tools were listed"
        assert not names & {"monarch_login", "monarch_login_with_token", "monarch_logout"}
        assert not names & read_only.MUTATING_TOOLS
