"""ADP JSON-RPC client that communicates with *adp_hypervisor* via subprocess.

The client spawns ``adp_hypervisor`` as a child process and exchanges JSON-RPC
2.0 messages over *stdin* / *stdout*.  It supports automatic restart on crash
(up to ``_MAX_RESTARTS`` attempts) and serialises concurrent requests through an
``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "2026-01-20"
_CLIENT_NAME = "adp-mcp-bridge"
_CLIENT_VERSION = "0.1.0"
_REQUEST_TIMEOUT = 30
_STOP_TIMEOUT = 5
_MAX_RESTARTS = 3

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ADPClientError(Exception):
    """Base exception for all ADP client errors."""


class ADPConnectionError(ADPClientError):
    """Subprocess connection or lifecycle error."""


class ADPProtocolError(ADPClientError):
    """JSON-RPC error response from *adp_hypervisor*.

    Attributes:
        code: Numeric error code returned by the server.
        message: Human-readable error description.
        data: Optional additional error data.
    """

    def __init__(self, code: int, message: str, data: object = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC error {code}: {message}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ADPClient:
    """Async JSON-RPC 2.0 client for the ADP hypervisor subprocess."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._request_id: int = 0
        self._config_path: str | None = None
        self._restart_count: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    # -- public interface ---------------------------------------------------

    async def start(self, config_path: str) -> None:
        """Spawn the *adp_hypervisor* subprocess and perform the handshake.

        Args:
            config_path: Filesystem path to the hypervisor configuration file.

        Raises:
            ADPConnectionError: If the subprocess cannot be started.
            ADPProtocolError: If the initialise handshake fails.
        """
        self._config_path = config_path
        await self._start_subprocess()

        await self._send_request(
            "adp.initialize",
            {
                "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
            },
        )
        logger.info("ADP hypervisor initialised (config=%s)", config_path)

    async def stop(self) -> None:
        """Gracefully stop the subprocess (SIGTERM, then SIGKILL after timeout)."""
        if self._process is None:
            return

        proc = self._process
        self._process = None

        if proc.returncode is not None:
            return

        logger.info("Sending SIGTERM to adp_hypervisor (pid=%s)", proc.pid)
        try:
            proc.send_signal(signal.SIGTERM)
            await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT)
        except (TimeoutError, ProcessLookupError):
            logger.warning("SIGTERM timed out – sending SIGKILL (pid=%s)", proc.pid)
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

        logger.info("adp_hypervisor stopped")

    async def discover(
        self,
        domain_prefix: str | None = None,
        intent_class: str | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        """Discover available ADP resources.

        Args:
            domain_prefix: Optional domain prefix filter.
            intent_class: Optional intent-class filter.
            keyword: Optional keyword search term.
            cursor: Optional pagination cursor.

        Returns:
            Server response payload.
        """
        filter_obj: dict[str, object] = {}
        if domain_prefix is not None:
            filter_obj["domainPrefix"] = domain_prefix
        if intent_class is not None:
            filter_obj["intentClass"] = intent_class
        if keyword is not None:
            filter_obj["keyword"] = keyword

        params: dict[str, object] = {}
        if filter_obj:
            params["filter"] = filter_obj
        if cursor is not None:
            params["cursor"] = cursor

        return await self._send_request("adp.discover", params)

    async def describe(
        self,
        resource_id: str,
        intent_class: str,
        version: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        """Describe a specific ADP resource.

        Args:
            resource_id: Unique resource identifier.
            intent_class: The intent class to describe.
            version: Optional schema version.
            cursor: Optional pagination cursor.

        Returns:
            Server response payload.
        """
        params: dict[str, object] = {
            "resourceId": resource_id,
            "intentClass": intent_class,
        }
        if version is not None:
            params["version"] = version
        if cursor is not None:
            params["cursor"] = cursor

        return await self._send_request("adp.describe", params)

    async def validate(
        self,
        resource_id: str,
        intent: dict[str, object],
    ) -> dict[str, object]:
        """Validate an intent against a resource.

        Args:
            resource_id: Unique resource identifier.
            intent: The intent payload to validate.

        Returns:
            Server response payload.
        """
        return await self._send_request(
            "adp.validate",
            {"resourceId": resource_id, "intent": intent},
        )

    async def execute(
        self,
        resource_id: str,
        intent: dict[str, object],
        cursor: str | None = None,
    ) -> dict[str, object]:
        """Execute an intent on a resource.

        Args:
            resource_id: Unique resource identifier.
            intent: The intent payload to execute.
            cursor: Optional pagination cursor.

        Returns:
            Server response payload.
        """
        params: dict[str, object] = {"resourceId": resource_id, "intent": intent}
        if cursor is not None:
            params["cursor"] = cursor

        return await self._send_request("adp.execute", params)

    # -- private helpers ----------------------------------------------------

    async def _send_request(
        self,
        method: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        """Build and send a JSON-RPC 2.0 request, then return the result.

        Args:
            method: JSON-RPC method name.
            params: Method parameters.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            ADPConnectionError: If the subprocess is unreachable.
            ADPProtocolError: If the server returns a JSON-RPC error object.
            ADPClientError: On timeout or unexpected response format.
        """
        async with self._lock:
            await self._ensure_alive()

            assert self._process is not None  # noqa: S101
            assert self._process.stdin is not None  # noqa: S101
            assert self._process.stdout is not None  # noqa: S101

            self._request_id += 1
            envelope: dict[str, object] = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }

            payload = json.dumps(envelope) + "\n"
            logger.debug("-> %s (id=%s)", method, self._request_id)

            try:
                self._process.stdin.write(payload.encode())
                await self._process.stdin.drain()

                raw = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=_REQUEST_TIMEOUT,
                )
            except TimeoutError as exc:
                raise ADPClientError(
                    f"Request {method!r} (id={self._request_id}) timed out "
                    f"after {_REQUEST_TIMEOUT}s"
                ) from exc
            except OSError as exc:
                raise ADPConnectionError(
                    f"I/O error while communicating with adp_hypervisor: {exc!r}"
                ) from exc

            if not raw:
                raise ADPConnectionError("adp_hypervisor closed stdout unexpectedly")

            try:
                response = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ADPClientError(f"Invalid JSON from adp_hypervisor: {raw!r}") from exc

            if "error" in response:
                err = response["error"]
                raise ADPProtocolError(
                    code=err.get("code", -1),
                    message=err.get("message", "unknown error"),
                    data=err.get("data"),
                )

            return response.get("result", {})  # type: ignore[no-any-return]

    async def _ensure_alive(self) -> None:
        """Verify the subprocess is running; restart if it has crashed.

        Raises:
            ADPConnectionError: If the subprocess cannot be (re)started after
                ``_MAX_RESTARTS`` attempts.
        """
        if self._process is not None and self._process.returncode is None:
            return

        if self._config_path is None:
            raise ADPConnectionError("Cannot restart adp_hypervisor: no config_path recorded")

        if self._restart_count >= _MAX_RESTARTS:
            raise ADPConnectionError(
                f"adp_hypervisor has crashed {self._restart_count} times; "
                f"giving up (max={_MAX_RESTARTS})"
            )

        self._restart_count += 1
        logger.warning(
            "adp_hypervisor is not running – attempting restart %s/%s",
            self._restart_count,
            _MAX_RESTARTS,
        )
        await self._start_subprocess()

    async def _start_subprocess(self) -> None:
        """Spawn the *adp_hypervisor* child process.

        Raises:
            ADPConnectionError: If the subprocess fails to start.
        """
        if self._config_path is None:
            raise ADPConnectionError("Cannot start adp_hypervisor: config_path is not set")

        try:
            self._process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "adp_hypervisor",
                "--config",
                self._config_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ADPConnectionError(f"Failed to spawn adp_hypervisor: {exc!r}") from exc

        logger.info(
            "adp_hypervisor started (pid=%s, config=%s)",
            self._process.pid,
            self._config_path,
        )
