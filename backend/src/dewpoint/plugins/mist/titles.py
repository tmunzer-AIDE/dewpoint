# SPDX-License-Identifier: Apache-2.0
"""A Mist node's title and its path values' field titles: the operationId, or the value's name, in words, normalized
through reviewed Mist terminology (the plugins-3 ruling): a term the id writes as words ("Nac", "WxTag") is written as
Mist writes it ("NAC", "wxtag"); any other word keeps the id's acronym ("WLAN") or is lowercase."""

import re

ACRONYMS = (
    "ap api arp atp ble bgp bpdu bssid crl dhcp dns esl evpn fips fpc0 fpga gbp gw ha id idp jse jsi led mac ml msp nac"
    " ospf pbn pcap plf psk qr rf rrm rssi saml scep sdk sirt sle sms srx ssl sso ssr sw ui url vc vm vpn wan wlan ztp"
)
# A term's words, lowercase: how Mist writes them. A two-word term is tried before a one-word one.
TERMS: dict[str, str] = {
    **{a: a.upper() for a in ACRONYMS.split()},
    # The API's compounds (the owner's choice, 2026-10-09).
    "wx tag": "wxtag",
    "wx rule": "wxrule",
    "wx tunnel": "wxtunnel",
    "mx edge": "mxedge",
    "mx tunnel": "mxtunnel",
    "v beacon": "vBeacon",
    # Names, as Juniper writes them.
    "aoscx": "AOS-CX",
    "cradlepoint": "Cradlepoint",
    "edgeconnect": "EdgeConnect",
    "iot": "IoT",
    "marvis": "Marvis",
    "mist": "Mist",
    "mist edge": "Mist Edge",
    "oauth": "OAuth",
    "oauth2": "OAuth2",
    "pma": "Premium Analytics",  # the OAS's name for it: letters added
    "sec intel": "SecIntel",
    "sky atp": "SkyATP",
    "telstra": "Telstra",
    "twilio": "Twilio",
    "zigbee": "Zigbee",
    "zscaler": "Zscaler",
    # What the split can't part: CoA ends an id, 128T and 2FA follow a word.
    "co a": "CoA",
    "org128 t": "org 128T",
    "for2fa": "for 2FA",
    "l esl": "ESL",  # the id's stray "L" dropped: its path is ap_esl_versions
}


def words(name: str) -> list[str]:
    """An acronym, maybe plural ("APs"), a word, or a lone capital ("ToARogue"): every letter of `name` is in a word,
    and a snake_case name's underscores part them."""
    return re.findall(r"[A-Z]{2,}s?(?![a-z])|[A-Z]?[a-z0-9]+|[A-Z]", name)


def title(name: str) -> str:
    split = words(name)
    lower = [w.lower() for w in split]
    out: list[str] = []
    i = 0
    while i < len(split):
        for n in (2, 1):
            term = _term(" ".join(lower[i : i + n])) if i + n <= len(split) else None
            if term is not None:
                out.append(term)
                i += n
                break
        else:
            out.append(split[i] if re.fullmatch(r"[A-Z][A-Z0-9]+s?", split[i]) else lower[i])  # AP, APs, E911
            i += 1
    text = " ".join(out)
    return text[:1].upper() + text[1:]


def _term(key: str) -> str | None:
    """How Mist writes these words, the last one maybe plural ("psks": "PSKs")."""
    if key in TERMS:
        return TERMS[key]
    if key.endswith("s") and key[:-1] in TERMS:
        return TERMS[key[:-1]] + "s"
    return None
