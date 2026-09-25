# SPDX-License-Identifier: Apache-2.0
import dewpoint


def test_package_exposes_version() -> None:
    assert dewpoint.__version__ == "0.1.0"
