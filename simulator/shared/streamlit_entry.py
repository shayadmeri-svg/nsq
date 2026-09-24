"""Streamlit launcher that keeps the container logs readable.

Why this exists
---------------
Streamlit sends every ForwardMsg to the browser via
``BrowserWebSocketHandler.write_forward_msg`` (streamlit 1.50,
``streamlit/web/server/browser_websocket_handler.py``)::

    def write_forward_msg(self, msg: ForwardMsg) -> None:
        try:
            self.write_message(serialize_forward_msg(msg), binary=True)
        except tornado.websocket.WebSocketClosedError as e:
            raise SessionClientDisconnectedError from e

``tornado``'s ``write_message`` is a coroutine-returning call, and Streamlit
does not await the Future it hands back. The ``except`` only catches the
*synchronous* raise (socket already torn down). When the browser goes away
*mid-render* — a tab closed or reloaded while the app is still streaming
widgets — the socket is closed but the handler is still alive, so the write
fails asynchronously instead. Nobody ever retrieves that Future, so asyncio
prints a full ``Task exception was never retrieved`` traceback for *every*
queued message. One page reload during a slow render is worth dozens of them,
which is how these end up flooding ``docker compose logs``.

The exceptions are cosmetic: the session is gone, there is nothing left to
deliver, and Streamlit cleans the session up on its own. What is not
cosmetic is that they bury real errors. So: install an asyncio exception
handler that drops exactly these two exception types and defers everything
else to the default handler.

This is a launcher, not an import hook — the Dockerfile ENTRYPOINT runs
``python -u shared/streamlit_entry.py run app.py …`` instead of
``streamlit run app.py …``, and every argument is passed straight through to
Streamlit's own CLI.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from tornado.iostream import StreamClosedError
from tornado.websocket import WebSocketClosedError

_LOGGER = logging.getLogger("nsq.streamlit_entry")

# Both show up in the same chain: tornado raises StreamClosedError from the
# underlying IOStream and re-raises it as WebSocketClosedError.
_CLIENT_GONE = (WebSocketClosedError, StreamClosedError)


def _quiet_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get("exception")
    if isinstance(exc, _CLIENT_GONE):
        # Browser disconnected before we finished writing to it. Nothing to
        # do and nothing to report; debug-level so it can still be seen with
        # --logger.level=debug.
        _LOGGER.debug("dropped a ForwardMsg for a disconnected browser: %r", exc)
        return
    loop.default_exception_handler(context)


class _QuietEventLoopPolicy(type(asyncio.get_event_loop_policy())):  # type: ignore[misc]
    """Event loop policy that pre-installs the handler above.

    Streamlit's bootstrap calls ``asyncio.run(main())``, which builds its loop
    through the active policy, so this is the one hook that reliably lands on
    the loop the tornado server actually uses.
    """

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        loop = super().new_event_loop()
        loop.set_exception_handler(_quiet_exception_handler)
        return loop


def main() -> int:
    asyncio.set_event_loop_policy(_QuietEventLoopPolicy())

    from streamlit.web.cli import main as streamlit_main

    # Streamlit's CLI is a click group and reads sys.argv itself.
    sys.argv = ["streamlit", *sys.argv[1:]]
    return streamlit_main()


if __name__ == "__main__":
    sys.exit(main())
