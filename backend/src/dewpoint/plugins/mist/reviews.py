# SPDX-License-Identifier: Apache-2.0
"""The reviewed Mist operations (plugins-3 D28, D24, D14, D27): the curated operations and the node each is reached by,
the device utilities and their reviews, the operations the owner holds back, and the evidence for each side effect.
`make_map()` turns them and the vendored OAS into the operation-policy map, `data/policy.json`; `python -m
dewpoint.plugins.mist.reviews` writes it, and a test refuses drift. Every operation nobody reviewed is held (D28 a),
reads included."""

import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.plugins.mist import oas, policy, routing

# The curated operations (the outline's appendix, 0613a22): (operationId, its node type). Each is allowed to that node
# and to the any-endpoint node of its method (D14): `mist.api.read` for a GET, `mist.api.write` for any other.
CURATED: tuple[tuple[str, str], ...] = (
    ("getOrg", "mist.org.get"),
    ("listOrgSites", "mist.org_sites.list"),
    ("createOrgSite", "mist.org_sites.create"),
    ("listOrgSiteGroups", "mist.org_sitegroups.list"),
    ("searchOrgDevices", "mist.org_devices.search"),
    ("getOrgInventory", "mist.org_inventory.list"),
    ("listOrgWlans", "mist.org_wlans.list"),
    ("getOrgWLAN", "mist.org_wlans.get"),
    ("createOrgWlan", "mist.org_wlans.create"),
    ("updateOrgWlan", "mist.org_wlans.update"),
    ("deleteOrgWlan", "mist.org_wlans.delete"),
    ("listOrgTemplates", "mist.org_wlan_templates.list"),
    ("getOrgTemplate", "mist.org_wlan_templates.get"),
    ("createOrgTemplate", "mist.org_wlan_templates.create"),
    ("updateOrgTemplate", "mist.org_wlan_templates.update"),
    ("deleteOrgTemplate", "mist.org_wlan_templates.delete"),
    ("listOrgNetworkTemplates", "mist.org_network_templates.list"),
    ("getOrgNetworkTemplate", "mist.org_network_templates.get"),
    ("createOrgNetworkTemplate", "mist.org_network_templates.create"),
    ("updateOrgNetworkTemplate", "mist.org_network_templates.update"),
    ("deleteOrgNetworkTemplate", "mist.org_network_templates.delete"),
    ("listOrgRfTemplates", "mist.org_rf_templates.list"),
    ("getOrgRfTemplate", "mist.org_rf_templates.get"),
    ("createOrgRfTemplate", "mist.org_rf_templates.create"),
    ("updateOrgRfTemplate", "mist.org_rf_templates.update"),
    ("deleteOrgRfTemplate", "mist.org_rf_templates.delete"),
    ("listOrgGatewayTemplates", "mist.org_gateway_templates.list"),
    ("getOrgGatewayTemplate", "mist.org_gateway_templates.get"),
    ("createOrgGatewayTemplate", "mist.org_gateway_templates.create"),
    ("updateOrgGatewayTemplate", "mist.org_gateway_templates.update"),
    ("deleteOrgGatewayTemplate", "mist.org_gateway_templates.delete"),
    ("listOrgSiteTemplates", "mist.org_site_templates.list"),
    ("getOrgSiteTemplate", "mist.org_site_templates.get"),
    ("createOrgSiteTemplate", "mist.org_site_templates.create"),
    ("updateOrgSiteTemplate", "mist.org_site_templates.update"),
    ("deleteOrgSiteTemplate", "mist.org_site_templates.delete"),
    ("listOrgDeviceProfiles", "mist.org_device_profiles.list"),
    ("getOrgDeviceProfile", "mist.org_device_profiles.get"),
    ("createOrgDeviceProfile", "mist.org_device_profiles.create"),
    ("updateOrgDeviceProfile", "mist.org_device_profiles.update"),
    ("deleteOrgDeviceProfile", "mist.org_device_profiles.delete"),
    ("listOrgPsks", "mist.org_psks.list"),
    ("getOrgPsk", "mist.org_psks.get"),
    ("createOrgPsk", "mist.org_psks.create"),
    ("updateOrgPsk", "mist.org_psks.update"),
    ("deleteOrgPsk", "mist.org_psks.delete"),
    ("listOrgNetworks", "mist.org_networks.list"),
    ("getOrgNetwork", "mist.org_networks.get"),
    ("createOrgNetwork", "mist.org_networks.create"),
    ("updateOrgNetwork", "mist.org_networks.update"),
    ("deleteOrgNetwork", "mist.org_networks.delete"),
    ("listOrgServices", "mist.org_services.list"),
    ("getOrgService", "mist.org_services.get"),
    ("createOrgService", "mist.org_services.create"),
    ("updateOrgService", "mist.org_services.update"),
    ("deleteOrgService", "mist.org_services.delete"),
    ("listOrgServicePolicies", "mist.org_service_policies.list"),
    ("getOrgServicePolicy", "mist.org_service_policies.get"),
    ("createOrgServicePolicy", "mist.org_service_policies.create"),
    ("updateOrgServicePolicy", "mist.org_service_policies.update"),
    ("deleteOrgServicePolicy", "mist.org_service_policies.delete"),
    ("listOrgSecPolicies", "mist.org_sec_policies.list"),
    ("getOrgSecPolicy", "mist.org_sec_policies.get"),
    ("createOrgSecPolicy", "mist.org_sec_policies.create"),
    ("updateOrgSecPolicy", "mist.org_sec_policies.update"),
    ("deleteOrgSecPolicy", "mist.org_sec_policies.delete"),
    ("listOrgIdpProfiles", "mist.org_idp_profiles.list"),
    ("getOrgIdpProfile", "mist.org_idp_profiles.get"),
    ("createOrgIdpProfile", "mist.org_idp_profiles.create"),
    ("updateOrgIdpProfile", "mist.org_idp_profiles.update"),
    ("deleteOrgIdpProfile", "mist.org_idp_profiles.delete"),
    ("listOrgAAMWProfiles", "mist.org_aamw_profiles.list"),
    ("getOrgAAMWProfile", "mist.org_aamw_profiles.get"),
    ("createOrgAAMWProfile", "mist.org_aamw_profiles.create"),
    ("updateOrgAAMWProfile", "mist.org_aamw_profiles.update"),
    ("deleteOrgAAMWProfile", "mist.org_aamw_profiles.delete"),
    ("listOrgSecIntelProfiles", "mist.org_secintel_profiles.list"),
    ("getOrgSecIntelProfile", "mist.org_secintel_profiles.get"),
    ("createOrgSecIntelProfile", "mist.org_secintel_profiles.create"),
    ("updateOrgSecIntelProfile", "mist.org_secintel_profiles.update"),
    ("deleteOrgSecIntelProfile", "mist.org_secintel_profiles.delete"),
    ("listOrgNacRules", "mist.org_nac_rules.list"),
    ("getOrgNacRule", "mist.org_nac_rules.get"),
    ("createOrgNacRule", "mist.org_nac_rules.create"),
    ("updateOrgNacRule", "mist.org_nac_rules.update"),
    ("deleteOrgNacRule", "mist.org_nac_rules.delete"),
    ("listOrgNacTags", "mist.org_nac_tags.list"),
    ("getOrgNacTag", "mist.org_nac_tags.get"),
    ("createOrgNacTag", "mist.org_nac_tags.create"),
    ("updateOrgNacTag", "mist.org_nac_tags.update"),
    ("deleteOrgNacTag", "mist.org_nac_tags.delete"),
    ("searchOrgUserMacs", "mist.org_usermacs.search"),
    ("getOrgUserMac", "mist.org_usermacs.get"),
    ("createOrgUserMac", "mist.org_usermacs.create"),
    ("updateOrgUserMac", "mist.org_usermacs.update"),
    ("deleteOrgUserMac", "mist.org_usermacs.delete"),
    ("listOrgGuestAuthorizations", "mist.org_guests.list"),
    ("searchOrgGuestAuthorization", "mist.org_guests.search"),
    ("getOrgGuestAuthorization", "mist.org_guests.get"),
    ("updateOrgGuestAuthorization", "mist.org_guests.update"),
    ("deleteOrgGuestAuthorization", "mist.org_guests.delete"),
    ("listOrgAssets", "mist.org_assets.list"),
    ("getOrgAsset", "mist.org_assets.get"),
    ("createOrgAsset", "mist.org_assets.create"),
    ("updateOrgAsset", "mist.org_assets.update"),
    ("deleteOrgAsset", "mist.org_assets.delete"),
    ("listOrgAssetFilters", "mist.org_asset_filters.list"),
    ("getOrgAssetFilter", "mist.org_asset_filters.get"),
    ("createOrgAssetFilter", "mist.org_asset_filters.create"),
    ("updateOrgAssetFilter", "mist.org_asset_filters.update"),
    ("deleteOrgAssetFilter", "mist.org_asset_filters.delete"),
    ("listOrgMxEdges", "mist.org_mxedges.list"),
    ("getOrgMxEdge", "mist.org_mxedges.get"),
    ("createOrgMxEdge", "mist.org_mxedges.create"),
    ("updateOrgMxEdge", "mist.org_mxedges.update"),
    ("deleteOrgMxEdge", "mist.org_mxedges.delete"),
    ("listOrgMxEdgeClusters", "mist.org_mxclusters.list"),
    ("getOrgMxEdgeCluster", "mist.org_mxclusters.get"),
    ("createOrgMxEdgeCluster", "mist.org_mxclusters.create"),
    ("updateOrgMxEdgeCluster", "mist.org_mxclusters.update"),
    ("deleteOrgMxEdgeCluster", "mist.org_mxclusters.delete"),
    ("listOrgMxTunnels", "mist.org_mxtunnels.list"),
    ("getOrgMxTunnel", "mist.org_mxtunnels.get"),
    ("createOrgMxTunnel", "mist.org_mxtunnels.create"),
    ("updateOrgMxTunnel", "mist.org_mxtunnels.update"),
    ("deleteOrgMxTunnel", "mist.org_mxtunnels.delete"),
    ("listOrgWxRules", "mist.org_wxrules.list"),
    ("getOrgWxRule", "mist.org_wxrules.get"),
    ("createOrgWxRule", "mist.org_wxrules.create"),
    ("updateOrgWxRule", "mist.org_wxrules.update"),
    ("deleteOrgWxRule", "mist.org_wxrules.delete"),
    ("listOrgWxTags", "mist.org_wxtags.list"),
    ("getOrgWxTag", "mist.org_wxtags.get"),
    ("createOrgWxTag", "mist.org_wxtags.create"),
    ("updateOrgWxTag", "mist.org_wxtags.update"),
    ("deleteOrgWxTag", "mist.org_wxtags.delete"),
    ("listOrgAlarmTemplates", "mist.org_alarm_templates.list"),
    ("getOrgAlarmTemplate", "mist.org_alarm_templates.get"),
    ("createOrgAlarmTemplate", "mist.org_alarm_templates.create"),
    ("updateOrgAlarmTemplate", "mist.org_alarm_templates.update"),
    ("deleteOrgAlarmTemplate", "mist.org_alarm_templates.delete"),
    ("searchOrgAlarms", "mist.org_alarms.search"),
    ("ackOrgAlarm", "mist.org_alarms.ack"),
    ("searchOrgWirelessClients", "mist.org_wireless_clients.search"),
    ("countOrgWirelessClients", "mist.org_wireless_clients.count"),
    ("searchOrgWiredClients", "mist.org_wired_clients.search"),
    ("countOrgWiredClients", "mist.org_wired_clients.count"),
    ("searchOrgNacClients", "mist.org_nac_clients.search"),
    ("countOrgNacClients", "mist.org_nac_clients.count"),
    ("searchOrgWanClients", "mist.org_wan_clients.search"),
    ("countOrgWanClients", "mist.org_wan_clients.count"),
    ("searchOrgEvents", "mist.org_events.search"),
    ("searchOrgDeviceEvents", "mist.org_device_events.search"),
    ("countOrgDeviceEvents", "mist.org_device_events.count"),
    ("searchOrgWirelessClientEvents", "mist.org_wireless_client_events.search"),
    ("countOrgWirelessClientEvents", "mist.org_wireless_client_events.count"),
    ("searchOrgNacClientEvents", "mist.org_nac_client_events.search"),
    ("countOrgNacClientEvents", "mist.org_nac_client_events.count"),
    ("searchOrgWanClientEvents", "mist.org_wan_client_events.search"),
    ("searchOrgMistEdgeEvents", "mist.org_mxedge_events.search"),
    ("countOrgSiteMxEdgeEvents", "mist.org_mxedge_events.count"),
    ("listOrgAuditLogs", "mist.org_audit_logs.search"),
    ("countOrgAuditLogs", "mist.org_audit_logs.count"),
    ("getOrgStats", "mist.org_stats.get"),
    ("listOrgSiteStats", "mist.org_site_stats.list"),
    ("listOrgDevicesStats", "mist.org_device_stats.list"),
    ("listOrgAssetsStats", "mist.org_asset_stats.list"),
    ("listOrgMxEdgesStats", "mist.org_mxedge_stats.list"),
    ("listOrgWebhooks", "mist.org_webhooks.list"),
    ("getOrgWebhook", "mist.org_webhooks.get"),
    ("createOrgWebhook", "mist.org_webhooks.create"),
    ("updateOrgWebhook", "mist.org_webhooks.update"),
    ("deleteOrgWebhook", "mist.org_webhooks.delete"),
    ("listWebhookTopics", "mist.const_webhook_topics.list"),
    ("getSiteInfo", "mist.site.get"),
    ("updateSiteInfo", "mist.site.update"),
    ("deleteSite", "mist.site.delete"),
    ("getSiteSetting", "mist.site_settings.get"),
    ("updateSiteSettings", "mist.site_settings.update"),
    ("listSiteDevices", "mist.site_devices.list"),
    ("getSiteDevice", "mist.site_devices.get"),
    ("updateSiteDevice", "mist.site_devices.update"),
    ("restartSiteDevice", "mist.site_devices.restart"),
    ("listSiteWlans", "mist.site_wlans.list"),
    ("getSiteWlan", "mist.site_wlans.get"),
    ("createSiteWlan", "mist.site_wlans.create"),
    ("updateSiteWlan", "mist.site_wlans.update"),
    ("deleteSiteWlan", "mist.site_wlans.delete"),
    ("listSitePsks", "mist.site_psks.list"),
    ("getSitePsk", "mist.site_psks.get"),
    ("createSitePsk", "mist.site_psks.create"),
    ("updateSitePsk", "mist.site_psks.update"),
    ("deleteSitePsk", "mist.site_psks.delete"),
    ("listSiteMaps", "mist.site_maps.list"),
    ("getSiteMap", "mist.site_maps.get"),
    ("createSiteMap", "mist.site_maps.create"),
    ("updateSiteMap", "mist.site_maps.update"),
    ("deleteSiteMap", "mist.site_maps.delete"),
    ("listSiteMapStacks", "mist.site_mapstacks.list"),
    ("getSiteMapStack", "mist.site_mapstacks.get"),
    ("createSiteMapStack", "mist.site_mapstacks.create"),
    ("updateSiteMapStack", "mist.site_mapstacks.update"),
    ("deleteSiteMapStack", "mist.site_mapstacks.delete"),
    ("listSiteAssets", "mist.site_assets.list"),
    ("getSiteAsset", "mist.site_assets.get"),
    ("createSiteAsset", "mist.site_assets.create"),
    ("updateSiteAsset", "mist.site_assets.update"),
    ("deleteSiteAsset", "mist.site_assets.delete"),
    ("listSiteAssetFilters", "mist.site_asset_filters.list"),
    ("getSiteAssetFilter", "mist.site_asset_filters.get"),
    ("createSiteAssetFilter", "mist.site_asset_filters.create"),
    ("updateSiteAssetFilter", "mist.site_asset_filters.update"),
    ("deleteSiteAssetFilter", "mist.site_asset_filters.delete"),
    ("listSiteWxRules", "mist.site_wxrules.list"),
    ("getSiteWxRule", "mist.site_wxrules.get"),
    ("createSiteWxRule", "mist.site_wxrules.create"),
    ("updateSiteWxRule", "mist.site_wxrules.update"),
    ("deleteSiteWxRule", "mist.site_wxrules.delete"),
    ("ListSiteWxRulesDerived", "mist.site_wxrules.list_derived"),
    ("listSiteWxTags", "mist.site_wxtags.list"),
    ("getSiteWxTag", "mist.site_wxtags.get"),
    ("createSiteWxTag", "mist.site_wxtags.create"),
    ("updateSiteWxTag", "mist.site_wxtags.update"),
    ("deleteSiteWxTag", "mist.site_wxtags.delete"),
    ("listSiteMxEdges", "mist.site_mxedges.list"),
    ("getSiteMxEdge", "mist.site_mxedges.get"),
    ("updateSiteMxEdge", "mist.site_mxedges.update"),
    ("deleteSiteMxEdge", "mist.site_mxedges.delete"),
    ("searchSiteMistEdgeEvents", "mist.site_mxedge_events.search"),
    ("countSiteMxEdgeEvents", "mist.site_mxedge_events.count"),
    ("searchSiteWirelessClients", "mist.site_wireless_clients.search"),
    ("countSiteWirelessClients", "mist.site_wireless_clients.count"),
    ("searchSiteWiredClients", "mist.site_wired_clients.search"),
    ("countSiteWiredClients", "mist.site_wired_clients.count"),
    ("searchSiteNacClients", "mist.site_nac_clients.search"),
    ("countSiteNacClients", "mist.site_nac_clients.count"),
    ("searchSiteWanClients", "mist.site_wan_clients.search"),
    ("countSiteWanClients", "mist.site_wan_clients.count"),
    ("listSiteRogueAPs", "mist.site_rogue_aps.list"),
    ("listSiteRogueClients", "mist.site_rogue_clients.list"),
    ("getSiteRogueAP", "mist.site_rogue_aps.get"),
    ("searchSiteRogueEvents", "mist.site_rogue_events.search"),
    ("countSiteRogueEvents", "mist.site_rogue_events.count"),
    ("getSiteInsightMetrics", "mist.site_insights.get"),
    ("getSiteInsightMetricsForAP", "mist.site_insights.ap"),
    ("getSiteInsightMetricsForClient", "mist.site_insights.client"),
    ("getSiteInsightMetricsForDevice", "mist.site_insights.device"),
    ("getSiteInsightMetricsForGateway", "mist.site_insights.gateway"),
    ("getSiteInsightMetricsForMxEdge", "mist.site_insights.mxedge"),
    ("getSiteInsightMetricsForSwitch", "mist.site_insights.switch"),
    ("getSiteStats", "mist.site_stats.get"),
    ("listSiteDevicesStats", "mist.site_device_stats.list"),
    ("listSiteWirelessClientsStats", "mist.site_wireless_client_stats.list"),
    ("listSiteMxEdgesStats", "mist.site_mxedge_stats.list"),
    ("listSiteAssetsStats", "mist.site_asset_stats.list"),
    ("listSiteBeaconsStats", "mist.site_beacon_stats.list"),
    ("listSiteDiscoveredAssets", "mist.site_discovered_assets.list"),
    ("getSiteAssetsOfInterest", "mist.site_assets_of_interest.get"),
    ("listSiteZonesStats", "mist.site_zone_stats.list"),
    ("listSiteRssiZonesStats", "mist.site_rssizone_stats.list"),
    ("getSiteWxRulesUsage", "mist.site_wxrule_usage.list"),
    ("listSiteSpectrumAnalysis", "mist.site_spectrum_analysis.list"),
)


@dataclass(frozen=True)
class Utility:
    operation: str
    node: str
    kind: str  # "diagnostic" (mist.diagnose, idempotent) or "disruptive" (mist.write, ambiguous)
    contract: str  # policy.CONTRACTS
    device_types: tuple[str, ...]
    parameters: tuple[str, ...]
    bounds: Mapping[str, int]
    repeat: str
    evidence: str
    selectors: tuple[str, ...] = ()  # what scopes a disruptive command: required, never empty, never `all`


# The device utilities (D27, D28), each reviewed into the map: its node, whether it's a repeatable diagnostic
# (`mist.diagnose`, idempotent) or disruptive (`mist.write`, ambiguous), its contract, the device types it runs on (the
# OAS tag's: Common all three, LAN switches, WAN gateways, narrowed or widened by the description's own list), the body
# parameters it may send (the refresh `interval` and `duration` never), their maxima, what repeating it does, and the
# evidence. Allowed to its own node only, never to `mist.api.write`, which would bypass all of that.
ALL = ("ap", "gateway", "switch")
GATEWAY, SWITCH, LAN_WAN = ("gateway",), ("switch",), ("gateway", "switch")
STREAMED = "its 200 answers a `session`, its output streams on the device's `cmd` channel (OAS)"
UNENDED = "no end of output is documented: a bounded collection"
DURATION = {"max_duration_s": 240}
READS = "reads the device's state again and changes nothing"
UTILITIES: tuple[Utility, ...] = (
    Utility("pingFromDevice", "mist.site_devices.ping", "diagnostic", "bounded_collection", ALL,
            ("count", "egress_interface", "host", "node", "size", "use_ipv6", "vrf"), {"count": 100, **DURATION},
            "sends `count` more echo requests from the device; no configuration or state changes",
            f'"Ping from AP, Switch and SSR"; {STREAMED}; the docs sample shows echo lines and {UNENDED}'),
    Utility("tracerouteFromDevice", "mist.site_devices.traceroute", "diagnostic", "bounded_collection", ALL,
            ("host", "network", "node", "port", "protocol", "timeout", "use_ipv6", "vrf"), {"timeout": 120, **DURATION},
            "sends more probes from the device; no configuration or state changes",
            f"traceroute performed from the device (Utilities Common); {STREAMED}; the docs sample shows hops and "
            f"{UNENDED}"),
    Utility("arpFromDevice", "mist.site_devices.arp", "diagnostic", "bounded_collection", ALL, ("node",), DURATION,
            READS, f"ARP performed on the device (Utilities Common); {STREAMED}; the docs sample is a text table and "
            f"{UNENDED}"),
    Utility("showSiteDeviceArpTable", "mist.site_devices.show_arp", "diagnostic", "stream_terminal_evidence", LAN_WAN,
            ("ip", "node", "port_id", "vrf"), DURATION, READS,
            f"the ARP table from the device (Utilities LAN, its `node` required for gateways); {STREAMED}; the docs "
            'sample ends its table with "finished": true and "status": "SUCCESS": stream terminal evidence'),
    Utility("showSiteDeviceBgpSummary", "mist.site_devices.show_bgp_summary", "diagnostic", "bounded_collection",
            LAN_WAN, ("node",), DURATION, READS,
            f'"Get BGP Summary from SSR, SRX and Switch"; {STREAMED}; the docs sample is text and {UNENDED}'),
    Utility("showSiteDeviceDhcpLeases", "mist.site_devices.show_dhcp_leases", "diagnostic", "bounded_collection", ALL,
            ("network", "node"), DURATION, READS, f'"Shows DHCP leases" (Utilities Common); {STREAMED}; {UNENDED}'),
    Utility("showSiteDeviceDot1xTable", "mist.site_devices.show_dot1x", "diagnostic", "bounded_collection", ALL,
            ("port_id",), DURATION, READS, f"the 802.1X table (Utilities Common); {STREAMED}; {UNENDED}"),
    Utility("showSiteDeviceEvpnDatabase", "mist.site_devices.show_evpn_database", "diagnostic", "bounded_collection",
            ALL, ("mac", "port_id"), DURATION, READS,
            f"the EVPN database (Utilities Common); {STREAMED}; {UNENDED}"),
    Utility("showSiteDeviceForwardingTable", "mist.site_devices.show_forwarding_table", "diagnostic",
            "bounded_collection", ALL,
            ("node", "prefix", "service_ip", "service_name", "service_port", "service_protocol", "service_tenant",
             "vrf"), DURATION, READS, f"the forwarding table (Utilities Common); {STREAMED}; {UNENDED}"),
    Utility("showSiteDeviceMacTable", "mist.site_devices.show_mac_table", "diagnostic", "bounded_collection", ALL,
            ("mac_address", "port_id", "vlan_id"), DURATION, READS,
            f"the MAC table (Utilities Common); {STREAMED}; {UNENDED}"),
    Utility("showSiteGatewayOspfDatabase", "mist.site_devices.show_ospf_database", "diagnostic", "bounded_collection",
            GATEWAY, ("node", "self_originate", "vrf"), DURATION, READS,
            f"a gateway's OSPF database (Utilities WAN); {STREAMED}; {UNENDED}"),
    Utility("showSiteGatewayOspfInterfaces", "mist.site_devices.show_ospf_interfaces", "diagnostic",
            "bounded_collection", GATEWAY, ("node", "port_id", "vrf"), DURATION, READS,
            f"a gateway's OSPF interfaces (Utilities WAN); {STREAMED}; {UNENDED}"),
    Utility("showSiteGatewayOspfNeighbors", "mist.site_devices.show_ospf_neighbors", "diagnostic",
            "bounded_collection", GATEWAY, ("neighbor", "node", "port_id", "vrf"), DURATION, READS,
            f"a gateway's OSPF neighbors (Utilities WAN); {STREAMED}; {UNENDED}"),
    Utility("showSiteGatewayOspfSummary", "mist.site_devices.show_ospf_summary", "diagnostic", "bounded_collection",
            GATEWAY, ("node", "vrf"), DURATION, READS,
            f"a gateway's OSPF summary (Utilities WAN); {STREAMED}; {UNENDED}"),
    Utility("showSiteSsrAndSrxRoutes", "mist.site_devices.show_route", "diagnostic", "bounded_collection", GATEWAY,
            ("neighbor", "prefix", "protocol", "route", "vrf"), DURATION, READS,
            f"an SSR's or SRX's routes (Utilities WAN); {STREAMED}; {UNENDED}"),
    Utility("showSiteSsrServicePath", "mist.site_devices.show_service_path", "diagnostic", "stream_terminal_evidence",
            GATEWAY, ("node", "service_name"), DURATION, READS,
            f"an SSR's service path (Utilities WAN); {STREAMED}; the docs sample ends its table with "
            '"finished": true and "status": "SUCCESS": stream terminal evidence'),
    Utility("showSiteSsrAndSrxSessions", "mist.site_devices.show_session", "diagnostic", "stream_terminal_evidence",
            GATEWAY, ("node", "service_name", "session_id"), DURATION, READS,
            f"an SSR's or SRX's sessions (Utilities WAN); {STREAMED}; the docs sample ends its table with "
            '"finished": true and "status": "SUCCESS": stream terminal evidence'),
    Utility("servicePingFromSsr", "mist.site_devices.service_ping", "diagnostic", "bounded_collection", GATEWAY,
            ("count", "host", "node", "service", "size", "tenant"), {"count": 100, **DURATION},
            "sends `count` more echo requests along the service's path; no configuration or state changes",
            f'"Ping from SSR" (Utilities WAN); {STREAMED}; the docs sample shows echo lines and {UNENDED}'),
    Utility("testSiteSsrDnsResolution", "mist.site_devices.resolve_dns", "diagnostic", "bounded_collection", GATEWAY,
            (), DURATION, "resolves the device's names again; no configuration changes",
            f"DNS resolutions performed on an SSR (Utilities WAN), no body; {STREAMED}; the docs sample is a text "
            f"table and {UNENDED}"),
    Utility("bounceDevicePort", "mist.site_devices.bounce_port", "disruptive", "acceptance_only", LAN_WAN,
            ("ports",), {}, "bounces the ports again: each bounce takes their links down",
            "port bounce from a switch or gateway (Utilities Common; vme, ae, irb and SSR HA control ports "
            "unsupported); its 200 answers nothing in the OAS, while the docs sample streams \"Port bounce "
            "complete.\" (unverified); no completion documented: acceptance only",
            selectors=('ports',)),
    Utility("cableTestFromSwitch", "mist.site_devices.cable_test", "disruptive", "acceptance_only", SWITCH, ("port",),
            {}, "runs the TDR test on the port again",
            f"TDR from a switch (Utilities LAN); {STREAMED}; no final message documented: acceptance only",
            selectors=('port',)),
    Utility("clearSiteDeviceMacTable", "mist.site_devices.clear_mac_table", "disruptive", "acceptance_only", ALL,
            ("mac_address", "port_id", "vlan_id"), {}, "clears the MAC table's entries again; the device learns them "
            "again", f"clears the MAC table (Utilities Common); {STREAMED}; no completion documented: acceptance only",
            selectors=('port_id',)),
    Utility("clearAllLearnedMacsFromPortOnSwitch", "mist.site_devices.clear_macs", "disruptive", "acceptance_only",
            SWITCH, ("ports",), {}, "clears the ports' learned MACs, persistent ones included, again",
            "clears every learned MAC of a port (Utilities LAN); its 200 answers nothing; no completion documented: "
            "acceptance only",
            selectors=('ports',)),
    Utility("clearBpduErrorsFromPortsOnSwitch", "mist.site_devices.clear_bpdu_error", "disruptive", "acceptance_only",
            SWITCH, ("ports",), {}, "clears the ports' BPDU error state again",
            "clears a BPDU error that disabled a port (Utilities LAN); its 200 answers nothing; no completion "
            "documented: acceptance only",
            selectors=('ports',)),
    Utility("clearSiteDeviceDot1xSession", "mist.site_devices.clear_dot1x", "disruptive", "acceptance_only", SWITCH,
            ("ports",), {}, "ends the ports' 802.1X sessions again; their clients authenticate again",
            f"clears 802.1X sessions (Utilities LAN); {STREAMED}; no completion documented: acceptance only",
            selectors=('ports',)),
    Utility("releaseSiteDeviceDhcpLease", "mist.site_devices.release_dhcp_leases", "disruptive", "acceptance_only",
            ALL, ("macs", "network", "node", "port_id"), {}, "releases the leases again",
            '"Releases an active DHCP lease" (Utilities Common); its 200 answers nothing; no completion documented: '
            "acceptance only",
            selectors=('port_id',)),
    Utility("releaseSiteSsrDhcpLease", "mist.site_devices.release_dhcp", "disruptive", "acceptance_only", GATEWAY,
            ("node", "port_id"), {}, "releases the interface's lease again",
            f'"Releases an active DHCP lease" (Utilities WAN); {STREAMED}; no completion documented: acceptance only',
            selectors=('port_id',)),
    Utility("clearSiteDeviceSession", "mist.site_devices.clear_session", "disruptive", "acceptance_only", GATEWAY,
            ("node", "service_name", "session_ids"), {}, "clears the sessions again",
            '"Clear session" (Utilities WAN); its 200 answers nothing; no completion documented: acceptance only',
            selectors=('session_ids',)),
    Utility("clearSiteSsrArpCache", "mist.site_devices.clear_arp", "disruptive", "acceptance_only", LAN_WAN,
            ("ip", "node", "port_id", "vlan", "vrf"), {}, "clears the ARP entries again; the device learns them again",
            f'"Clear ARP cache for SSR, SRX and Switch"; {STREAMED}; no completion documented: acceptance only',
            selectors=('port_id',)),
    Utility("clearSiteSsrBgpRoutes", "mist.site_devices.clear_bgp", "disruptive", "acceptance_only", GATEWAY,
            ("neighbor", "node", "type", "vrf"), {},
            "resets the BGP sessions again: their routes are withdrawn and learnt again",
            f"clears the routes of one or all BGP neighbors (Utilities WAN); {STREAMED}; no completion documented: "
            "acceptance only",
            selectors=('neighbor',)),
)  # fmt: skip

UTILITY_PATH = re.compile(r"^/api/v1/sites/\{site_id\}/devices/\{device_id\}/[a-z0-9_]+$")
REFRESH = frozenset({"interval", "duration"})  # repeated output for up to 300 s: no contract bounds it yet
SELECTOR_TYPES = ("string", "array")  # a port, a neighbor; a list of ports or sessions
DEVICE_CHECK = "getSiteDevice"  # the read that checks a utility's device type before anything else is sent
KINDS = {"diagnostic": ("mist.diagnose", "idempotent"), "disruptive": ("mist.write", "ambiguous")}

# Held back for the owner (D24): unavailable to every node. The deprecated audit-log list (`listOrgAuditLogsLegacy`),
# which the appendix also holds, is denied as every deprecated operation is.
HELD: dict[str, str] = {
    "addOrgInventory": "claims devices into the org (activation codes)",
    "updateOrgInventoryAssignment": "assigns and unassigns devices, and can delete inventory records",
    "deauthSiteWirelessClientsConnectedToARogue": "a radio action against clients",
    "deleteOrgPskList": "an empty list deletes every org PSK",
    "updateOrgMultiplePsks": "a bulk form; the single-object node covers it",
    "updateSiteMultiplePsks": "a bulk form; the single-object node covers it",
    "importSitePsks": "a CSV or multipart import",
    "updateOrgMultipleUserMacs": "a bulk form; the single-object node covers it",
    "deleteOrgMarvisClient": "deletes Marvis client stats",
    "uploadSiteMxEdgeSupportFiles": "a support upload",
    "upgradeSiteMxEdges": "a firmware upgrade",
    "upgradeDevice": "a firmware upgrade",
    # The device utilities D27 holds back (the ZTP password's is always refused, which is stricter):
    "createSiteDeviceShellSession": "an interactive shell (D27)",
    "getSiteDeviceConfigCmd": "the full CLI configuration, which may hold secrets (D27)",
    "uploadSiteDeviceSupportFile": "a support upload (D27)",
    "zeroizeSiteFipsAllAps": "a FIPS zeroize of every AP (D27)",
    "reprovisionSiteOctermDevice": "a reprovision (D27)",
    "readoptSiteOctermDevice": "a re-adoption (D27)",
    "restoreSiteDeviceBackupVersion": "a firmware rollback (D27)",
    "toogleSiteDeviceVcRoutingEnginesRole": "a virtual chassis master switchover (D27)",
    "startSitePacketCapture": "a packet capture stream, later (D27)",
    "monitorSiteDeviceTraffic": "streams through a separate JWT URL whose protocol is undocumented (D27)",
    "runSiteSrxTopCommand": "streams through a separate JWT URL whose protocol is undocumented (D27)",
    "clearSiteDevicePolicyHitCount": "streams through a separate JWT URL whose protocol is undocumented (D27)",
}

# Each side effect's evidence (D16): the HTTP method alone is no evidence, so each kind cites what it rests on.
EVIDENCE: dict[str, str] = {
    "none": "A GET, a safe method (RFC 9110 9.2.1), which Mist's API overview maps to Read.",
    "idempotent": (
        "A PUT, documented as updating only the fields sent (outline D15: Juniper's REST overview, the OAS's"
        " updateSiteInfo), so the same body leaves the same state; or a DELETE (RFC 9110 9.2.2), whose 404 on a retry"
        " reads as applied or already absent."
    ),
    "ambiguous": (
        "A POST: a create makes a new object each time and no marker field is verified for reconcile(); an action's"
        " repeated effect isn't documented."
    ),
}
SIDE_EFFECTS = {"GET": "none", "PUT": "idempotent", "DELETE": "idempotent", "POST": "ambiguous"}


class ReviewError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def make_map() -> dict[str, Any]:
    """The policy map the reviews and the vendored OAS make. A review of an operation that doesn't exist, is
    deprecated, held or always refused, or has no scope class, fails the build."""
    ops = oas.operations()
    curated = dict(CURATED)
    utilities = {u.operation: u for u in UTILITIES}
    problems: list[str] = []
    nodes = [*curated.values(), *(u.node for u in UTILITIES)]
    if (
        len(curated) != len(CURATED)
        or len(utilities) != len(UTILITIES)
        or len(set(nodes)) != len(nodes)
        or (set(curated) & set(utilities))
    ):
        problems.append("a duplicate review or node type")
    problems += [f"{op_id}: no such operation" for op_id in [*curated, *utilities] if op_id not in ops]
    problems += [f"{op_id}: no such operation" for op_id in HELD if op_id not in ops]
    entries: dict[str, dict[str, Any]] = {}
    for op_id, op in sorted(ops.items()):
        entry: dict[str, Any] = {"method": op.method, "path": op.path}
        reviewed = op_id in curated or op_id in utilities
        if op.deprecated:
            entry |= {"state": "denied", "reason": "deprecated"}
        elif policy.refused(op.path):
            entry |= {"state": "denied", "reason": "always_refused"}
        elif op_id in HELD:
            entry |= {"state": "held", "reason": HELD[op_id]}
        elif op_id in utilities:
            found = _utility_problems(op, utilities[op_id])
            if found:
                problems += found
                continue
            entry |= _utility_entry(utilities[op_id])
        elif reviewed:
            scope, side_effect = policy.scope_of(op.path), SIDE_EFFECTS.get(op.method)
            if scope is None or side_effect is None:
                problems.append(f"{op_id}: no scope class or side effect")
                continue
            generic = "mist.api.read" if op.method == "GET" else "mist.api.write"
            entry |= {
                "state": "allowed",
                "nodes": [curated[op_id], generic],
                "capability": "mist.read" if op.method == "GET" else "mist.write",
                "scope": scope,
                "side_effect": side_effect,
                "evidence": EVIDENCE[side_effect],
            }
        else:
            entry |= {"state": "held", "reason": "unreviewed"}
        if reviewed and entry["state"] != "allowed":
            problems.append(f"{op_id}: reviewed, but {entry['state']} ({entry['reason']})")
        entries[op_id] = entry
    problems += _reads(entries)
    if problems:
        raise ReviewError(problems)
    return {"version": policy.VERSION, "oas_sha256": oas.SHA256, "operations": entries}


def _utility_problems(op: oas.Operation, u: Utility) -> list[str]:
    """Whether a utility's review fits its operation: a POST under a site's device; a contract a node implements, a
    disruptive one acceptance only; a stream only from an answer holding a `session`; known device types; parameters
    of its body but the refresh ones; maxima only for its integer parameters (within the OAS's own) and, streaming, its
    duration."""
    name, doc = op.id, oas.document()
    if op.method != "POST" or not UTILITY_PATH.match(op.path):
        return [f"{name}: not a device utility"]
    out: list[str] = []
    if u.kind not in KINDS:
        out.append(f"{name}: kind {u.kind!r}")
    if u.contract not in policy.CONTRACTS:
        return [*out, f"{name}: contract {u.contract!r} has no node"]
    if u.kind == "disruptive" and u.contract != "acceptance_only":
        out.append(f"{name}: a disruptive utility is acceptance only (D27)")
    stream = u.contract != "acceptance_only"
    answer = oas.answer(doc, op)
    if stream and (answer is None or "session" not in oas.resolve(doc, answer).get("properties", {})):
        out.append(f"{name}: streams, but its answer holds no session")
    if not u.device_types or not set(u.device_types) <= set(policy.DEVICE_TYPES):
        out.append(f"{name}: device types {list(u.device_types)} aren't {list(policy.DEVICE_TYPES)}")
    body = _body(doc, op)
    out += [f"{name}: parameter {p!r} isn't permitted" for p in u.parameters if p not in body or p in REFRESH]
    out += [f"{name}: parameter {p!r} is an object, which would carry any keys" for p in u.parameters
            if p in body and oas.resolve(doc, body[p]).get("type") == "object"]  # fmt: skip
    if u.kind == "disruptive" and not u.selectors:
        out.append(f"{name}: a disruptive utility names its selectors (review M1)")
    for s in u.selectors:
        found = oas.resolve(doc, body[s]) if s in u.parameters and s in body else None
        items = oas.resolve(doc, found.get("items", {})) if found is not None and found.get("type") == "array" else {}
        if found is None or found.get("type") not in SELECTOR_TYPES or (items and items.get("type") != "string"):
            out.append(f"{name}: selector {s!r} isn't a string or a list of strings among its parameters")
    for key, bound in u.bounds.items():
        if key == "max_duration_s":
            if not stream:
                out.append(f"{name}: bound 'max_duration_s' is a stream's")
            continue
        prop = oas.resolve(doc, body.get(key, {})) if key in u.parameters else {}
        low, high = prop.get("minimum"), prop.get("maximum")
        if prop.get("type") != "integer" or (low is not None and bound < low) or (high is not None and bound > high):
            out.append(f"{name}: bound {key!r} isn't within an integer parameter's range")
    return out


def _body(doc: Mapping[str, Any], op: oas.Operation) -> Mapping[str, Any]:
    """An operation's JSON body's properties (none when it takes no body)."""
    found = op.spec.get("requestBody")
    if found is None:
        return {}
    schema = oas.resolve(doc, (oas.resolve(doc, found).get("content") or {}).get("application/json", {}).get("schema"))
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    return props if isinstance(props, Mapping) else {}


def _utility_entry(u: Utility) -> dict[str, Any]:
    capability, side_effect = KINDS[u.kind]
    return {
        "state": "allowed",
        "nodes": [u.node],  # never mist.api.write: it would bypass the parameters and the contract
        "capability": capability,
        "scope": "site",
        "side_effect": side_effect,
        "evidence": u.evidence,
        "utility": {
            "contract": u.contract,
            "stream": u.contract != "acceptance_only",
            "device_types": list(u.device_types),
            "parameters": list(u.parameters),
            "bounds": dict(u.bounds),
            "repeat": u.repeat,
            "selectors": list(u.selectors),
        },
    }


def _reads(entries: dict[str, dict[str, Any]]) -> list[str]:
    """Each allowed operation's reads: its site check (a site-scope operation can't be allowed without it), the
    same-path GET an update merges into, and the lists its pickers read; every one allowed itself."""
    doc, ops = oas.document(), oas.operations()
    allowed = {op_id for op_id, e in entries.items() if e["state"] == "allowed"}
    lists = {ops[o].path: o for o in sorted(allowed) if routing.is_list(doc, ops[o])}
    gets = {ops[o].path: o for o in allowed if ops[o].method == "GET"}
    problems: list[str] = []
    for op_id in sorted(allowed):
        op, entry = ops[op_id], entries[op_id]
        reads = set(routing.pickers(op.path, entry["scope"], lists).values())
        if entry["scope"] == "site":
            if routing.SITE_CHECK not in allowed:
                problems.append(f"{op_id}: its site check reads {routing.SITE_CHECK}, which isn't allowed")
            reads.add(routing.SITE_CHECK)
        if op.method == "PUT" and op.path in gets:
            reads.add(gets[op.path])
        if "utility" in entry:
            if DEVICE_CHECK not in allowed:
                problems.append(f"{op_id}: its device check reads {DEVICE_CHECK}, which isn't allowed")
            reads.add(DEVICE_CHECK)
        entry["reads"] = sorted(reads)
    return problems


def render(made: dict[str, Any]) -> str:
    """The map as written: one operation a line, keys sorted, so a review's diff shows each operation it changes."""
    ops = made["operations"]
    lines = [json.dumps(k) + ": " + json.dumps(ops[k], sort_keys=True, ensure_ascii=False) for k in sorted(ops)]
    head = f'{{\n"oas_sha256": {json.dumps(made["oas_sha256"])},\n"version": {made["version"]},\n"operations": {{\n'
    return head + ",\n".join(lines) + "\n}\n}\n"


if __name__ == "__main__":
    try:
        text = render(make_map())
    except ReviewError as e:
        sys.exit("\n".join(e.problems))
    policy.MAP_FILE.write_text(text)
