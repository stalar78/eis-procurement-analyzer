from __future__ import annotations

import ssl
import sys
from functools import lru_cache
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager


class NativeTrustHTTPSAdapter(HTTPAdapter):
    def __init__(self, ssl_context: ssl.SSLContext, **kwargs: Any) -> None:
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> None:
        pool_kwargs["ssl_context"] = self._ssl_context
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)


def _native_windows_ssl_context() -> ssl.SSLContext:
    import truststore

    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


@lru_cache(maxsize=1)
def _trusted_session() -> requests.Session:
    session = requests.Session()
    if sys.platform == "win32":
        session.mount("https://", NativeTrustHTTPSAdapter(_native_windows_ssl_context()))
    return session


def get(url: str, **kwargs: Any) -> requests.Response:
    return _trusted_session().get(url, **kwargs)
