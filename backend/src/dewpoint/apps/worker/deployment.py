# SPDX-License-Identifier: Apache-2.0
"""The engine's Worker Deployment (spec §7). Each build is a Deployment Version of `dewpoint-engine`, with build ID
`dewpoint-<version>+abi<ENGINE_ABI>`. `RunGraph` and `LoopBatch` are pinned: a run, its children and its continued
runs finish on the version they started on, while new runs start on the deployment's current version. Making a build
current is an operator's step (docs/operations/deployment.md)."""

import asyncio
from dataclasses import dataclass

from temporalio.api.enums.v1 import WorkerDeploymentVersionStatus
from temporalio.api.workflowservice.v1 import (
    DescribeWorkerDeploymentRequest,
    SetWorkerDeploymentCurrentVersionRequest,
)
from temporalio.client import Client
from temporalio.common import WorkerDeploymentVersion
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import WorkerDeploymentConfig

import dewpoint
from dewpoint.engine.runtime.build import build_id

DEPLOYMENT = "dewpoint-engine"
IDENTITY = "dewpoint-deployment"  # who changed the routing, as Temporal records it


def this_build() -> str:
    return build_id(dewpoint.__version__)


def deployment_config(build: str) -> WorkerDeploymentConfig:
    """The engine worker's: it serves `build`'s version of the deployment. The CEL workers aren't in it (§7)."""
    return WorkerDeploymentConfig(version=WorkerDeploymentVersion(DEPLOYMENT, build), use_worker_versioning=True)


@dataclass(frozen=True)
class Version:
    build_id: str
    status: str  # current, ramping, draining, drained or inactive


@dataclass(frozen=True)
class Deployment:
    current: str | None  # the build new runs start on
    versions: list[Version]


async def set_current(client: Client, build: str, *, wait_s: float = 60.0) -> None:
    """Make `build` the version new runs start on. A version exists once one of its workers has polled: until then
    Temporal refuses, and this retries for up to `wait_s`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    request = SetWorkerDeploymentCurrentVersionRequest(
        namespace=client.namespace, deployment_name=DEPLOYMENT, build_id=build, identity=IDENTITY
    )
    while True:
        try:
            await client.workflow_service.set_worker_deployment_current_version(request)
            return
        except RPCError as e:
            if e.status not in (RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION) or loop.time() > deadline:
                raise
        await asyncio.sleep(0.5)


async def describe(client: Client) -> Deployment:
    """The current build, and every version Temporal knows with its status: a version still draining serves the
    pinned runs that started on it."""
    info = (
        await client.workflow_service.describe_worker_deployment(
            DescribeWorkerDeploymentRequest(namespace=client.namespace, deployment_name=DEPLOYMENT)
        )
    ).worker_deployment_info
    current = info.routing_config.current_deployment_version.build_id or None
    prefix = "WORKER_DEPLOYMENT_VERSION_STATUS_"
    versions = [
        Version(
            v.deployment_version.build_id, WorkerDeploymentVersionStatus.Name(v.status).removeprefix(prefix).lower()
        )
        for v in info.version_summaries
    ]
    return Deployment(current, sorted(versions, key=lambda v: v.build_id))
