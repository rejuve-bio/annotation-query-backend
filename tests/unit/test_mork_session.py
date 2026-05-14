# Stub heavy production deps before any app imports so this file can be run
# without the full dependency stack.  Real packages (installed in Docker) take
# precedence via sys.modules.setdefault — integration tests are unaffected.
import sys
from unittest.mock import MagicMock

for _dep in ("biocypher", "hyperon", "neo4j", "neo4j.exceptions",
             "flask", "flask_mail", "celery", "celery.utils.log",
             "anthropic", "openai", "tiktoken", "nanoid", "socketio",
             "elasticsearch", "pymongo", "motor"):
    if _dep not in sys.modules:
        try:
            __import__(_dep)
        except ImportError:
            sys.modules[_dep] = MagicMock()

import os
import signal as _signal
import subprocess
import time
from unittest.mock import patch

import pytest

import app.services.mork_cli_generator as mod
from app.services.mork_cli_generator import _MorkSession, _make_signal_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def live_session():
    """A session whose container appears alive via the TTL cache."""
    s = _MorkSession("/tmp/test_dataset")
    s._cid = "container_abc"
    s._last_alive_check = time.monotonic()  # cache fresh → _alive() returns True without docker inspect
    return s


def _make_handler(prev):
    """Build a signal handler with a controlled previous-handler value."""
    with patch.object(mod._signal, "getsignal", return_value=prev):
        return _make_signal_handler(_signal.SIGTERM)


# ---------------------------------------------------------------------------
# _MorkSession.exec_query — retry / self-healing path
# ---------------------------------------------------------------------------

class TestExecQueryRetry:
    def test_retries_after_container_dies_within_ttl(self, live_session):
        """When docker exec fails because the container died within the TTL window,
        exec_query invalidates the cache, restarts the container, and retries once."""
        exec_fail  = subprocess.CalledProcessError(1, ["docker", "exec"], stderr="No such container")
        inspect    = MagicMock(returncode=0, stdout="false\n")   # container not running
        docker_run = MagicMock(returncode=0, stdout="new_cid\n")
        exec_ok    = MagicMock(returncode=0, stdout="result: 42\n")

        with patch("subprocess.run", side_effect=[exec_fail, inspect, docker_run, exec_ok]) as mock_run:
            result = live_session.exec_query("/tmp/query.metta")

        assert result.stdout == "result: 42\n"
        assert live_session._cid == "new_cid"
        assert mock_run.call_count == 4

    def test_reraises_when_container_alive_and_mork_errors(self, live_session):
        """When docker exec fails but the container is still running, the error is
        a real MORK query failure — exec_query re-raises without restarting."""
        exec_fail     = subprocess.CalledProcessError(1, ["docker", "exec"], stderr="mork: parse error")
        inspect_alive = MagicMock(returncode=0, stdout="true\n")

        with patch("subprocess.run", side_effect=[exec_fail, inspect_alive]):
            with pytest.raises(subprocess.CalledProcessError):
                live_session.exec_query("/tmp/query.metta")

    def test_ttl_cache_invalidated_on_exec_failure(self, live_session):
        """After docker exec fails, _alive() must perform a real docker inspect
        rather than returning True from the stale TTL cache.  Verified by
        confirming the inspect call appears as the second subprocess.run call."""
        exec_fail     = subprocess.CalledProcessError(1, ["docker", "exec"], stderr="error")
        inspect_alive = MagicMock(returncode=0, stdout="true\n")

        with patch("subprocess.run", side_effect=[exec_fail, inspect_alive]) as mock_run:
            with pytest.raises(subprocess.CalledProcessError):
                live_session.exec_query("/tmp/query.metta")

        # First call: docker exec (failed). Second call: docker inspect (cache was cleared).
        assert mock_run.call_count == 2
        second_cmd = mock_run.call_args_list[1][0][0]
        assert "docker" in second_cmd and "inspect" in second_cmd


# ---------------------------------------------------------------------------
# _MorkSession._start() — label assertions
# ---------------------------------------------------------------------------

class TestStartLabels:
    def _docker_run_args(self, mock_run):
        return mock_run.call_args_list[0][0][0]

    def test_mork_worker_label_always_present(self, tmp_path):
        s = _MorkSession(str(tmp_path))
        with patch("subprocess.run", return_value=MagicMock(stdout="cid\n")) as mock_run:
            with patch.dict(os.environ, {}, clear=False):
                s._start()
        args = self._docker_run_args(mock_run)
        assert "--label" in args
        assert "mork.worker=1" in args

    def test_project_label_added_when_env_set(self, tmp_path):
        s = _MorkSession(str(tmp_path))
        with patch("subprocess.run", return_value=MagicMock(stdout="cid\n")) as mock_run:
            with patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": "myproject"}):
                s._start()
        args = self._docker_run_args(mock_run)
        assert "mork.project=myproject" in args

    def test_project_label_absent_when_env_unset(self, tmp_path):
        s = _MorkSession(str(tmp_path))
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_PROJECT_NAME"}
        with patch("subprocess.run", return_value=MagicMock(stdout="cid\n")) as mock_run:
            with patch.dict(os.environ, env, clear=True):
                s._start()
        args = self._docker_run_args(mock_run)
        assert not any("mork.project" in a for a in args)

    def test_compose_project_label_not_used(self, tmp_path):
        """Must not use com.docker.compose.project — that label triggers orphan
        detection in docker compose down --remove-orphans."""
        s = _MorkSession(str(tmp_path))
        with patch("subprocess.run", return_value=MagicMock(stdout="cid\n")) as mock_run:
            with patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": "myproject"}):
                s._start()
        args = self._docker_run_args(mock_run)
        assert not any("com.docker.compose.project" in a for a in args)


# ---------------------------------------------------------------------------
# _make_signal_handler — chaining and edge cases
# ---------------------------------------------------------------------------

class TestSignalHandler:
    def test_cleanup_is_called(self):
        handler = _make_handler(prev=lambda s, f: None)
        with patch.object(mod, "_cleanup_sessions") as mock_cleanup:
            handler(_signal.SIGTERM, None)
        mock_cleanup.assert_called_once()

    def test_chains_to_previous_callable_handler(self):
        calls = []
        handler = _make_handler(prev=lambda s, f: calls.append(s))
        with patch.object(mod, "_cleanup_sessions"):
            handler(_signal.SIGTERM, None)
        assert calls == [_signal.SIGTERM]

    def test_cleanup_exception_does_not_prevent_chaining(self):
        """A RuntimeError in _cleanup_sessions must not swallow the signal — the
        previous handler must still be called (finally block)."""
        calls = []
        handler = _make_handler(prev=lambda s, f: calls.append(s))
        with patch.object(mod, "_cleanup_sessions", side_effect=RuntimeError("boom")):
            handler(_signal.SIGTERM, None)
        assert calls == [_signal.SIGTERM]

    def test_sig_ign_is_preserved(self):
        """When the previous handler was SIG_IGN the process must not be killed."""
        handler = _make_handler(prev=_signal.SIG_IGN)
        with patch.object(mod, "_cleanup_sessions"):
            with patch.object(mod._signal, "signal") as mock_sig:
                with patch("os.kill") as mock_kill:
                    handler(_signal.SIGTERM, None)
        mock_sig.assert_not_called()
        mock_kill.assert_not_called()

    def test_sig_dfl_resets_and_redelivers_signal(self):
        """When there was no previous handler (SIG_DFL) the handler reinstalls the
        default disposition and re-sends the signal so the process actually exits."""
        handler = _make_handler(prev=_signal.SIG_DFL)
        with patch.object(mod, "_cleanup_sessions"):
            with patch.object(mod._signal, "signal") as mock_sig:
                with patch("os.kill") as mock_kill:
                    handler(_signal.SIGTERM, None)
        mock_sig.assert_called_once_with(_signal.SIGTERM, _signal.SIG_DFL)
        mock_kill.assert_called_once_with(os.getpid(), _signal.SIGTERM)
