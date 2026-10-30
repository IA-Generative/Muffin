# muffin

![Version: 0.36.0-rc.2](https://img.shields.io/badge/Version-0.36.0--rc.2-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 0.38.0-rc.2](https://img.shields.io/badge/AppVersion-0.38.0--rc.2-informational?style=flat-square)

A Helm chart to deploy Muffin.

## Requirements

Kubernetes: `>=1.25.0-0`

| Repository | Name | Version |
|------------|------|---------|
| https://cloudnative-pg.github.io/charts | cnpg(cluster) | 0.8.1 |
| https://qdrant.github.io/qdrant-helm | qdrant | 1.20.0 |
| https://unknowniq.github.io/helm-charts | searxng | 0.1.11 |
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
| agent_execution.containerPort | string | `nil` | Agent_execution container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
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
| agent_execution.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| agent_execution.image.repository | string | `"ia-generative/muffin/worker-agent-execution"` | Repository to use for the app. |
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
| agent_execution.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Agent_execution container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| agent_execution.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| agent_execution.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| agent_execution.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| agent_execution.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| agent_execution.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| agent_execution.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Agent_execution container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| agent_execution.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| agent_execution.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| agent_execution.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| agent_execution.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| agent_execution.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| agent_execution.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Agent_execution container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| agent_execution.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
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
| backend.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| backend.image.repository | string | `"ia-generative/muffin/backend"` | Repository to use for the app. |
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
| backend.probes.livenessProbe.httpGet.path | string | `"/api/health"` | Backend container healthcheck endpoint (livenessProbe is defined using `toYaml` so it is possible to override it completely). |
| backend.probes.livenessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| backend.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| backend.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| backend.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| backend.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| backend.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| backend.probes.readinessProbe.httpGet.path | string | `"/api/health"` | Backend container healthcheck endpoint (readinessProbe is defined using `toYaml` so it is possible to override it completely). |
| backend.probes.readinessProbe.httpGet.port | int | `8080` | Port to use for healthcheck (defaults to container port). |
| backend.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| backend.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| backend.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| backend.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| backend.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| backend.probes.startupProbe.httpGet.path | string | `"/api/health"` | Backend container healthcheck endpoint (startupProbe is defined using `toYaml` so it is possible to override it completely). |
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

### DocumentEnrichment

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.affinity | object | `{}` | Affinity used for app pod. |
| document_enrichment.args | list | `[]` | Document_enrichment container command args. |
| document_enrichment.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| document_enrichment.command | list | `[]` | Document_enrichment container command. |
| document_enrichment.containerPort | string | `nil` | Document_enrichment container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| document_enrichment.containerPortName | string | `"http"` | Document_enrichment container port name. |
| document_enrichment.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| document_enrichment.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| document_enrichment.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| document_enrichment.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| document_enrichment.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| document_enrichment.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| document_enrichment.envFrom | list | `[]` | Document_enrichment container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| document_enrichment.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| document_enrichment.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| document_enrichment.extraPorts | list | `[]` | Document_enrichment extra container ports. |
| document_enrichment.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| document_enrichment.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| document_enrichment.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| document_enrichment.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| document_enrichment.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| document_enrichment.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| document_enrichment.imagePullSecrets | list | `[]` | Image credentials configuration. |
| document_enrichment.initContainers | list | `[]` | Init containers to add to the app pod. |
| document_enrichment.nodeSelector | object | `{}` | Default node selector for app. |
| document_enrichment.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| document_enrichment.podLabels | object | `{}` | Labels for the app deployed pods. |
| document_enrichment.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| document_enrichment.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| document_enrichment.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| document_enrichment.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| document_enrichment.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| document_enrichment.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| document_enrichment.tolerations | list | `[]` | Default tolerations for app. |
| document_enrichment.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| document_enrichment.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| document_enrichment.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| document_enrichment.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| document_enrichment.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| document_enrichment.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| document_enrichment.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| document_enrichment.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| document_enrichment.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| document_enrichment.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| document_enrichment.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| document_enrichment.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| document_enrichment.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| document_enrichment.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| document_enrichment.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| document_enrichment.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| document_enrichment.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| document_enrichment.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| document_enrichment.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| document_enrichment.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| document_enrichment.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| document_enrichment.image.repository | string | `"ia-generative/muffin/worker-document-process"` | Repository to use for the app. |
| document_enrichment.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.ingress.annotations | object | `{}` | Additional ingress annotations. |
| document_enrichment.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| document_enrichment.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| document_enrichment.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| document_enrichment.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| document_enrichment.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| document_enrichment.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| document_enrichment.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| document_enrichment.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| document_enrichment.ingress.labels | object | `{}` | Additional ingress labels. |
| document_enrichment.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.metrics.enabled | bool | `false` | Deploy metrics service. |
| document_enrichment.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| document_enrichment.metrics.service.labels | object | `{}` | Metrics service labels. |
| document_enrichment.metrics.service.port | int | `9000` | Metrics service port. |
| document_enrichment.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| document_enrichment.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| document_enrichment.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| document_enrichment.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| document_enrichment.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| document_enrichment.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| document_enrichment.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| document_enrichment.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| document_enrichment.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| document_enrichment.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| document_enrichment.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| document_enrichment.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| document_enrichment.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| document_enrichment.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| document_enrichment.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `document_enrichment.pdb.minAvailable`. |
| document_enrichment.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Document_enrichment container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| document_enrichment.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_enrichment.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| document_enrichment.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| document_enrichment.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_enrichment.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| document_enrichment.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Document_enrichment container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| document_enrichment.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_enrichment.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| document_enrichment.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| document_enrichment.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_enrichment.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| document_enrichment.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Document_enrichment container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| document_enrichment.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_enrichment.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| document_enrichment.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| document_enrichment.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_enrichment.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| document_enrichment.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| document_enrichment.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| document_enrichment.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| document_enrichment.service.extraPorts | list | `[]` | Extra service ports. |
| document_enrichment.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| document_enrichment.service.port | int | `80` | Port used by the service. |
| document_enrichment.service.portName | string | `"http"` | Port name used by the service. |
| document_enrichment.service.protocol | string | `"TCP"` | Protocol used by the service. |
| document_enrichment.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| document_enrichment.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| document_enrichment.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| document_enrichment.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| document_enrichment.serviceAccount.create | bool | `false` | Create a service account. |
| document_enrichment.serviceAccount.enabled | bool | `false` | Enable the service account. |
| document_enrichment.serviceAccount.name | string | `""` | Service account name. |
| document_enrichment.serviceAccount.role.create | bool | `false` | Should the role be created. |
| document_enrichment.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_enrichment.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| document_enrichment.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| document_enrichment.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### DocumentProcess

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| document_process.affinity | object | `{}` | Affinity used for app pod. |
| document_process.args | list | `[]` | Document_process container command args. |
| document_process.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| document_process.command | list | `[]` | Document_process container command. |
| document_process.containerPort | string | `nil` | Document_process container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
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
| document_process.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| document_process.image.repository | string | `"ia-generative/muffin/worker-document-process"` | Repository to use for the app. |
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
| document_process.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Document_process container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| document_process.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_process.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| document_process.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| document_process.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_process.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| document_process.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Document_process container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| document_process.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| document_process.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| document_process.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| document_process.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| document_process.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| document_process.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Document_process container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| document_process.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
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
| frontend.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| frontend.image.repository | string | `"ia-generative/muffin/frontend"` | Repository to use for the app. |
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

### IndexRebuild

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.affinity | object | `{}` | Affinity used for app pod. |
| index_rebuild.args | list | `[]` | Index_rebuild container command args. |
| index_rebuild.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| index_rebuild.command | list | `[]` | Index_rebuild container command. |
| index_rebuild.containerPort | string | `nil` | Index_rebuild container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| index_rebuild.containerPortName | string | `"http"` | Index_rebuild container port name. |
| index_rebuild.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| index_rebuild.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| index_rebuild.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| index_rebuild.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| index_rebuild.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| index_rebuild.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| index_rebuild.envFrom | list | `[]` | Index_rebuild container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| index_rebuild.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| index_rebuild.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| index_rebuild.extraPorts | list | `[]` | Index_rebuild extra container ports. |
| index_rebuild.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| index_rebuild.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| index_rebuild.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| index_rebuild.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| index_rebuild.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| index_rebuild.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| index_rebuild.imagePullSecrets | list | `[]` | Image credentials configuration. |
| index_rebuild.initContainers | list | `[]` | Init containers to add to the app pod. |
| index_rebuild.nodeSelector | object | `{}` | Default node selector for app. |
| index_rebuild.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| index_rebuild.podLabels | object | `{}` | Labels for the app deployed pods. |
| index_rebuild.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| index_rebuild.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| index_rebuild.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| index_rebuild.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| index_rebuild.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| index_rebuild.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| index_rebuild.tolerations | list | `[]` | Default tolerations for app. |
| index_rebuild.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| index_rebuild.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| index_rebuild.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| index_rebuild.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| index_rebuild.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| index_rebuild.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| index_rebuild.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| index_rebuild.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| index_rebuild.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| index_rebuild.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| index_rebuild.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| index_rebuild.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| index_rebuild.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| index_rebuild.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| index_rebuild.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| index_rebuild.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| index_rebuild.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| index_rebuild.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| index_rebuild.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| index_rebuild.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| index_rebuild.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| index_rebuild.image.repository | string | `"ia-generative/muffin/worker-document-process"` | Repository to use for the app. |
| index_rebuild.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.ingress.annotations | object | `{}` | Additional ingress annotations. |
| index_rebuild.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| index_rebuild.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| index_rebuild.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| index_rebuild.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| index_rebuild.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| index_rebuild.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| index_rebuild.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| index_rebuild.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| index_rebuild.ingress.labels | object | `{}` | Additional ingress labels. |
| index_rebuild.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.metrics.enabled | bool | `false` | Deploy metrics service. |
| index_rebuild.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| index_rebuild.metrics.service.labels | object | `{}` | Metrics service labels. |
| index_rebuild.metrics.service.port | int | `9000` | Metrics service port. |
| index_rebuild.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| index_rebuild.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| index_rebuild.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| index_rebuild.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| index_rebuild.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| index_rebuild.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| index_rebuild.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| index_rebuild.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| index_rebuild.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| index_rebuild.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| index_rebuild.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| index_rebuild.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| index_rebuild.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| index_rebuild.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| index_rebuild.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `index_rebuild.pdb.minAvailable`. |
| index_rebuild.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Index_rebuild container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| index_rebuild.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| index_rebuild.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| index_rebuild.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| index_rebuild.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| index_rebuild.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| index_rebuild.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Index_rebuild container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| index_rebuild.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| index_rebuild.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| index_rebuild.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| index_rebuild.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| index_rebuild.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| index_rebuild.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Index_rebuild container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| index_rebuild.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| index_rebuild.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| index_rebuild.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| index_rebuild.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| index_rebuild.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| index_rebuild.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| index_rebuild.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| index_rebuild.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| index_rebuild.service.extraPorts | list | `[]` | Extra service ports. |
| index_rebuild.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| index_rebuild.service.port | int | `80` | Port used by the service. |
| index_rebuild.service.portName | string | `"http"` | Port name used by the service. |
| index_rebuild.service.protocol | string | `"TCP"` | Protocol used by the service. |
| index_rebuild.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| index_rebuild.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| index_rebuild.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| index_rebuild.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| index_rebuild.serviceAccount.create | bool | `false` | Create a service account. |
| index_rebuild.serviceAccount.enabled | bool | `false` | Enable the service account. |
| index_rebuild.serviceAccount.name | string | `""` | Service account name. |
| index_rebuild.serviceAccount.role.create | bool | `false` | Should the role be created. |
| index_rebuild.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| index_rebuild.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| index_rebuild.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| index_rebuild.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### Ocr

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.affinity | object | `{}` | Affinity used for app pod. |
| ocr.args | list | `[]` | Ocr container command args. |
| ocr.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| ocr.command | list | `[]` | Ocr container command. |
| ocr.containerPort | string | `nil` | Ocr container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| ocr.containerPortName | string | `"http"` | Ocr container port name. |
| ocr.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| ocr.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| ocr.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| ocr.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| ocr.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| ocr.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| ocr.envFrom | list | `[]` | Ocr container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| ocr.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| ocr.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| ocr.extraPorts | list | `[]` | Ocr extra container ports. |
| ocr.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| ocr.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| ocr.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| ocr.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| ocr.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| ocr.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| ocr.imagePullSecrets | list | `[]` | Image credentials configuration. |
| ocr.initContainers | list | `[]` | Init containers to add to the app pod. |
| ocr.nodeSelector | object | `{}` | Default node selector for app. |
| ocr.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| ocr.podLabels | object | `{}` | Labels for the app deployed pods. |
| ocr.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| ocr.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| ocr.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| ocr.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| ocr.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| ocr.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| ocr.tolerations | list | `[]` | Default tolerations for app. |
| ocr.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| ocr.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| ocr.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| ocr.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| ocr.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| ocr.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| ocr.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| ocr.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| ocr.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| ocr.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| ocr.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| ocr.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| ocr.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| ocr.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| ocr.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| ocr.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| ocr.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| ocr.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| ocr.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| ocr.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| ocr.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| ocr.image.repository | string | `"ia-generative/muffin/worker-ocr"` | Repository to use for the app. |
| ocr.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.ingress.annotations | object | `{}` | Additional ingress annotations. |
| ocr.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| ocr.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| ocr.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| ocr.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| ocr.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| ocr.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| ocr.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| ocr.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| ocr.ingress.labels | object | `{}` | Additional ingress labels. |
| ocr.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.metrics.enabled | bool | `false` | Deploy metrics service. |
| ocr.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| ocr.metrics.service.labels | object | `{}` | Metrics service labels. |
| ocr.metrics.service.port | int | `9000` | Metrics service port. |
| ocr.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| ocr.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| ocr.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| ocr.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| ocr.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| ocr.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| ocr.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| ocr.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| ocr.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| ocr.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| ocr.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| ocr.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| ocr.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| ocr.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| ocr.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| ocr.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| ocr.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| ocr.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| ocr.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| ocr.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| ocr.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| ocr.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| ocr.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| ocr.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| ocr.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `ocr.pdb.minAvailable`. |
| ocr.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| ocr.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| ocr.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| ocr.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| ocr.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| ocr.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| ocr.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| ocr.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| ocr.service.extraPorts | list | `[]` | Extra service ports. |
| ocr.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| ocr.service.port | int | `80` | Port used by the service. |
| ocr.service.portName | string | `"http"` | Port name used by the service. |
| ocr.service.protocol | string | `"TCP"` | Protocol used by the service. |
| ocr.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| ocr.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| ocr.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| ocr.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| ocr.serviceAccount.create | bool | `false` | Create a service account. |
| ocr.serviceAccount.enabled | bool | `false` | Enable the service account. |
| ocr.serviceAccount.name | string | `""` | Service account name. |
| ocr.serviceAccount.role.create | bool | `false` | Should the role be created. |
| ocr.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| ocr.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| ocr.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### OcrLayout

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.affinity | object | `{}` | Affinity used for app pod. |
| ocr_layout.args | list | `[]` | Ocr_layout container command args. |
| ocr_layout.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| ocr_layout.command | list | `[]` | Ocr_layout container command. |
| ocr_layout.containerPort | string | `nil` | Ocr_layout container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| ocr_layout.containerPortName | string | `"http"` | Ocr_layout container port name. |
| ocr_layout.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| ocr_layout.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| ocr_layout.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| ocr_layout.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| ocr_layout.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| ocr_layout.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| ocr_layout.envFrom | list | `[]` | Ocr_layout container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| ocr_layout.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| ocr_layout.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| ocr_layout.extraPorts | list | `[]` | Ocr_layout extra container ports. |
| ocr_layout.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| ocr_layout.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| ocr_layout.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| ocr_layout.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| ocr_layout.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| ocr_layout.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| ocr_layout.imagePullSecrets | list | `[]` | Image credentials configuration. |
| ocr_layout.initContainers | list | `[]` | Init containers to add to the app pod. |
| ocr_layout.nodeSelector | object | `{}` | Default node selector for app. |
| ocr_layout.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| ocr_layout.podLabels | object | `{}` | Labels for the app deployed pods. |
| ocr_layout.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| ocr_layout.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| ocr_layout.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| ocr_layout.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| ocr_layout.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| ocr_layout.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| ocr_layout.tolerations | list | `[]` | Default tolerations for app. |
| ocr_layout.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| ocr_layout.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| ocr_layout.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| ocr_layout.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| ocr_layout.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| ocr_layout.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| ocr_layout.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| ocr_layout.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| ocr_layout.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| ocr_layout.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| ocr_layout.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| ocr_layout.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| ocr_layout.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| ocr_layout.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| ocr_layout.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| ocr_layout.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| ocr_layout.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| ocr_layout.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| ocr_layout.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| ocr_layout.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| ocr_layout.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| ocr_layout.image.repository | string | `"ia-generative/muffin/worker-ocr-layout"` | Repository to use for the app. |
| ocr_layout.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.ingress.annotations | object | `{}` | Additional ingress annotations. |
| ocr_layout.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| ocr_layout.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| ocr_layout.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| ocr_layout.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| ocr_layout.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| ocr_layout.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| ocr_layout.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| ocr_layout.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| ocr_layout.ingress.labels | object | `{}` | Additional ingress labels. |
| ocr_layout.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.metrics.enabled | bool | `false` | Deploy metrics service. |
| ocr_layout.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| ocr_layout.metrics.service.labels | object | `{}` | Metrics service labels. |
| ocr_layout.metrics.service.port | int | `9000` | Metrics service port. |
| ocr_layout.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| ocr_layout.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| ocr_layout.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| ocr_layout.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| ocr_layout.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| ocr_layout.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| ocr_layout.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| ocr_layout.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| ocr_layout.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| ocr_layout.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| ocr_layout.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| ocr_layout.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| ocr_layout.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| ocr_layout.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| ocr_layout.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `ocr_layout.pdb.minAvailable`. |
| ocr_layout.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_layout container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_layout.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_layout.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| ocr_layout.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| ocr_layout.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_layout.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr_layout.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_layout container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_layout.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_layout.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| ocr_layout.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr_layout.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_layout.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr_layout.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_layout container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_layout.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_layout.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| ocr_layout.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr_layout.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_layout.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| ocr_layout.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| ocr_layout.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| ocr_layout.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| ocr_layout.service.extraPorts | list | `[]` | Extra service ports. |
| ocr_layout.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| ocr_layout.service.port | int | `80` | Port used by the service. |
| ocr_layout.service.portName | string | `"http"` | Port name used by the service. |
| ocr_layout.service.protocol | string | `"TCP"` | Protocol used by the service. |
| ocr_layout.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| ocr_layout.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| ocr_layout.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| ocr_layout.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| ocr_layout.serviceAccount.create | bool | `false` | Create a service account. |
| ocr_layout.serviceAccount.enabled | bool | `false` | Enable the service account. |
| ocr_layout.serviceAccount.name | string | `""` | Service account name. |
| ocr_layout.serviceAccount.role.create | bool | `false` | Should the role be created. |
| ocr_layout.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_layout.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| ocr_layout.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| ocr_layout.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### OcrTable

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.affinity | object | `{}` | Affinity used for app pod. |
| ocr_table.args | list | `[]` | Ocr_table container command args. |
| ocr_table.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| ocr_table.command | list | `[]` | Ocr_table container command. |
| ocr_table.containerPort | string | `nil` | Ocr_table container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| ocr_table.containerPortName | string | `"http"` | Ocr_table container port name. |
| ocr_table.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| ocr_table.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| ocr_table.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| ocr_table.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| ocr_table.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| ocr_table.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| ocr_table.envFrom | list | `[]` | Ocr_table container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| ocr_table.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| ocr_table.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| ocr_table.extraPorts | list | `[]` | Ocr_table extra container ports. |
| ocr_table.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| ocr_table.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| ocr_table.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| ocr_table.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| ocr_table.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| ocr_table.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| ocr_table.imagePullSecrets | list | `[]` | Image credentials configuration. |
| ocr_table.initContainers | list | `[]` | Init containers to add to the app pod. |
| ocr_table.nodeSelector | object | `{}` | Default node selector for app. |
| ocr_table.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| ocr_table.podLabels | object | `{}` | Labels for the app deployed pods. |
| ocr_table.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| ocr_table.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| ocr_table.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| ocr_table.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| ocr_table.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| ocr_table.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| ocr_table.tolerations | list | `[]` | Default tolerations for app. |
| ocr_table.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| ocr_table.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| ocr_table.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| ocr_table.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| ocr_table.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| ocr_table.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| ocr_table.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| ocr_table.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| ocr_table.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| ocr_table.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| ocr_table.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| ocr_table.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| ocr_table.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| ocr_table.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| ocr_table.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| ocr_table.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| ocr_table.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| ocr_table.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| ocr_table.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| ocr_table.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| ocr_table.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| ocr_table.image.repository | string | `"ia-generative/muffin/worker-ocr-table"` | Repository to use for the app. |
| ocr_table.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.ingress.annotations | object | `{}` | Additional ingress annotations. |
| ocr_table.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| ocr_table.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| ocr_table.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| ocr_table.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| ocr_table.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| ocr_table.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| ocr_table.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| ocr_table.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| ocr_table.ingress.labels | object | `{}` | Additional ingress labels. |
| ocr_table.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.metrics.enabled | bool | `false` | Deploy metrics service. |
| ocr_table.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| ocr_table.metrics.service.labels | object | `{}` | Metrics service labels. |
| ocr_table.metrics.service.port | int | `9000` | Metrics service port. |
| ocr_table.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| ocr_table.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| ocr_table.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| ocr_table.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| ocr_table.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| ocr_table.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| ocr_table.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| ocr_table.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr_table.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr_table.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| ocr_table.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| ocr_table.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| ocr_table.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| ocr_table.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| ocr_table.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| ocr_table.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| ocr_table.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| ocr_table.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| ocr_table.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| ocr_table.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| ocr_table.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| ocr_table.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| ocr_table.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| ocr_table.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| ocr_table.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| ocr_table.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| ocr_table.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `ocr_table.pdb.minAvailable`. |
| ocr_table.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_table container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_table.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_table.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| ocr_table.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| ocr_table.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_table.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr_table.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_table container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_table.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_table.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| ocr_table.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr_table.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_table.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr_table.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_table container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_table.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_table.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| ocr_table.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr_table.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_table.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| ocr_table.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| ocr_table.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| ocr_table.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| ocr_table.service.extraPorts | list | `[]` | Extra service ports. |
| ocr_table.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| ocr_table.service.port | int | `80` | Port used by the service. |
| ocr_table.service.portName | string | `"http"` | Port name used by the service. |
| ocr_table.service.protocol | string | `"TCP"` | Protocol used by the service. |
| ocr_table.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| ocr_table.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| ocr_table.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| ocr_table.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| ocr_table.serviceAccount.create | bool | `false` | Create a service account. |
| ocr_table.serviceAccount.enabled | bool | `false` | Enable the service account. |
| ocr_table.serviceAccount.name | string | `""` | Service account name. |
| ocr_table.serviceAccount.role.create | bool | `false` | Should the role be created. |
| ocr_table.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_table.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| ocr_table.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| ocr_table.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### OcrVision

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.affinity | object | `{}` | Affinity used for app pod. |
| ocr_vision.args | list | `[]` | Ocr_vision container command args. |
| ocr_vision.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| ocr_vision.command | list | `[]` | Ocr_vision container command. |
| ocr_vision.containerPort | string | `nil` | Ocr_vision container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| ocr_vision.containerPortName | string | `"http"` | Ocr_vision container port name. |
| ocr_vision.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| ocr_vision.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| ocr_vision.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| ocr_vision.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| ocr_vision.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| ocr_vision.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| ocr_vision.envFrom | list | `[]` | Ocr_vision container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| ocr_vision.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| ocr_vision.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| ocr_vision.extraPorts | list | `[]` | Ocr_vision extra container ports. |
| ocr_vision.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| ocr_vision.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| ocr_vision.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| ocr_vision.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| ocr_vision.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| ocr_vision.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| ocr_vision.imagePullSecrets | list | `[]` | Image credentials configuration. |
| ocr_vision.initContainers | list | `[]` | Init containers to add to the app pod. |
| ocr_vision.nodeSelector | object | `{}` | Default node selector for app. |
| ocr_vision.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| ocr_vision.podLabels | object | `{}` | Labels for the app deployed pods. |
| ocr_vision.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| ocr_vision.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| ocr_vision.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| ocr_vision.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| ocr_vision.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| ocr_vision.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| ocr_vision.tolerations | list | `[]` | Default tolerations for app. |
| ocr_vision.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| ocr_vision.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| ocr_vision.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| ocr_vision.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| ocr_vision.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| ocr_vision.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| ocr_vision.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| ocr_vision.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| ocr_vision.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| ocr_vision.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| ocr_vision.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| ocr_vision.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| ocr_vision.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| ocr_vision.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| ocr_vision.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| ocr_vision.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| ocr_vision.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| ocr_vision.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| ocr_vision.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| ocr_vision.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| ocr_vision.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| ocr_vision.image.repository | string | `"ia-generative/muffin/worker-ocr-vision"` | Repository to use for the app. |
| ocr_vision.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.ingress.annotations | object | `{}` | Additional ingress annotations. |
| ocr_vision.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| ocr_vision.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| ocr_vision.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| ocr_vision.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| ocr_vision.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| ocr_vision.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| ocr_vision.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| ocr_vision.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| ocr_vision.ingress.labels | object | `{}` | Additional ingress labels. |
| ocr_vision.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.metrics.enabled | bool | `false` | Deploy metrics service. |
| ocr_vision.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| ocr_vision.metrics.service.labels | object | `{}` | Metrics service labels. |
| ocr_vision.metrics.service.port | int | `9000` | Metrics service port. |
| ocr_vision.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| ocr_vision.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| ocr_vision.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| ocr_vision.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| ocr_vision.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| ocr_vision.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| ocr_vision.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| ocr_vision.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| ocr_vision.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| ocr_vision.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| ocr_vision.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| ocr_vision.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| ocr_vision.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| ocr_vision.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| ocr_vision.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `ocr_vision.pdb.minAvailable`. |
| ocr_vision.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_vision container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_vision.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_vision.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| ocr_vision.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| ocr_vision.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_vision.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr_vision.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_vision container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_vision.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_vision.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| ocr_vision.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr_vision.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_vision.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| ocr_vision.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Ocr_vision container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| ocr_vision.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| ocr_vision.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| ocr_vision.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| ocr_vision.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| ocr_vision.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| ocr_vision.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| ocr_vision.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| ocr_vision.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| ocr_vision.service.extraPorts | list | `[]` | Extra service ports. |
| ocr_vision.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| ocr_vision.service.port | int | `80` | Port used by the service. |
| ocr_vision.service.portName | string | `"http"` | Port name used by the service. |
| ocr_vision.service.protocol | string | `"TCP"` | Protocol used by the service. |
| ocr_vision.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| ocr_vision.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| ocr_vision.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| ocr_vision.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| ocr_vision.serviceAccount.create | bool | `false` | Create a service account. |
| ocr_vision.serviceAccount.enabled | bool | `false` | Enable the service account. |
| ocr_vision.serviceAccount.name | string | `""` | Service account name. |
| ocr_vision.serviceAccount.role.create | bool | `false` | Should the role be created. |
| ocr_vision.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ocr_vision.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| ocr_vision.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| ocr_vision.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### Searxng

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| searxng.enabled | bool | `true` | Enable the SearXNG subchart. |
| searxng.extraConfig | object | `{"server":{"limiter":true},"valkey":{"url":"valkey://muffin-redis:6379/0"}}` | SearXNG settings.yml overrides merged on top of the chart defaults. `extraConfig` is deep-merged via Helm's `mergeOverwrite`, so only the keys below are overridden — the rest (engines, brand, outgoing...) come from the chart's built-in defaults. |
| searxng.persistence | object | `{"config":{"enabled":false}}` | Persistence for the config directory. Disabled by default — the init container copies settings.yml from the ConfigMap into an emptyDir on every pod start, which is the desired behaviour (config changes via Helm upgrade, not persisted across restarts). |
| searxng.podSecurityContext | object | `{"fsGroup":977,"fsGroupChangePolicy":"Always","runAsGroup":977,"runAsNonRoot":true,"runAsUser":977}` | Pod-level security context. The chart defaults to runAsUser: 977 (the `searxng` user inside the image) with fsGroup: 977. We add `fsGroupChangePolicy: Always` so Kubernetes recursively chowns the emptyDir contents on every pod start, ensuring /etc/searxng files are owned by searxng:searxng (the init container copies from a root-owned ConfigMap and cannot chown itself since it runs non-root). |
| searxng.valkey | object | `{"enabled":false}` | Disable the embedded Valkey subchart; we use the top-level `redis` subchart (service: muffin-redis:6379) instead. |

### Tabular

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.affinity | object | `{}` | Affinity used for app pod. |
| tabular.args | list | `[]` | Tabular container command args. |
| tabular.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| tabular.command | list | `[]` | Tabular container command. |
| tabular.containerPort | string | `nil` | Tabular container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| tabular.containerPortName | string | `"http"` | Tabular container port name. |
| tabular.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| tabular.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| tabular.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| tabular.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| tabular.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| tabular.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| tabular.envFrom | list | `[]` | Tabular container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| tabular.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| tabular.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| tabular.extraPorts | list | `[]` | Tabular extra container ports. |
| tabular.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| tabular.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| tabular.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| tabular.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| tabular.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| tabular.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| tabular.imagePullSecrets | list | `[]` | Image credentials configuration. |
| tabular.initContainers | list | `[]` | Init containers to add to the app pod. |
| tabular.nodeSelector | object | `{}` | Default node selector for app. |
| tabular.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| tabular.podLabels | object | `{}` | Labels for the app deployed pods. |
| tabular.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| tabular.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| tabular.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| tabular.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| tabular.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| tabular.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| tabular.tolerations | list | `[]` | Default tolerations for app. |
| tabular.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| tabular.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| tabular.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| tabular.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| tabular.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| tabular.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| tabular.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| tabular.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| tabular.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| tabular.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| tabular.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| tabular.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| tabular.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| tabular.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| tabular.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| tabular.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| tabular.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| tabular.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| tabular.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| tabular.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| tabular.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| tabular.image.repository | string | `"ia-generative/muffin/worker-tabular"` | Repository to use for the app. |
| tabular.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.ingress.annotations | object | `{}` | Additional ingress annotations. |
| tabular.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| tabular.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| tabular.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| tabular.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| tabular.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| tabular.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| tabular.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| tabular.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| tabular.ingress.labels | object | `{}` | Additional ingress labels. |
| tabular.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.metrics.enabled | bool | `false` | Deploy metrics service. |
| tabular.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| tabular.metrics.service.labels | object | `{}` | Metrics service labels. |
| tabular.metrics.service.port | int | `9000` | Metrics service port. |
| tabular.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| tabular.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| tabular.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| tabular.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| tabular.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| tabular.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| tabular.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| tabular.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| tabular.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| tabular.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| tabular.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| tabular.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| tabular.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| tabular.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| tabular.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| tabular.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| tabular.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| tabular.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| tabular.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| tabular.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| tabular.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| tabular.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| tabular.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| tabular.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| tabular.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| tabular.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| tabular.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `tabular.pdb.minAvailable`. |
| tabular.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Tabular container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| tabular.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| tabular.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| tabular.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| tabular.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| tabular.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| tabular.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Tabular container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| tabular.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| tabular.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| tabular.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| tabular.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| tabular.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| tabular.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Tabular container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| tabular.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| tabular.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| tabular.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| tabular.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| tabular.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| tabular.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| tabular.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| tabular.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| tabular.service.extraPorts | list | `[]` | Extra service ports. |
| tabular.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| tabular.service.port | int | `80` | Port used by the service. |
| tabular.service.portName | string | `"http"` | Port name used by the service. |
| tabular.service.protocol | string | `"TCP"` | Protocol used by the service. |
| tabular.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| tabular.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| tabular.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| tabular.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| tabular.serviceAccount.create | bool | `false` | Create a service account. |
| tabular.serviceAccount.enabled | bool | `false` | Enable the service account. |
| tabular.serviceAccount.name | string | `""` | Service account name. |
| tabular.serviceAccount.role.create | bool | `false` | Should the role be created. |
| tabular.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| tabular.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| tabular.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| tabular.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### WorkerDocumentEdit

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.affinity | object | `{}` | Affinity used for app pod. |
| worker_document_edit.args | list | `[]` | Worker_document_edit container command args. |
| worker_document_edit.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| worker_document_edit.command | list | `[]` | Worker_document_edit container command. |
| worker_document_edit.containerPort | string | `nil` | Worker_document_edit container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| worker_document_edit.containerPortName | string | `"http"` | Worker_document_edit container port name. |
| worker_document_edit.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| worker_document_edit.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| worker_document_edit.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| worker_document_edit.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| worker_document_edit.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| worker_document_edit.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| worker_document_edit.envFrom | list | `[]` | Worker_document_edit container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| worker_document_edit.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| worker_document_edit.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| worker_document_edit.extraPorts | list | `[]` | Worker_document_edit extra container ports. |
| worker_document_edit.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| worker_document_edit.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| worker_document_edit.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| worker_document_edit.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| worker_document_edit.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| worker_document_edit.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| worker_document_edit.imagePullSecrets | list | `[]` | Image credentials configuration. |
| worker_document_edit.initContainers | list | `[]` | Init containers to add to the app pod. |
| worker_document_edit.nodeSelector | object | `{}` | Default node selector for app. |
| worker_document_edit.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| worker_document_edit.podLabels | object | `{}` | Labels for the app deployed pods. |
| worker_document_edit.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| worker_document_edit.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| worker_document_edit.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| worker_document_edit.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| worker_document_edit.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| worker_document_edit.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| worker_document_edit.tolerations | list | `[]` | Default tolerations for app. |
| worker_document_edit.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| worker_document_edit.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| worker_document_edit.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| worker_document_edit.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| worker_document_edit.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| worker_document_edit.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| worker_document_edit.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| worker_document_edit.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| worker_document_edit.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| worker_document_edit.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| worker_document_edit.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| worker_document_edit.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| worker_document_edit.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| worker_document_edit.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| worker_document_edit.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| worker_document_edit.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| worker_document_edit.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| worker_document_edit.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| worker_document_edit.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| worker_document_edit.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| worker_document_edit.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| worker_document_edit.image.repository | string | `"ia-generative/muffin/worker-document-edit"` | Repository to use for the app. |
| worker_document_edit.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.ingress.annotations | object | `{}` | Additional ingress annotations. |
| worker_document_edit.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| worker_document_edit.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| worker_document_edit.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| worker_document_edit.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| worker_document_edit.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| worker_document_edit.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| worker_document_edit.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| worker_document_edit.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| worker_document_edit.ingress.labels | object | `{}` | Additional ingress labels. |
| worker_document_edit.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.metrics.enabled | bool | `false` | Deploy metrics service. |
| worker_document_edit.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| worker_document_edit.metrics.service.labels | object | `{}` | Metrics service labels. |
| worker_document_edit.metrics.service.port | int | `9000` | Metrics service port. |
| worker_document_edit.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| worker_document_edit.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| worker_document_edit.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| worker_document_edit.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| worker_document_edit.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| worker_document_edit.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| worker_document_edit.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| worker_document_edit.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| worker_document_edit.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| worker_document_edit.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| worker_document_edit.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| worker_document_edit.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| worker_document_edit.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| worker_document_edit.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| worker_document_edit.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `agent_execution.pdb.minAvailable`. |
| worker_document_edit.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_document_edit container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_document_edit.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_document_edit.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| worker_document_edit.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| worker_document_edit.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_document_edit.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| worker_document_edit.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_document_edit container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_document_edit.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_document_edit.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| worker_document_edit.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| worker_document_edit.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_document_edit.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| worker_document_edit.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_document_edit container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_document_edit.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_document_edit.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| worker_document_edit.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| worker_document_edit.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_document_edit.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| worker_document_edit.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| worker_document_edit.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| worker_document_edit.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| worker_document_edit.service.extraPorts | list | `[]` | Extra service ports. |
| worker_document_edit.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| worker_document_edit.service.port | int | `80` | Port used by the service. |
| worker_document_edit.service.portName | string | `"http"` | Port name used by the service. |
| worker_document_edit.service.protocol | string | `"TCP"` | Protocol used by the service. |
| worker_document_edit.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| worker_document_edit.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| worker_document_edit.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| worker_document_edit.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| worker_document_edit.serviceAccount.create | bool | `false` | Create a service account. |
| worker_document_edit.serviceAccount.enabled | bool | `false` | Enable the service account. |
| worker_document_edit.serviceAccount.name | string | `""` | Service account name. |
| worker_document_edit.serviceAccount.role.create | bool | `false` | Should the role be created. |
| worker_document_edit.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_document_edit.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| worker_document_edit.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| worker_document_edit.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### WorkerEvaluation

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.affinity | object | `{}` | Affinity used for app pod. |
| worker_evaluation.args | list | `[]` | Worker_evaluation container command args. |
| worker_evaluation.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| worker_evaluation.command | list | `[]` | Worker_evaluation container command. |
| worker_evaluation.containerPort | string | `nil` | Worker_evaluation container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| worker_evaluation.containerPortName | string | `"http"` | Worker_evaluation container port name. |
| worker_evaluation.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| worker_evaluation.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| worker_evaluation.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| worker_evaluation.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| worker_evaluation.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| worker_evaluation.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| worker_evaluation.envFrom | list | `[]` | Worker_evaluation container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| worker_evaluation.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| worker_evaluation.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| worker_evaluation.extraPorts | list | `[]` | Worker_evaluation extra container ports. |
| worker_evaluation.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| worker_evaluation.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| worker_evaluation.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| worker_evaluation.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| worker_evaluation.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| worker_evaluation.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| worker_evaluation.imagePullSecrets | list | `[]` | Image credentials configuration. |
| worker_evaluation.initContainers | list | `[]` | Init containers to add to the app pod. |
| worker_evaluation.nodeSelector | object | `{}` | Default node selector for app. |
| worker_evaluation.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| worker_evaluation.podLabels | object | `{}` | Labels for the app deployed pods. |
| worker_evaluation.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| worker_evaluation.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| worker_evaluation.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| worker_evaluation.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| worker_evaluation.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| worker_evaluation.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| worker_evaluation.tolerations | list | `[]` | Default tolerations for app. |
| worker_evaluation.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| worker_evaluation.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| worker_evaluation.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| worker_evaluation.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| worker_evaluation.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| worker_evaluation.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| worker_evaluation.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| worker_evaluation.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| worker_evaluation.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| worker_evaluation.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| worker_evaluation.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| worker_evaluation.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| worker_evaluation.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| worker_evaluation.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| worker_evaluation.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| worker_evaluation.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| worker_evaluation.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| worker_evaluation.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| worker_evaluation.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| worker_evaluation.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| worker_evaluation.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| worker_evaluation.image.repository | string | `"ia-generative/muffin/worker-evaluation"` | Repository to use for the app. |
| worker_evaluation.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.ingress.annotations | object | `{}` | Additional ingress annotations. |
| worker_evaluation.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| worker_evaluation.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| worker_evaluation.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| worker_evaluation.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| worker_evaluation.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| worker_evaluation.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| worker_evaluation.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| worker_evaluation.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| worker_evaluation.ingress.labels | object | `{}` | Additional ingress labels. |
| worker_evaluation.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.metrics.enabled | bool | `false` | Deploy metrics service. |
| worker_evaluation.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| worker_evaluation.metrics.service.labels | object | `{}` | Metrics service labels. |
| worker_evaluation.metrics.service.port | int | `9000` | Metrics service port. |
| worker_evaluation.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| worker_evaluation.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| worker_evaluation.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| worker_evaluation.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| worker_evaluation.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| worker_evaluation.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| worker_evaluation.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| worker_evaluation.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| worker_evaluation.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| worker_evaluation.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| worker_evaluation.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| worker_evaluation.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| worker_evaluation.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| worker_evaluation.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| worker_evaluation.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `agent_execution.pdb.minAvailable`. |
| worker_evaluation.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_evaluation container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_evaluation.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_evaluation.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| worker_evaluation.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| worker_evaluation.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_evaluation.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| worker_evaluation.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_evaluation container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_evaluation.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_evaluation.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| worker_evaluation.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| worker_evaluation.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_evaluation.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| worker_evaluation.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_evaluation container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_evaluation.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_evaluation.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| worker_evaluation.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| worker_evaluation.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_evaluation.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| worker_evaluation.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| worker_evaluation.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| worker_evaluation.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| worker_evaluation.service.extraPorts | list | `[]` | Extra service ports. |
| worker_evaluation.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| worker_evaluation.service.port | int | `80` | Port used by the service. |
| worker_evaluation.service.portName | string | `"http"` | Port name used by the service. |
| worker_evaluation.service.protocol | string | `"TCP"` | Protocol used by the service. |
| worker_evaluation.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| worker_evaluation.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| worker_evaluation.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| worker_evaluation.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| worker_evaluation.serviceAccount.create | bool | `false` | Create a service account. |
| worker_evaluation.serviceAccount.enabled | bool | `false` | Enable the service account. |
| worker_evaluation.serviceAccount.name | string | `""` | Service account name. |
| worker_evaluation.serviceAccount.role.create | bool | `false` | Should the role be created. |
| worker_evaluation.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_evaluation.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| worker_evaluation.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| worker_evaluation.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

### WorkerOwuiSync

#### General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.affinity | object | `{}` | Affinity used for app pod. |
| worker_owui_sync.args | list | `[]` | Worker_owui_sync container command args. |
| worker_owui_sync.automountServiceAccountToken | bool | `false` | Mount the ServiceAccount token into the app pods. Defaults to false so a compromised container holds no API credentials; the API server does not need the token unless the app actually talks to the Kubernetes API. Applied at pod level so it holds even when `serviceAccount.name` points at an SA that automounts. |
| worker_owui_sync.command | list | `[]` | Worker_owui_sync container command. |
| worker_owui_sync.containerPort | string | `nil` | Worker_owui_sync container port number. Set to `null`/`0` (and disable `service`/probes) for components that don't listen on any port (e.g. a queue consumer). |
| worker_owui_sync.containerPortName | string | `"http"` | Worker_owui_sync container port name. |
| worker_owui_sync.deploymentType | string | `"Deployment"` | Workload kind to deploy the app as. One of "Deployment", "StatefulSet" or "DaemonSet" (validated at render time - an unknown value fails instead of producing a release with no workload). Use the top-level `jobs` / `cronjobs` maps for one-off or scheduled workloads. Some values only apply to certain kinds: `replicaCount`/`autoscaling` and `strategy` are Deployment-only (`autoscaling` also works on a StatefulSet), `volumeClaims`/`extraVolumeClaims` are StatefulSet-only, and `updateStrategy` covers StatefulSet and DaemonSet. |
| worker_owui_sync.dnsConfig | object | `{}` | Pod DNS configuration, merged with `dnsPolicy` by the kubelet. |
| worker_owui_sync.dnsPolicy | string | `""` (`ClusterFirstWithHostNet` when `hostNetwork` is true) | Pod DNS policy. Left empty, it defaults to `ClusterFirstWithHostNet` when `hostNetwork` is true (otherwise a hostNetwork pod silently stops resolving cluster DNS) and to the Kubernetes default `ClusterFirst` when it isn't. |
| worker_owui_sync.enableServiceLinks | bool | `false` | Inject the legacy `{SVC}_SERVICE_HOST`/`_PORT` environment variables for every Service in the namespace. Defaults to false: the variables are rarely used, leak the namespace's topology into every container, and can collide with the app's own configuration. Set to true only for an app that genuinely reads them. |
| worker_owui_sync.env | object | `{}` | Map or array of environment variables to inject into the app container (`valueFrom` supported). |
| worker_owui_sync.envCm | object | `{}` | Map of environment variables to inject into a configmap loaded by the app container (`valueFrom` not supported). |
| worker_owui_sync.envFrom | list | `[]` | Worker_owui_sync container env variables loaded from configmap or secret reference. List or map (merged with `global.envFrom` above, global entries first); see `global.envFrom` for both forms. |
| worker_owui_sync.envSecret | object | `{}` | Map of environment variables to inject into a secret loaded by the app container (`valueFrom` not supported). Values placed here are stored in plain text in the values file AND in the Helm release secret, so use it for non-sensitive-but-secret-shaped config only. For real credentials prefer referencing a Secret you manage elsewhere via `envFrom`, or have an operator materialise it (see the `VaultStaticSecret` example under `extraObjects`). |
| worker_owui_sync.extraContainers | list | `[]` | Extra containers to add to the app pod as sidecars. |
| worker_owui_sync.extraPorts | list | `[]` | Worker_owui_sync extra container ports. |
| worker_owui_sync.extraVolumeClaims | list | `[]` | Additional volumeClaims to add, concatenated with `volumeClaims` above at render time. |
| worker_owui_sync.extraVolumeMounts | list | `[]` | Additional volumeMounts to add, concatenated with `volumeMounts` above at render time. |
| worker_owui_sync.extraVolumes | list | `[]` | Additional volumes to add, concatenated with `volumes` above at render time (e.g. to mount a cert or config from a values override without repeating the chart's own volumes). |
| worker_owui_sync.hostAliases | list | `[]` | Host aliases that will be injected at pod-level into /etc/hosts. |
| worker_owui_sync.hostNetwork | bool | `false` | Share the host network namespace. Container ports then bind directly on the node, so they must not collide with anything else running there. |
| worker_owui_sync.hostPID | bool | `false` | Share the host PID namespace (lets the container see and signal host processes). |
| worker_owui_sync.imagePullSecrets | list | `[]` | Image credentials configuration. |
| worker_owui_sync.initContainers | list | `[]` | Init containers to add to the app pod. |
| worker_owui_sync.nodeSelector | object | `{}` | Default node selector for app. |
| worker_owui_sync.podAnnotations | object | `{}` | Annotations for the app deployed pods. |
| worker_owui_sync.podLabels | object | `{}` | Labels for the app deployed pods. |
| worker_owui_sync.podSecurityContext | object | `{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard. Rendered via `toYaml`, so any `PodSecurityContext` field is accepted. Adjust the UID/GID to whatever your image actually ships with - `runAsNonRoot` makes the kubelet refuse to start a container that would run as root, which is the intended failure mode rather than something to switch off. Set to `null` to omit the block entirely. |
| worker_owui_sync.priorityClassName | string | `""` | PriorityClass to schedule the pods with (e.g. `system-node-critical` for a node agent that must not be evicted under pressure). |
| worker_owui_sync.replicaCount | int | `1` | The number of application controller pods to run. Ignored when `deploymentType` is "DaemonSet" (one pod per node) or when `autoscaling.enabled` is true. |
| worker_owui_sync.revisionHistoryLimit | int | `10` | Revision history limit for the app. |
| worker_owui_sync.securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"privileged":false,"readOnlyRootFilesystem":true,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}` | Container-level security context. Defaults to a hardened baseline that satisfies the `restricted` Pod Security Standard: no privilege escalation, no capabilities, immutable root filesystem. Rendered via `toYaml`, so any `SecurityContext` field is accepted. Note `readOnlyRootFilesystem` requires the app to write only to mounted volumes - the default `volumes`/`volumeMounts` below provide an `emptyDir` on /tmp for that reason. Set to `null` to omit the block entirely. |
| worker_owui_sync.terminationGracePeriodSeconds | int | `null` (Kubernetes default of 30) | Grace period, in seconds, given to the pod to shut down cleanly before it is killed. |
| worker_owui_sync.tolerations | list | `[]` | Default tolerations for app. |
| worker_owui_sync.topologySpreadConstraints | list | `[]` | Topology spread constraints used to spread the pods across failure domains. |
| worker_owui_sync.updateStrategy | object | `{}` | Update strategy applied when `deploymentType` is "StatefulSet" or "DaemonSet" (ignored for a Deployment, which uses `strategy` above). Rendered verbatim via `toYaml`, so it takes the native `StatefulSetUpdateStrategy`/`DaemonSetUpdateStrategy` shape of the selected kind; left empty, Kubernetes applies its own default (`RollingUpdate` for both). |
| worker_owui_sync.volumeClaims | list | `[]` | List of volumeClaims to add, rendered as the StatefulSet's `volumeClaimTemplates`. Requires `deploymentType: "StatefulSet"` - setting it on a Deployment or DaemonSet fails at render time rather than being silently dropped (use `volumes`/`extraVolumes` there instead). |
| worker_owui_sync.volumeMounts | list | `[{"mountPath":"/tmp","name":"tmp"}]` | List of mounts to add (normally used with `volumes` or `volumeClaims`). Prefer this for mounts the chart itself always needs; use `extraVolumeMounts` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to the `/tmp` mount backing the hardened `readOnlyRootFilesystem` default (see `volumes` above). |
| worker_owui_sync.volumes | list | `[{"emptyDir":{},"name":"tmp"}]` | List of volumes to add. Prefer this for volumes the chart itself always needs (e.g. security-hardening `emptyDir`s); use `extraVolumes` below for anything you add on top, so overriding one doesn't require repeating the other. Defaults to a `/tmp` `emptyDir`, which is what makes the default `securityContext.readOnlyRootFilesystem: true` usable - drop it only if you also relax that. Helm replaces lists wholesale rather than merging them, so overriding this key means restating the entries you want to keep. |

#### Autoscaling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.autoscaling.enabled | bool | `false` | Enable Horizontal Pod Autoscaler for the app. |
| worker_owui_sync.autoscaling.maxReplicas | int | `3` | Maximum number of replicas for the app. |
| worker_owui_sync.autoscaling.minReplicas | int | `1` | Minimum number of replicas for the app. |
| worker_owui_sync.autoscaling.targetCPUUtilizationPercentage | int | `80` | Average CPU utilization percentage for the app. |
| worker_owui_sync.autoscaling.targetMemoryUtilizationPercentage | int | `80` | Average memory utilization percentage for the app. |

#### GrpcRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.grpcRoute.annotations | object | `{}` | Additional GRPCRoute annotations. |
| worker_owui_sync.grpcRoute.enabled | bool | `false` | Enable a GRPCRoute resource for this service. |
| worker_owui_sync.grpcRoute.hostnames | list | `[]` | Hostnames for the GRPCRoute to match. |
| worker_owui_sync.grpcRoute.labels | object | `{}` | Additional GRPCRoute labels. |
| worker_owui_sync.grpcRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the GRPCRoute to. |
| worker_owui_sync.grpcRoute.rules | list | `[]` | Routing rules for the GRPCRoute. |

#### HttpRoute

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.httpRoute.annotations | object | `{}` | Additional HTTPRoute annotations. |
| worker_owui_sync.httpRoute.enabled | bool | `false` | Enable an HTTPRoute resource for this service. |
| worker_owui_sync.httpRoute.hostnames | list | `[]` | Hostnames for the HTTPRoute to match. |
| worker_owui_sync.httpRoute.labels | object | `{}` | Additional HTTPRoute labels. |
| worker_owui_sync.httpRoute.parentRefs | list | `[]` | Parent references (Gateways) to attach the HTTPRoute to. |
| worker_owui_sync.httpRoute.rules | list | `[]` | Routing rules for the HTTPRoute. |

#### Image

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.image.digest | string | `""` | Image digest (`sha256:...`). When set it takes precedence over `tag`, pinning the exact image content so the same release can never resolve to a different build - preferred over a mutable tag for anything you deploy to production. |
| worker_owui_sync.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy for the app. |
| worker_owui_sync.image.registry | string | `"ghcr.io"` | Registry to use for the app. |
| worker_owui_sync.image.repository | string | `"ia-generative/muffin/worker-owui-sync"` | Repository to use for the app. |
| worker_owui_sync.image.tag | string | `""` | Tag to use for the app. Overrides the image tag whose default is the chart appVersion. |

#### Ingress

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.ingress.annotations | object | `{}` | Additional ingress annotations. |
| worker_owui_sync.ingress.className | string | `""` | Defines which ingress controller will implement the resource. |
| worker_owui_sync.ingress.enabled | bool | `false` | Whether or not ingress should be enabled. |
| worker_owui_sync.ingress.hosts[0].name | string | `"domain.local"` | Name of the host record. |
| worker_owui_sync.ingress.hosts[0].paths | list | `[{"backend":{"portNumber":null,"serviceName":""},"path":"/","pathType":"Prefix"}]` | Paths of the host record to manage routing (avoids repeating the same host for multiple paths/backends). |
| worker_owui_sync.ingress.hosts[0].paths[0].backend.portNumber | string | `nil` | Port used by the backend service linked to the path (leave null to use the app service port). |
| worker_owui_sync.ingress.hosts[0].paths[0].backend.serviceName | string | `""` | Name of the backend service linked to the path (leave empty to use the app service). |
| worker_owui_sync.ingress.hosts[0].paths[0].path | string | `"/"` | Path of the host record to manage routing. |
| worker_owui_sync.ingress.hosts[0].paths[0].pathType | string | `"Prefix"` | Path type of the host record. |
| worker_owui_sync.ingress.labels | object | `{}` | Additional ingress labels. |
| worker_owui_sync.ingress.tls | list | `[]` | Enable TLS configuration. |

#### Metrics

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.metrics.enabled | bool | `false` | Deploy metrics service. |
| worker_owui_sync.metrics.service.annotations | object | `{}` | Metrics service annotations. |
| worker_owui_sync.metrics.service.labels | object | `{}` | Metrics service labels. |
| worker_owui_sync.metrics.service.port | int | `9000` | Metrics service port. |
| worker_owui_sync.metrics.service.portName | string | `"metrics"` | Metrics service port name. |
| worker_owui_sync.metrics.service.targetPort | int | `9000` | Metrics service target port. |
| worker_owui_sync.metrics.service.type | string | `"ClusterIP"` | Type of metrics service to create. |
| worker_owui_sync.metrics.serviceMonitor.annotations | object | `{}` | Prometheus ServiceMonitor annotations. |
| worker_owui_sync.metrics.serviceMonitor.enabled | bool | `false` | Enable a prometheus ServiceMonitor. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].basicAuth.password | string | `""` | The secret in the service monitor namespace that contains the password for authentication. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].basicAuth.username | string | `""` | The secret in the service monitor namespace that contains the username for authentication. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.key | string | `""` | Secret key to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].bearerTokenSecret.name | string | `""` | Secret name to mount to read bearer token for scraping targets. The secret needs to be in the same namespace as the service monitor and accessible by the Prometheus Operator. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].honorLabels | bool | `false` | When true, honorLabels preserves the metric’s labels when they collide with the target’s labels. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].interval | string | `"30s"` | Prometheus ServiceMonitor interval. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].metricRelabelings | list | `[]` | Prometheus MetricRelabelConfigs to apply to samples before ingestion. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].path | string | `"/metrics"` | Path used by the Prometheus ServiceMonitor to scrape metrics. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].relabelings | list | `[]` | Prometheus RelabelConfigs to apply to samples before scraping. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].scheme | string | `""` | Prometheus ServiceMonitor scheme. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].scrapeTimeout | string | `"10s"` | Prometheus ServiceMonitor scrapeTimeout. If empty, Prometheus uses the global scrape timeout unless it is less than the target's scrape interval value in which the latter is used. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].selector | object | `{}` | Prometheus ServiceMonitor selector. |
| worker_owui_sync.metrics.serviceMonitor.endpoints[0].tlsConfig | object | `{}` | Prometheus ServiceMonitor tlsConfig. |
| worker_owui_sync.metrics.serviceMonitor.labels | object | `{}` | Prometheus ServiceMonitor labels. |

#### NetworkPolicy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.networkPolicy.annotations | object | `{}` | Annotations to be added to the app NetworkPolicy. |
| worker_owui_sync.networkPolicy.create | bool | `false` | Create NetworkPolicy object for the app. The policy always selects this component's pods only (via its selector labels), never the whole namespace. |
| worker_owui_sync.networkPolicy.egress | list | `[]` | Egress rules for the NetworkPolicy object. |
| worker_owui_sync.networkPolicy.ingress | list | `[]` | Ingress rules for the NetworkPolicy object. |
| worker_owui_sync.networkPolicy.labels | object | `{}` | Labels to be added to the app NetworkPolicy. |
| worker_owui_sync.networkPolicy.policyTypes | list | `["Ingress"]` | Policy types used in the NetworkPolicy object. |

#### Pdb

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.pdb.annotations | object | `{}` | Annotations to be added to app pdb. |
| worker_owui_sync.pdb.enabled | bool | `false` | Deploy a PodDisruptionBudget for the app |
| worker_owui_sync.pdb.labels | object | `{}` | Labels to be added to app pdb. |
| worker_owui_sync.pdb.maxUnavailable | string | `""` | Number of pods that are unavailable after eviction as number or percentage (eg.: 50%). Has higher precedence over `agent_execution.pdb.minAvailable`. |
| worker_owui_sync.pdb.minAvailable | string | `""` | Number of pods that are available after eviction as number or percentage (eg.: 50%). One of `minAvailable` / `maxUnavailable` must be set when `pdb.enabled` is true - a budget of 0 is the same as having no budget at all, so leaving both empty fails at render time. |

#### Probes

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.probes.livenessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_owui_sync container healthcheck (livenessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_owui_sync.probes.livenessProbe.failureThreshold | int | `3` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_owui_sync.probes.livenessProbe.initialDelaySeconds | int | `30` | Number of seconds after the container has started before probe is initiated. |
| worker_owui_sync.probes.livenessProbe.periodSeconds | int | `30` | How often (in seconds) to perform the probe. |
| worker_owui_sync.probes.livenessProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_owui_sync.probes.livenessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| worker_owui_sync.probes.readinessProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_owui_sync container healthcheck (readinessProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_owui_sync.probes.readinessProbe.failureThreshold | int | `2` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_owui_sync.probes.readinessProbe.initialDelaySeconds | int | `10` | Number of seconds after the container has started before probe is initiated. |
| worker_owui_sync.probes.readinessProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| worker_owui_sync.probes.readinessProbe.successThreshold | int | `2` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_owui_sync.probes.readinessProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |
| worker_owui_sync.probes.startupProbe.exec | object | `{"command":["celery","-A","app.celery_app","inspect","ping","-d","celery@$(HOSTNAME)"]}` | Worker_owui_sync container healthcheck (startupProbe is defined using `toYaml` so it is possible to override it completely). Uses `celery inspect ping` since Celery workers don't expose an HTTP endpoint. |
| worker_owui_sync.probes.startupProbe.failureThreshold | int | `10` | Minimum consecutive failures for the probe to be considered failed after having succeeded. |
| worker_owui_sync.probes.startupProbe.initialDelaySeconds | int | `0` | Number of seconds after the container has started before probe is initiated. |
| worker_owui_sync.probes.startupProbe.periodSeconds | int | `10` | How often (in seconds) to perform the probe. |
| worker_owui_sync.probes.startupProbe.successThreshold | int | `1` | Minimum consecutive successes for the probe to be considered successful after having failed. |
| worker_owui_sync.probes.startupProbe.timeoutSeconds | int | `5` | Number of seconds after which the probe times out. |

#### Resources

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.resources.limits.cpu | string | `"500m"` | CPU limit for the app. |
| worker_owui_sync.resources.limits.memory | string | `"2Gi"` | Memory limit for the app. |
| worker_owui_sync.resources.requests.cpu | string | `"100m"` | CPU request for the app. |
| worker_owui_sync.resources.requests.memory | string | `"256Mi"` | Memory request for the app. |

#### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.service.enabled | bool | `true` | Whether or not to create a Service for the app. Set to `false` for components that don't accept traffic (e.g. a queue consumer with no `containerPort`). |
| worker_owui_sync.service.extraPorts | list | `[]` | Extra service ports. |
| worker_owui_sync.service.nodePort | int | `null` (allocated by Kubernetes) | Port used when type is `NodePort` to expose the service on the given node port. Left empty, Kubernetes allocates one from the configured node-port range, which avoids two releases of this chart colliding on the same hardcoded port. |
| worker_owui_sync.service.port | int | `80` | Port used by the service. |
| worker_owui_sync.service.portName | string | `"http"` | Port name used by the service. |
| worker_owui_sync.service.protocol | string | `"TCP"` | Protocol used by the service. |
| worker_owui_sync.service.type | string | `"ClusterIP"` | Type of service to create for the app. |

#### ServiceAccount

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.serviceAccount.annotations | object | `{}` | Annotations applied to created service account. |
| worker_owui_sync.serviceAccount.automountServiceAccountToken | bool | `false` | Should the service account access token be automount in the pod. |
| worker_owui_sync.serviceAccount.clusterRole.create | bool | `false` | Should the clusterRole be created. |
| worker_owui_sync.serviceAccount.clusterRole.rules | list | `[]` | ClusterRole rules associated with the service account. |
| worker_owui_sync.serviceAccount.create | bool | `false` | Create a service account. |
| worker_owui_sync.serviceAccount.enabled | bool | `false` | Enable the service account. |
| worker_owui_sync.serviceAccount.name | string | `""` | Service account name. |
| worker_owui_sync.serviceAccount.role.create | bool | `false` | Should the role be created. |
| worker_owui_sync.serviceAccount.role.rules | list | `[]` | Role rules associated with the service account. |

#### Strategy

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| worker_owui_sync.strategy.rollingUpdate.maxSurge | int | `1` | The maximum number of pods that can be scheduled above the desired number of pods. |
| worker_owui_sync.strategy.rollingUpdate.maxUnavailable | int | `1` | The maximum number of pods that can be unavailable during the update process. |
| worker_owui_sync.strategy.type | string | `"RollingUpdate"` | Strategy type used to replace old Pods by new ones, can be `Recreate` or `RollingUpdate`. Only applied when `deploymentType` is "Deployment". |

## Sources

**Source code:**

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
