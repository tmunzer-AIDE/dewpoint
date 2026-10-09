// SPDX-License-Identifier: Apache-2.0

package policy

import "strings"

// Class is how the authorizer treats an API (D12.1's classification).
type Class int

const (
	Unclassed Class = iota // not in the table: refused and audited
	Delegated              // can't change a namespace's configuration: the caller's role alone, not audited
	Inspected              // RegisterNamespace and UpdateNamespace: the namespace rules, then the role; audited
	Refused                // can change a namespace's configuration or the cluster's replication: refused, audited
	Closed                 // Nexus's HTTP routes: not Dewpoint's, and v1.32.0 can't turn them off; refused, not audited
)

func (c Class) String() string {
	return [...]string{"unclassed", "delegated", "inspected", "refused", "closed"}[c]
}

const (
	workflowService = "/temporal.api.workflowservice.v1.WorkflowService/"
	operatorService = "/temporal.api.operatorservice.v1.OperatorService/"
	adminService    = "/temporal.server.api.adminservice.v1.AdminService/"

	RegisterNamespace = workflowService + "RegisterNamespace"
	UpdateNamespace   = workflowService + "UpdateNamespace"
)

// The frontend's services as Temporal v1.32.0 registers them (service/frontend/service.go): WorkflowService,
// AdminService and OperatorService from their generated definitions, then gRPC's health and reflection services.
// Each name is in exactly one class. A server upgrade that adds an RPC fails the build's descriptor test until it's
// classed here, and an unclassed one is refused at runtime.
var classes = map[string]map[Class]string{
	workflowService: {
		Inspected: "RegisterNamespace UpdateNamespace",
		// workflow rules are kept in the namespace's configuration
		Refused: "DeprecateNamespace CreateWorkflowRule DeleteWorkflowRule",
		Delegated: `DescribeNamespace ListNamespaces
			StartWorkflowExecution ExecuteMultiOperation GetWorkflowExecutionHistory GetWorkflowExecutionHistoryReverse
			PollWorkflowTaskQueue RespondWorkflowTaskCompleted RespondWorkflowTaskFailed PollActivityTaskQueue
			RecordActivityTaskHeartbeat RecordActivityTaskHeartbeatById RespondActivityTaskCompleted
			RespondActivityTaskCompletedById RespondActivityTaskFailed RespondActivityTaskFailedById
			RespondActivityTaskCanceled RespondActivityTaskCanceledById RequestCancelWorkflowExecution
			SignalWorkflowExecution SignalWithStartWorkflowExecution ResetWorkflowExecution TerminateWorkflowExecution
			DeleteWorkflowExecution ListOpenWorkflowExecutions ListClosedWorkflowExecutions ListWorkflowExecutions
			ListArchivedWorkflowExecutions ScanWorkflowExecutions CountWorkflowExecutions GetSearchAttributes
			RespondQueryTaskCompleted ResetStickyTaskQueue ShutdownWorker QueryWorkflow DescribeWorkflowExecution
			DescribeTaskQueue GetClusterInfo GetSystemInfo ListTaskQueuePartitions
			CreateSchedule DescribeSchedule UpdateSchedule PatchSchedule ListScheduleMatchingTimes DeleteSchedule
			ListSchedules CountSchedules
			UpdateWorkerBuildIdCompatibility GetWorkerBuildIdCompatibility UpdateWorkerVersioningRules
			GetWorkerVersioningRules GetWorkerTaskReachability DescribeDeployment DescribeWorkerDeploymentVersion
			ListDeployments GetDeploymentReachability GetCurrentDeployment SetCurrentDeployment
			SetWorkerDeploymentCurrentVersion DescribeWorkerDeployment DeleteWorkerDeployment
			DeleteWorkerDeploymentVersion SetWorkerDeploymentRampingVersion ListWorkerDeployments
			CreateWorkerDeployment CreateWorkerDeploymentVersion UpdateWorkerDeploymentVersionComputeConfig
			ValidateWorkerDeploymentVersionComputeConfig UpdateWorkerDeploymentVersionMetadata
			SetWorkerDeploymentManager
			UpdateWorkflowExecution PollWorkflowExecutionUpdate StartBatchOperation StopBatchOperation
			DescribeBatchOperation ListBatchOperations PollNexusTaskQueue RespondNexusTaskCompleted
			RespondNexusTaskFailed UpdateActivityOptions UpdateWorkflowExecutionOptions PauseActivity UnpauseActivity
			ResetActivity DescribeWorkflowRule ListWorkflowRules TriggerWorkflowRule RecordWorkerHeartbeat
			ListWorkers CountWorkers UpdateTaskQueueConfig FetchWorkerConfig UpdateWorkerConfig DescribeWorker
			PauseWorkflowExecution UnpauseWorkflowExecution StartActivityExecution StartNexusOperationExecution
			DescribeActivityExecution DescribeNexusOperationExecution PollActivityExecution
			PollNexusOperationExecution ListActivityExecutions ListNexusOperationExecutions CountActivityExecutions
			CountNexusOperationExecutions RequestCancelActivityExecution RequestCancelNexusOperationExecution
			TerminateActivityExecution DeleteActivityExecution PauseActivityExecution ResetActivityExecution
			UnpauseActivityExecution UpdateActivityExecutionOptions TerminateNexusOperationExecution
			DeleteNexusOperationExecution PollWorkflowExecutionTimeSkipping`,
	},
	operatorService: {
		// search attributes on SQL visibility are aliases in the namespace's configuration; a remote cluster would
		// replicate a namespace beyond its retention; Nexus endpoints aren't Dewpoint's and stay closed
		Refused: `AddSearchAttributes RemoveSearchAttributes DeleteNamespace AddOrUpdateRemoteCluster
			RemoveRemoteCluster CreateNexusEndpoint UpdateNexusEndpoint DeleteNexusEndpoint`,
		Delegated: "ListSearchAttributes ListClusters GetNexusEndpoint ListNexusEndpoints",
	},
	adminService: {
		Refused: "AddSearchAttributes RemoveSearchAttributes AddOrUpdateRemoteCluster RemoveRemoteCluster",
		// cluster-scoped administration: Temporal's default authorizer requires the system admin role
		Delegated: `RebuildMutableState ImportWorkflowExecution DescribeMutableState DescribeHistoryHost GetShard
			CloseShard ListHistoryTasks RemoveTask GetWorkflowExecutionRawHistoryV2 GetWorkflowExecutionRawHistory
			GetReplicationMessages GetNamespaceReplicationMessages GetDLQReplicationMessages ReapplyEvents
			GetSearchAttributes DescribeCluster ListClusters ListClusterMembers GetDLQMessages PurgeDLQMessages
			MergeDLQMessages RefreshWorkflowTasks StartAdminBatchOperation ResendReplicationTasks GetTaskQueueTasks
			DeleteWorkflowExecution StreamWorkflowReplicationMessages GetNamespace GetDLQTasks PurgeDLQTasks
			MergeDLQTasks DescribeDLQJob CancelDLQJob AddTasks ListQueues DeepHealthCheck SyncWorkflowState
			GenerateLastHistoryReplicationTasks DescribeTaskQueuePartition ForceUnloadTaskQueuePartition
			GetTaskQueueUserData MigrateSchedule`,
	},
	// not gRPC services: the names the frontend's Nexus HTTP routes authorize (service/frontend/configs/quotas.go)
	"/temporal.api.nexusservice.v1.NexusService/": {
		Closed: "DispatchByNamespaceAndTaskQueue DispatchByEndpoint CompleteNexusOperation",
	},
	"/grpc.health.v1.Health/":                    {Delegated: "Check List Watch"},
	"/grpc.reflection.v1.ServerReflection/":      {Delegated: "ServerReflectionInfo"},
	"/grpc.reflection.v1alpha.ServerReflection/": {Delegated: "ServerReflectionInfo"},
}

// Served lists the RPCs of the services beyond the three generated ones: health and reflection.
var Served = []string{
	"/grpc.health.v1.Health/Check", "/grpc.health.v1.Health/List", "/grpc.health.v1.Health/Watch",
	"/grpc.reflection.v1.ServerReflection/ServerReflectionInfo",
	"/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
}

// NexusHTTP lists the API names the frontend's Nexus HTTP routes authorize.
var NexusHTTP = []string{
	"/temporal.api.nexusservice.v1.NexusService/DispatchByNamespaceAndTaskQueue",
	"/temporal.api.nexusservice.v1.NexusService/DispatchByEndpoint",
	"/temporal.api.nexusservice.v1.NexusService/CompleteNexusOperation",
}

var table = func() map[string]Class {
	t := map[string]Class{}
	for service, byClass := range classes {
		for class, names := range byClass {
			for _, name := range strings.Fields(names) {
				if _, twice := t[service+name]; twice {
					panic("classed twice: " + service + name)
				}
				t[service+name] = class
			}
		}
	}
	return t
}()

// Classify is an API's class; Unclassed when the table doesn't name it.
func Classify(api string) Class { return table[api] }

// Table is the whole classification, for the inventory.
func Table() map[string]Class {
	t := make(map[string]Class, len(table))
	for api, class := range table {
		t[api] = class
	}
	return t
}
