# SPDX-License-Identifier: Apache-2.0
"""A Mist node's title and its path values' field titles: the operationId, or the value's name, in words."""

import re

import pytest

from dewpoint.plugins.mist import oas
from dewpoint.plugins.mist.titles import TERMS, title, words

OPS = oas.operations().values()
NAMES = sorted({op.id for op in OPS} | {p["name"] for op in OPS for p in op.parameters if p["in"] == "path"})


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("listOrgSites", "List org sites"),
        ("getOrgWLAN", "Get org WLAN"),
        ("getSiteRogueAP", "Get site rogue AP"),
        ("listSiteRogueAPs", "List site rogue APs"),  # an acronym's plural
        ("createOrgAAMWProfile", "Create org AAMW profile"),  # an acronym's last capital starting a word
        ("getOrgE911Report", "Get org E911 report"),  # a capital and digits
        ("deauthSiteWirelessClientsConnectedToARogue", "Deauth site wireless clients connected to a rogue"),
        ("clearSiteDeviceDot1xSession", "Clear site device dot1x session"),  # the API's term, as wxtag
        ("vbeacon_id", "Vbeacon ID"),  # a path value's name is the API's, compound included
    ],
)
def test_a_title_is_the_operation_id_in_words(name: str, expected: str) -> None:
    assert title(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # The owner's spellings (2026-10-09).
        ("getOrgCurrentMatchingClientsOfAWxTag", "Get org current matching clients of a wxtag"),
        ("createSiteVBeacon", "Create site vBeacon"),
        ("getOrg128TRegistrationCommands", "Get org 128T registration commands"),
        ("sendOrgNacClientCoA", "Send org NAC client CoA"),
        ("listApLEslVersions", "List AP ESL versions"),  # the id's stray "L" dropped (its path: ap_esl_versions)
        ("listOrgPmaDashboards", "List org Premium Analytics dashboards"),  # the OAS's name, letters added
        # An acronym or a name the id writes as a word.
        ("createOrgNacRule", "Create org NAC rule"),
        ("showSiteGatewayOspfDatabase", "Show site gateway OSPF database"),
        ("getOrgSecIntelProfile", "Get org SecIntel profile"),
        ("getOrgMistScep", "Get org Mist SCEP"),
        ("getOrgAoscxRegisterCmd", "Get org AOS-CX register cmd"),
        ("generateSecretFor2faVerification", "Generate secret for 2FA verification"),
        ("linkOauth2MistAccount", "Link OAuth2 Mist account"),
        # Plurals: a term's last word with an "s".
        ("listOrgPsks", "List org PSKs"),
        ("listOrgWxTags", "List org wxtags"),
        ("listSiteVBeacons", "List site vBeacons"),
        # A two-word term over its words: "Mist Edge" over "Mist" (tried first), "SkyATP" over "ATP" (met first); and
        # only what the id says.
        ("searchOrgMistEdgeEvents", "Search org Mist Edge events"),
        ("getOrgSkyAtpIntegration", "Get org SkyATP integration"),
        ("getOrgMxEdgeCluster", "Get org mxedge cluster"),
        # A path value's name: whole words only.
        ("site_id", "Site ID"),
        ("guest_mac", "Guest MAC"),
        ("rogue_bssid", "Rogue BSSID"),
        ("fpc0_mac", "FPC0 MAC"),
    ],
)
def test_a_title_writes_mist_terms_as_mist_does(name: str, expected: str) -> None:
    assert title(name) == expected


def test_the_words_keep_every_letter_of_each_operation_id_and_path_value() -> None:
    """A character no word matched was skipped: "listSiteRogueAPs" lost its "A"."""
    assert [n for n in NAMES if "".join(words(n)).lower() != re.sub(r"[^a-z0-9]", "", n.lower())] == []


def test_every_term_is_reached_by_an_operation_id_or_a_path_value() -> None:
    """Reachability only, against a misspelled or dead key: the tables above pin how each term is written."""
    found = {" ".join(w.lower() for w in words(n)) for n in NAMES}

    def reached(key: str) -> bool:
        return any(re.search(rf"(?:^| ){re.escape(key)}s?(?: |$)", text) for text in found)

    assert [key for key in TERMS if not reached(key)] == []
