# muffin

![Version: 0.5.0-rc.2](https://img.shields.io/badge/Version-0.5.0--rc.2-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 0.6.0-rc.2](https://img.shields.io/badge/AppVersion-0.6.0--rc.2-informational?style=flat-square)

A Helm chart to deploy Muffin.

## Requirements

Kubernetes: `>=1.25.0-0`

| Repository | Name | Version |
|------------|------|---------|
| https://charts.kubito.dev | searxng | 1.1.4 |
| https://cloudnative-pg.github.io/charts | cnpg(cluster) | 0.8.1 |
| https://meilisearch.github.io/meilisearch-kubernetes | meilisearch | 0.39.0 |
| oci://registry-1.docker.io/cloudpirates | postgres(postgres) | 0.19.6 |
| oci://registry-1.docker.io/cloudpirates | redis(redis) | 0.27.9 |
| oci://registry-1.docker.io/cloudpirates | rustfs(rustfs) | 0.10.0 |

## Values

### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| commonLabels | object | `{}` | Add labels to all the deployed resources |
| cronjobs | object | `{}` | Map of CronJobs to create (e.g. periodic archiving, cleanup, reports...). Each key is used as the cronjob name and as its `app.kubernetes.io/component` label. Every entry accepts the same fields as a `jobs` entry (see above, minus `hook`) plus the scheduling fields documented in the commented example below. |
| enabled | bool | `true` | Master switch for the whole chart. When `false`, every template renders nothing - use this to keep a release/namespace registered with a deployment system (e.g. an ArgoCD Application that always gets generated for every app/env combination) without actually deploying any resource into it. Note this does NOT cover subchart dependencies added via `Chart.yaml` (e.g. a bundled database/cache) - those still need their own `enabled: false` alongside this one. |
| extraObjects | object | `{}` | Map of extra specs to dynamically add to this chart. Each key is a unique, arbitrary name for the object (only used so `-f` values files/overrides can add, override or remove a single entry by key instead of the whole list - lists don't merge across values files in Helm). |
| fullnameOverride | string | `""` | String to fully override the default application name. |
| jobs | object | `{}` | Map of Jobs to create (e.g. one-off DB migrations, data seeding, archiving...). Each key is used as the job name and as its `app.kubernetes.io/component` label. Every entry accepts the fields documented in the commented example below. |
| nameOverride | string | `""` | Provide a name in place of the default application name. |

### Global

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| global.env | object | `{}` | Map or array of environment variables to inject into all containers (`valueFrom` supported). |
| global.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by all containers (`valueFrom` not supported). |
| global.envFrom | list | `[]` | List or map of `configMapRef`/`secretRef` entries to load into every container's `envFrom` (merged with each component's own `envFrom`, global entries first). |
| global.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by all containers (`valueFrom` not supported). |
| global.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| global.httpRoute.enabled | bool | `false` | Whether or not the chart-level HTTPRoute should be enabled. |
| global.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| global.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| global.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| global.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. Required when `enabled` is true, and every `backendRefs` entry must carry a `name`. |
| global.imagePullSecrets | list | `[]` | Image credentials applied to every component in addition to any component-specific `imagePullSecrets`. |
| global.imageRegistry | string | `""` | Global Docker image registry |
| global.ingress.annotations | object | `{}` | Additional ingress annotations. |
| global.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| global.ingress.enabled | bool | `false` | Whether or not the chart-level ingress should be enabled. |
| global.ingress.hosts | list | `[]` | Hosts and paths served by the chart-level ingress. Each path's `backend.serviceName` is required (see above); `backend.portNumber` defaults to 80. |
| global.ingress.labels | object | `{}` | Additional ingress labels. |
| global.ingress.tls | list | `[]` | TLS configuration for the chart-level ingress. |

### AgentExecution

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.affinity | object | `{}` | Affinity used for app pod. |
| agent_execution.args | list | `[]` | Agent_execution container command args. |
| agent_execution.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| agent_execution.command | list | `[]` | Agent_execution container command. |
| agent_execution.containerPort | int | `8080` | Agent_execution container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| agent_execution.containerPortName | string | `"http"` | Agent_execution container port name. |
| agent_execution.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| agent_execution.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| agent_execution.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| agent_execution.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| agent_execution.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| agent_execution.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| agent_execution.envFrom | list | `[]` | Agent_execution container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| agent_execution.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| agent_execution.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| agent_execution.extraPorts | list | `[]` | Agent_execution extra container ports. |
| agent_execution.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| agent_execution.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| agent_execution.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| agent_execution.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| agent_execution.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| agent_execution.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| agent_execution.imagePullSecrets | list | `[]` | Image credentials configuration. |
| agent_execution.initContainers | list | `[]` | Init containers to add to the app pod. |
| agent_execution.nodeSelector | object | `{}` | Default node selector for app. |
| agent_execution.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| agent_execution.podLabels | object | `{}` | Labels for the app deployed pods. |
| agent_execution.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| agent_execution.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| agent_execution.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| agent_execution.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| agent_execution.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| agent_execution.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| agent_execution.tolerations | list | `[]` | Default tolerations for app. |
| agent_execution.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| agent_execution.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| agent_execution.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| agent_execution.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| agent_execution.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| agent_execution.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| agent_execution.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| agent_execution.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| agent_execution.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| agent_execution.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| agent_execution.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| agent_execution.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| agent_execution.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| agent_execution.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| agent_execution.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| agent_execution.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| agent_execution.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| agent_execution.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| agent_execution.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| agent_execution.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| agent_execution.image.registry | string | `"docker.io"` | Registry to use for the app. |
| agent_execution.image.repository | string | `"debian"` | Repository to use for the app. |
| agent_execution.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.ingress.annotations | object | `{}` | Additional ingress annotations. |
| agent_execution.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| agent_execution.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| agent_execution.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| agent_execution.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| agent_execution.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| agent_execution.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| agent_execution.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| agent_execution.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| agent_execution.ingress.labels | object | `{}` | Additional ingress labels. |
| agent_execution.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.metrics.enabled | bool | `false` | Deploy metrics service. |
| agent_execution.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| agent_execution.metrics.service.labels | object | `{}` | Metrics service labels. |
| agent_execution.metrics.service.port | int | `9000` | Metrics service port. |
| agent_execution.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| agent_execution.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| agent_execution.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| agent_execution.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| agent_execution.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| agent_execution.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| agent_execution.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| agent_execution.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| agent_execution.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| agent_execution.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| agent_execution.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| agent_execution.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| agent_execution.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| agent_execution.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| agent_execution.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| agent_execution.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| agent_execution.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| agent_execution.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| agent_execution.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| agent_execution.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| agent_execution.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| agent_execution.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| agent_execution.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| agent_execution.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| agent_execution.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| agent_execution.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| agent_execution.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `agent_execution.pdb.minAvailable`. |
| agent_execution.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| agent_execution.probes.livenessProbe.httpGet.path | string | `"/"` | Agent_execution container healthcheck endpoint (livenessProbe is defined using `toYaml` so it is possible to override it completely). |
| agent_execution.probes.livenessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| agent_execution.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| agent_execution.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| agent_execution.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| agent_execution.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| agent_execution.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| agent_execution.probes.readinessProbe.httpGet.path | string | `"/"` | Agent_execution container healthcheck endpoint (readinessProbe is defined using `toYaml` so it is possible to override it completely). |
| agent_execution.probes.readinessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| agent_execution.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| agent_execution.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| agent_execution.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| agent_execution.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| agent_execution.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| agent_execution.probes.startupProbe.httpGet.path | string | `"/"` | Agent_execution container healthcheck endpoint (startupProbe is defined using `toYaml` so it is possible to override it completely). |
| agent_execution.probes.startupProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| agent_execution.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| agent_execution.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| agent_execution.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| agent_execution.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| agent_execution.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| agent_execution.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| agent_execution.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| agent_execution.service.extraPorts | list | `[]` | Extra service ports. |
| agent_execution.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| agent_execution.service.port | int | `80` | Port used by the service. |
| agent_execution.service.portName | string | `"http"` | Port name used by the service. |
| agent_execution.service.protocol | string | `"TCP"` | Protocol used by the service. |
| agent_execution.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| agent_execution.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| agent_execution.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| agent_execution.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| agent_execution.serviceAccount.create | bool | `false` | Create a service account. |
| agent_execution.serviceAccount.enabled | bool | `false` | Enable the service account. |
| agent_execution.serviceAccount.name | string | `""` | Service account name. |
| agent_execution.serviceAccount.role.create | bool | `false` | Should the role be created. |
| agent_execution.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| agent_execution.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| agent_execution.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| agent_execution.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### Backend

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.affinity | object | `{}` | Affinity used for app pod. |
| backend.args | list | `[]` | Backend container command args. |
| backend.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| backend.command | list | `[]` | Backend container command. |
| backend.containerPort | int | `8080` | Backend container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| backend.containerPortName | string | `"http"` | Backend container port name. |
| backend.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| backend.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| backend.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| backend.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| backend.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| backend.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| backend.envFrom | list | `[]` | Backend container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| backend.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| backend.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| backend.extraPorts | list | `[]` | Backend extra container ports. |
| backend.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| backend.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| backend.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| backend.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| backend.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| backend.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| backend.imagePullSecrets | list | `[]` | Image credentials configuration. |
| backend.initContainers | list | `[]` | Init containers to add to the app pod. |
| backend.nodeSelector | object | `{}` | Default node selector for app. |
| backend.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| backend.podLabels | object | `{}` | Labels for the app deployed pods. |
| backend.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| backend.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| backend.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| backend.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| backend.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| backend.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| backend.tolerations | list | `[]` | Default tolerations for app. |
| backend.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| backend.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| backend.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| backend.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| backend.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| backend.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| backend.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| backend.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| backend.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| backend.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| backend.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| backend.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| backend.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| backend.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| backend.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| backend.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| backend.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| backend.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| backend.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| backend.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| backend.image.registry | string | `"docker.io"` | Registry to use for the app. |
| backend.image.repository | string | `"debian"` | Repository to use for the app. |
| backend.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.ingress.annotations | object | `{}` | Additional ingress annotations. |
| backend.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| backend.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| backend.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| backend.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| backend.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| backend.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| backend.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| backend.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| backend.ingress.labels | object | `{}` | Additional ingress labels. |
| backend.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.metrics.enabled | bool | `false` | Deploy metrics service. |
| backend.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| backend.metrics.service.labels | object | `{}` | Metrics service labels. |
| backend.metrics.service.port | int | `9000` | Metrics service port. |
| backend.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| backend.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| backend.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| backend.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| backend.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| backend.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| backend.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| backend.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| backend.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| backend.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| backend.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| backend.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| backend.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| backend.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| backend.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| backend.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| backend.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| backend.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| backend.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| backend.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| backend.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| backend.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| backend.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| backend.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| backend.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| backend.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| backend.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `backend.pdb.minAvailable`. |
| backend.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| backend.probes.livenessProbe.httpGet.path | string | `"/"` | Backend container healthcheck endpoint (livenessProbe is defined using `toYaml` so it is possible to override it completely). |
| backend.probes.livenessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| backend.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| backend.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| backend.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| backend.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| backend.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| backend.probes.readinessProbe.httpGet.path | string | `"/"` | Backend container healthcheck endpoint (readinessProbe is defined using `toYaml` so it is possible to override it completely). |
| backend.probes.readinessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| backend.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| backend.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| backend.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| backend.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| backend.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| backend.probes.startupProbe.httpGet.path | string | `"/"` | Backend container healthcheck endpoint (startupProbe is defined using `toYaml` so it is possible to override it completely). |
| backend.probes.startupProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| backend.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| backend.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| backend.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| backend.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| backend.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| backend.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| backend.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| backend.service.extraPorts | list | `[]` | Extra service ports. |
| backend.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| backend.service.port | int | `80` | Port used by the service. |
| backend.service.portName | string | `"http"` | Port name used by the service. |
| backend.service.protocol | string | `"TCP"` | Protocol used by the service. |
| backend.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| backend.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| backend.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| backend.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| backend.serviceAccount.create | bool | `false` | Create a service account. |
| backend.serviceAccount.enabled | bool | `false` | Enable the service account. |
| backend.serviceAccount.name | string | `""` | Service account name. |
| backend.serviceAccount.role.create | bool | `false` | Should the role be created. |
| backend.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| backend.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| backend.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### DocumentProcess

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.affinity | object | `{}` | Affinity used for app pod. |
| document_process.args | list | `[]` | Document_process container command args. |
| document_process.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| document_process.command | list | `[]` | Document_process container command. |
| document_process.containerPort | int | `8080` | Document_process container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| document_process.containerPortName | string | `"http"` | Document_process container port name. |
| document_process.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| document_process.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| document_process.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| document_process.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| document_process.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| document_process.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| document_process.envFrom | list | `[]` | Document_process container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| document_process.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| document_process.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| document_process.extraPorts | list | `[]` | Document_process extra container ports. |
| document_process.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| document_process.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| document_process.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| document_process.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| document_process.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| document_process.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| document_process.imagePullSecrets | list | `[]` | Image credentials configuration. |
| document_process.initContainers | list | `[]` | Init containers to add to the app pod. |
| document_process.nodeSelector | object | `{}` | Default node selector for app. |
| document_process.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| document_process.podLabels | object | `{}` | Labels for the app deployed pods. |
| document_process.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| document_process.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| document_process.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| document_process.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| document_process.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| document_process.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| document_process.tolerations | list | `[]` | Default tolerations for app. |
| document_process.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| document_process.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| document_process.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| document_process.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| document_process.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| document_process.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| document_process.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| document_process.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| document_process.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| document_process.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| document_process.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| document_process.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| document_process.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| document_process.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| document_process.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| document_process.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| document_process.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| document_process.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| document_process.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| document_process.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| document_process.image.registry | string | `"docker.io"` | Registry to use for the app. |
| document_process.image.repository | string | `"debian"` | Repository to use for the app. |
| document_process.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.ingress.annotations | object | `{}` | Additional ingress annotations. |
| document_process.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| document_process.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| document_process.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| document_process.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| document_process.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| document_process.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| document_process.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| document_process.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| document_process.ingress.labels | object | `{}` | Additional ingress labels. |
| document_process.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.metrics.enabled | bool | `false` | Deploy metrics service. |
| document_process.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| document_process.metrics.service.labels | object | `{}` | Metrics service labels. |
| document_process.metrics.service.port | int | `9000` | Metrics service port. |
| document_process.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| document_process.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| document_process.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| document_process.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| document_process.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| document_process.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| document_process.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| document_process.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| document_process.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| document_process.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| document_process.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| document_process.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| document_process.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| document_process.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| document_process.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| document_process.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| document_process.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| document_process.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| document_process.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| document_process.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| document_process.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| document_process.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| document_process.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| document_process.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| document_process.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| document_process.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| document_process.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `document_process.pdb.minAvailable`. |
| document_process.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_process.probes.livenessProbe.httpGet.path | string | `"/"` | Document_process container healthcheck endpoint (livenessProbe is defined using `toYaml` so it is possible to override it completely). |
| document_process.probes.livenessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| document_process.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| document_process.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| document_process.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_process.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| document_process.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_process.probes.readinessProbe.httpGet.path | string | `"/"` | Document_process container healthcheck endpoint (readinessProbe is defined using `toYaml` so it is possible to override it completely). |
| document_process.probes.readinessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| document_process.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| document_process.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| document_process.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_process.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| document_process.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_process.probes.startupProbe.httpGet.path | string | `"/"` | Document_process container healthcheck endpoint (startupProbe is defined using `toYaml` so it is possible to override it completely). |
| document_process.probes.startupProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| document_process.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| document_process.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| document_process.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_process.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| document_process.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| document_process.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| document_process.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| document_process.service.extraPorts | list | `[]` | Extra service ports. |
| document_process.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| document_process.service.port | int | `80` | Port used by the service. |
| document_process.service.portName | string | `"http"` | Port name used by the service. |
| document_process.service.protocol | string | `"TCP"` | Protocol used by the service. |
| document_process.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| document_process.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| document_process.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| document_process.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| document_process.serviceAccount.create | bool | `false` | Create a service account. |
| document_process.serviceAccount.enabled | bool | `false` | Enable the service account. |
| document_process.serviceAccount.name | string | `""` | Service account name. |
| document_process.serviceAccount.role.create | bool | `false` | Should the role be created. |
| document_process.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| document_process.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| document_process.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### Frontend

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.affinity | object | `{}` | Affinity used for app pod. |
| frontend.args | list | `[]` | Frontend container command args. |
| frontend.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| frontend.command | list | `[]` | Frontend container command. |
| frontend.containerPort | int | `8080` | Frontend container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| frontend.containerPortName | string | `"http"` | Frontend container port name. |
| frontend.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| frontend.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| frontend.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| frontend.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| frontend.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| frontend.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| frontend.envFrom | list | `[]` | Frontend container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| frontend.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| frontend.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| frontend.extraPorts | list | `[]` | Frontend extra container ports. |
| frontend.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| frontend.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| frontend.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| frontend.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| frontend.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| frontend.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| frontend.imagePullSecrets | list | `[]` | Image credentials configuration. |
| frontend.initContainers | list | `[]` | Init containers to add to the app pod. |
| frontend.nodeSelector | object | `{}` | Default node selector for app. |
| frontend.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| frontend.podLabels | object | `{}` | Labels for the app deployed pods. |
| frontend.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| frontend.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| frontend.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| frontend.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| frontend.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| frontend.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| frontend.tolerations | list | `[]` | Default tolerations for app. |
| frontend.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| frontend.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| frontend.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| frontend.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| frontend.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| frontend.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| frontend.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| frontend.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| frontend.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| frontend.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| frontend.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| frontend.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| frontend.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| frontend.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| frontend.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| frontend.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| frontend.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| frontend.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| frontend.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| frontend.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| frontend.image.registry | string | `"docker.io"` | Registry to use for the app. |
| frontend.image.repository | string | `"debian"` | Repository to use for the app. |
| frontend.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.ingress.annotations | object | `{}` | Additional ingress annotations. |
| frontend.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| frontend.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| frontend.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| frontend.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| frontend.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| frontend.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| frontend.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| frontend.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| frontend.ingress.labels | object | `{}` | Additional ingress labels. |
| frontend.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.metrics.enabled | bool | `false` | Deploy metrics service. |
| frontend.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| frontend.metrics.service.labels | object | `{}` | Metrics service labels. |
| frontend.metrics.service.port | int | `9000` | Metrics service port. |
| frontend.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| frontend.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| frontend.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| frontend.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| frontend.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| frontend.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| frontend.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| frontend.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| frontend.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| frontend.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| frontend.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| frontend.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| frontend.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| frontend.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| frontend.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| frontend.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| frontend.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| frontend.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| frontend.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| frontend.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| frontend.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| frontend.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| frontend.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| frontend.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| frontend.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| frontend.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| frontend.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `frontend.pdb.minAvailable`. |
| frontend.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| frontend.probes.livenessProbe.httpGet.path | string | `"/"` | Frontend container healthcheck endpoint (livenessProbe is defined using `toYaml` so it is possible to override it completely). |
| frontend.probes.livenessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| frontend.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| frontend.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| frontend.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| frontend.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| frontend.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| frontend.probes.readinessProbe.httpGet.path | string | `"/"` | Frontend container healthcheck endpoint (readinessProbe is defined using `toYaml` so it is possible to override it completely). |
| frontend.probes.readinessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| frontend.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| frontend.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| frontend.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| frontend.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| frontend.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| frontend.probes.startupProbe.httpGet.path | string | `"/"` | Frontend container healthcheck endpoint (startupProbe is defined using `toYaml` so it is possible to override it completely). |
| frontend.probes.startupProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| frontend.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| frontend.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| frontend.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| frontend.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| frontend.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| frontend.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| frontend.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| frontend.service.extraPorts | list | `[]` | Extra service ports. |
| frontend.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| frontend.service.port | int | `80` | Port used by the service. |
| frontend.service.portName | string | `"http"` | Port name used by the service. |
| frontend.service.protocol | string | `"TCP"` | Protocol used by the service. |
| frontend.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| frontend.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| frontend.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| frontend.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| frontend.serviceAccount.create | bool | `false` | Create a service account. |
| frontend.serviceAccount.enabled | bool | `false` | Enable the service account. |
| frontend.serviceAccount.name | string | `""` | Service account name. |
| frontend.serviceAccount.role.create | bool | `false` | Should the role be created. |
| frontend.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| frontend.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| frontend.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### Gateway

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| gateway.addresses | list | `[]` | Gateway addresses configuration. |
| gateway.annotations | object | `{}` | Additional gateway annotations. |
| gateway.className | string | `""` | GatewayClass name. Required when creating a Gateway. |
| gateway.create | bool | `false` | Create a Gateway resource. Usually, you reference an existing Gateway managed by the infrastructure team. |
| gateway.labels | object | `{}` | Additional gateway labels. |
| gateway.listeners | list | `[]` | Gateway listeners configuration. |
| gateway.name | string | `""` | Name of the Gateway resource. If not set, uses the release fullname. |

## Sources

**Source code:**

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
