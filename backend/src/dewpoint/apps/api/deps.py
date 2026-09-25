# SPDX-License-Identifier: Apache-2.0
from fastapi import Request

from dewpoint.core.crypto.keyring import Keyring


def get_keyring(request: Request) -> Keyring:
    return request.app.state.keyring  # type: ignore[no-any-return]
