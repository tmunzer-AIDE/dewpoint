# SPDX-License-Identifier: Apache-2.0
"""Webhook ingress (engine 2b spec §8.3): its own process and database login, `/hooks/<endpoint_id>`. It holds the
ingress key, never a tenant's data key, and has no table privilege: it resolves an endpoint and records events only
through the database's SECURITY DEFINER functions."""
