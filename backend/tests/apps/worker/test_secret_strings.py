# SPDX-License-Identifier: Apache-2.0
"""What of a secret URL joins the run's secret index (plugins-3 D5): the URL, and its path, path segments and query
values of 8 characters or more, each as written (percent-encoded) and decoded, since an output could repeat either
(the 3c-1 review, finding 5)."""

from dewpoint.apps.worker.network import secret_strings

TOKEN = "c" * 20


def test_a_query_values_raw_and_decoded_forms_are_secrets() -> None:
    url = f"https://chat.googleapis.com/v1/spaces/AAAAbCd12/messages?key=AIzaSyKKKK&token={TOKEN}%3D"
    found = secret_strings({"webhook_url": url})
    assert {url, f"{TOKEN}%3D", f"{TOKEN}=", "AIzaSyKKKK", "AAAAbCd12"} <= set(found)


def test_a_path_segments_raw_and_decoded_forms_are_secrets() -> None:
    url = f"https://hooks.example.com/in/{TOKEN}%2Fx%20y"
    found = set(secret_strings({"url": url}))
    assert {f"{TOKEN}%2Fx%20y", f"/in/{TOKEN}%2Fx%20y", TOKEN, f"/in/{TOKEN}/x y"} <= found


def test_short_parts_alone_arent_secrets() -> None:
    found = secret_strings({"url": "https://hooks.example.com/in/abc?k=xyz"})
    assert found == ["https://hooks.example.com/in/abc?k=xyz"]
