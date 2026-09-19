# Changelog

## [0.6.0-rc.4](https://github.com/IA-Generative/Muffin/compare/v0.6.0-rc.3...v0.6.0-rc.4) (2026-09-19)


### Bug Fixes

* tests and lint ([eb592de](https://github.com/IA-Generative/Muffin/commit/eb592de2e09857dc22d8c687d1a8d489cd475399))

## [0.6.0-rc.3](https://github.com/IA-Generative/Muffin/compare/v0.6.0-rc.2...v0.6.0-rc.3) (2026-09-19)


### Features

* add conversation feedback ([2d7dd03](https://github.com/IA-Generative/Muffin/commit/2d7dd030f2c0ed1a9c46a72ae9bd40b38546b9b3))
* connect evaluation to collections ([700cd53](https://github.com/IA-Generative/Muffin/commit/700cd5376ba1abb5379de7e0fb2eeaaf361129f4))
* connection with evaluation ([35c0974](https://github.com/IA-Generative/Muffin/commit/35c097478364d1a522d2163362a32d6558a0b41f))
* **quality:** filter scores by model and skip already-scored conversations ([3100fd6](https://github.com/IA-Generative/Muffin/commit/3100fd69f0fca742fd0a04b3c01d21f568601a5c))

## [0.6.0-rc.2](https://github.com/IA-Generative/Muffin/compare/v0.6.0-rc.1...v0.6.0-rc.2) (2026-09-19)


### Features

* add new worker ([c2a9add](https://github.com/IA-Generative/Muffin/commit/c2a9add7847f01fce94c2570d1234a4347deb092))

## [0.6.0-rc.1](https://github.com/IA-Generative/Muffin/compare/v0.6.0-rc...v0.6.0-rc.1) (2026-09-19)


### Features

* **worker:** add time tool for LLM temporal context ([#56](https://github.com/IA-Generative/Muffin/issues/56)) ([4c6b06c](https://github.com/IA-Generative/Muffin/commit/4c6b06c4094f73104eb5ff2f78c0337fa577c6a9))

## [0.6.0-rc](https://github.com/IA-Generative/Muffin/compare/v0.5.0...v0.6.0-rc) (2026-09-19)


### Features

* differentiate source types visually in sources panel ([5e6f671](https://github.com/IA-Generative/Muffin/commit/5e6f6711f1d9ae6465c7945882988418a155800e))
* lazy loading des onglets collection avec routes explicites ([165ad0f](https://github.com/IA-Generative/Muffin/commit/165ad0f851dd588f598f829da31434edadeb042f))
* persist feedback state across page reloads ([005283e](https://github.com/IA-Generative/Muffin/commit/005283e426875a93f33e84b71fb936003d521016))
* refonte de la page Tâches en tableau dépliable avec pagination ([b0263e6](https://github.com/IA-Generative/Muffin/commit/b0263e6f9ba14da3a6c87e5e5c7d18d6f773868d))
* restore and edit feedback after page reload ([c3a1398](https://github.com/IA-Generative/Muffin/commit/c3a13987a0078d84d638d3eb9347ec178c352428))
* stream conversation titles with ChatGPT-style animation ([c804bf1](https://github.com/IA-Generative/Muffin/commit/c804bf1a4dcc134fad9e8d7dfca54259e6e3fe30))


### Bug Fixes

* add migration jobs into docker compose ([ed28d15](https://github.com/IA-Generative/Muffin/commit/ed28d15863985c321212d800f2f447ba6938993c))
* **backend:** delete Meilisearch embeddings when deleting/reindexing a document ([81d426b](https://github.com/IA-Generative/Muffin/commit/81d426b7e4788492964d7f222df7859e90152306))
* **frontend:** show clean error messages instead of technical backend errors ([92f73f8](https://github.com/IA-Generative/Muffin/commit/92f73f8adb09266a5aa17c0daa820e02224c4d19))
* get run after leaving conversation ([009f3c1](https://github.com/IA-Generative/Muffin/commit/009f3c1b3f5257d281c5200aaa567a92b3e1a135))
* lint front ([b7d2680](https://github.com/IA-Generative/Muffin/commit/b7d2680566b7285667a3418c8cbf44cdb3d2f652))
* llm interaction bug with collection_id, document_id ([7ff2776](https://github.com/IA-Generative/Muffin/commit/7ff2776a1516a4eab4ce33930abf7ec21b1e4d0c))
* re play when it's on error ([a555d23](https://github.com/IA-Generative/Muffin/commit/a555d231de334a0f5a6ef29a56191bce22239ef5))
* visual fix on message ... that go upper now ([e6371f2](https://github.com/IA-Generative/Muffin/commit/e6371f2d59fbea66edd311274cc060629833baf8))
* web search 500 error and planner short-circuit ([df0f8d7](https://github.com/IA-Generative/Muffin/commit/df0f8d7cd6a1527af392a2a69e61b9027e1478ac))

## [0.5.0](https://github.com/IA-Generative/Muffin/compare/v0.4.0...v0.5.0) (2026-09-19)


### Features

* **backend:** implement discussion-quality scoring ([#31](https://github.com/IA-Generative/Muffin/issues/31) - backend half) ([6cbf0c9](https://github.com/IA-Generative/Muffin/commit/6cbf0c969a8d27e3f9acd8738a4930eaa4b95b14))
* **backend:** implement retrieval evaluation ([#11](https://github.com/IA-Generative/Muffin/issues/11) - backend half) ([9df2519](https://github.com/IA-Generative/Muffin/commit/9df25191c3887faa2e92d6ed7a58e4e5426157bb))
* **backend:** materialize agent citations as Source rows ([af67622](https://github.com/IA-Generative/Muffin/commit/af67622fc11b12df6b0bd8a234cb6d23f3152690)), closes [#39](https://github.com/IA-Generative/Muffin/issues/39)
* **backend:** persist and aggregate user feedback ([a4887b2](https://github.com/IA-Generative/Muffin/commit/a4887b231428ee638198f3b44b59da080ff43f90)), closes [#30](https://github.com/IA-Generative/Muffin/issues/30)
* evaluate both validated and unvalidated QA pairs, three-way metrics ([33c92e8](https://github.com/IA-Generative/Muffin/commit/33c92e88eb042920a25a7b14164e83016fbc824a))
* **frontend:** add a Qualité dashboard for the 4 quality metric families ([648695e](https://github.com/IA-Generative/Muffin/commit/648695e153cc122ae7f7fe223015aa677d27c32b))
* **frontend:** sample sizes, eval-run picker, cost/latency, discussion length ([163fa5d](https://github.com/IA-Generative/Muffin/commit/163fa5d3b605669b559b7523eaa987f8412db0fd))
* wire source ids into the frontend and feedback into FeedbackSource ([96ef9f4](https://github.com/IA-Generative/Muffin/commit/96ef9f445e30416b58f131933dc1198e8528e935)), closes [#41](https://github.com/IA-Generative/Muffin/issues/41)
* **worker:** add score_discussion, a second task in worker/evaluation ([#31](https://github.com/IA-Generative/Muffin/issues/31)) ([4435090](https://github.com/IA-Generative/Muffin/commit/443509098a9c0d3e7c8695ee66f0a610ef882401))
* **worker:** add worker/evaluation, a dedicated retrieval-evaluation worker ([#11](https://github.com/IA-Generative/Muffin/issues/11)) ([d2ad77c](https://github.com/IA-Generative/Muffin/commit/d2ad77cb6f30a359144fb7f6cbd518d1b9d24798))


### Bug Fixes

* **docker:** add HEALTHCHECK to all service Dockerfiles ([7a3faf5](https://github.com/IA-Generative/Muffin/commit/7a3faf5da71bb18ba6bd64c5e78a89f3a74bf56f))

## [0.5.0-rc.4](https://github.com/IA-Generative/Muffin/compare/v0.5.0-rc.3...v0.5.0-rc.4) (2026-09-19)


### Features

* **backend:** implement discussion-quality scoring ([#31](https://github.com/IA-Generative/Muffin/issues/31) - backend half) ([56d6cd5](https://github.com/IA-Generative/Muffin/commit/56d6cd562204def7b7a9fbaeb308ea80b74b8d67))
* **worker:** add score_discussion, a second task in worker/evaluation ([#31](https://github.com/IA-Generative/Muffin/issues/31)) ([2f38306](https://github.com/IA-Generative/Muffin/commit/2f38306ec1503ee4937985fa8f318e03e5edeafe))

## [0.5.0-rc.3](https://github.com/IA-Generative/Muffin/compare/v0.5.0-rc.2...v0.5.0-rc.3) (2026-09-19)


### Features

* **backend:** implement retrieval evaluation ([#11](https://github.com/IA-Generative/Muffin/issues/11) - backend half) ([8885730](https://github.com/IA-Generative/Muffin/commit/88857304babfbe2dfe4312211cbd6b1ce01f4b10))
* evaluate both validated and unvalidated QA pairs, three-way metrics ([9e202bc](https://github.com/IA-Generative/Muffin/commit/9e202bc6d7e9ee91c861e90417695b916cad6041))
* **worker:** add worker/evaluation, a dedicated retrieval-evaluation worker ([#11](https://github.com/IA-Generative/Muffin/issues/11)) ([c50d810](https://github.com/IA-Generative/Muffin/commit/c50d81027cb9664b6020b954f81a6391c120655d))

## [0.5.0-rc.2](https://github.com/IA-Generative/Muffin/compare/v0.5.0-rc.1...v0.5.0-rc.2) (2026-09-19)


### Features

* **frontend:** add a Qualité dashboard for the 4 quality metric families ([ff94228](https://github.com/IA-Generative/Muffin/commit/ff94228a615c29cfac62ee6187b834ec0f7447d7))
* **frontend:** sample sizes, eval-run picker, cost/latency, discussion length ([5f8fd16](https://github.com/IA-Generative/Muffin/commit/5f8fd16fd0adf905a501455bb774e6113fed1131))

## [0.5.0-rc.1](https://github.com/IA-Generative/Muffin/compare/v0.5.0-rc...v0.5.0-rc.1) (2026-09-19)


### Features

* **backend:** materialize agent citations as Source rows ([8221da1](https://github.com/IA-Generative/Muffin/commit/8221da12acfd56417a732f78a0c3c09cf9607eee)), closes [#39](https://github.com/IA-Generative/Muffin/issues/39)
* wire source ids into the frontend and feedback into FeedbackSource ([48de759](https://github.com/IA-Generative/Muffin/commit/48de759ab45cc1dd4d670ad068ed262d52410c6c)), closes [#41](https://github.com/IA-Generative/Muffin/issues/41)

## [0.5.0-rc](https://github.com/IA-Generative/Muffin/compare/v0.4.0...v0.5.0-rc) (2026-09-19)


### Features

* **backend:** persist and aggregate user feedback ([88c4b09](https://github.com/IA-Generative/Muffin/commit/88c4b093276e66172b7134040cf2d6997dd59ce5)), closes [#30](https://github.com/IA-Generative/Muffin/issues/30)

## [0.4.0](https://github.com/IA-Generative/Muffin/compare/v0.3.1...v0.4.0) (2026-09-19)


### Features

* **agent:** add web_search tool backed by SearXNG ([863181e](https://github.com/IA-Generative/Muffin/commit/863181e6b0ac14a8ff6d6e7ca15253f209086804))
* **agent:** route group-shared collections into the agent's VDB search ([86fec3f](https://github.com/IA-Generative/Muffin/commit/86fec3f8a8f45a13b00d37cd846765f8bbc71bb7))
* **auth:** declare OpenAPI security schemes for Swagger UI ([0e54123](https://github.com/IA-Generative/Muffin/commit/0e54123e647eed8e862a8d773e60fd21dc991352))
* **backend:** add web_search_enabled flag to runs ([5d4c885](https://github.com/IA-Generative/Muffin/commit/5d4c88566bc8a495f0f0c0adc18be6f7b56c1e06))
* **backend:** persist and expose the agent's groundedness verdict ([a9201e2](https://github.com/IA-Generative/Muffin/commit/a9201e29e310cbb6878802294a4a36da73b81e3d)), closes [#32](https://github.com/IA-Generative/Muffin/issues/32)
* **collections:** private/public visibility and hashed collection sharing ([f8f2a34](https://github.com/IA-Generative/Muffin/commit/f8f2a34f56d4379b859f55fd4ba451692503c57a))
* **frontend:** add a web-search toggle to the composer's Outils menu ([d0ba546](https://github.com/IA-Generative/Muffin/commit/d0ba546cee257f57735f54ff992c5e58d67a02fe))
* **helm:** add searxng as a chart dependency ([277f453](https://github.com/IA-Generative/Muffin/commit/277f45390edc261054559028941169d47a876b37))
* **search:** replace Qdrant with Meilisearch for hybrid search ([625f93f](https://github.com/IA-Generative/Muffin/commit/625f93ff59b95c400cbe14df6792cc9f2d1a4554))


### Bug Fixes

* **helm:** bump chart version to 0.2.3 ([5a7b214](https://github.com/IA-Generative/Muffin/commit/5a7b214a34ecf8401ddb6002210c541cfcc1d440))

## [0.3.1](https://github.com/IA-Generative/Muffin/compare/v0.3.0...v0.3.1) (2026-09-18)


### Bug Fixes

* **helm:** bump chart version to 0.2.1 ([8245eb1](https://github.com/IA-Generative/Muffin/commit/8245eb1bb6cee218882469de6ce8b21aabe070aa))
* **helm:** rename chart from "helm" to "muffin" ([8df0889](https://github.com/IA-Generative/Muffin/commit/8df08892ccb414c1c2688a4ec2c690a1128729cb))

## [0.3.1-rc](https://github.com/IA-Generative/Muffin/compare/v0.3.0...v0.3.1-rc) (2026-09-18)


### Bug Fixes

* **helm:** bump chart version to 0.2.1 ([6842d67](https://github.com/IA-Generative/Muffin/commit/6842d67872ea57a853a5a490337d04b15b66d10e))
* **helm:** rename chart from "helm" to "muffin" ([f4297e1](https://github.com/IA-Generative/Muffin/commit/f4297e1189b4285b5c72023c6735f2cac24a24a8))

## [0.3.0](https://github.com/IA-Generative/Muffin/compare/v0.2.0...v0.3.0) (2026-09-18)


### Features

* **chat:** let users attach collections to search via a "+" composer picker ([f78d8b8](https://github.com/IA-Generative/Muffin/commit/f78d8b8cd07c383573ea6bb71a39df2a3f3ae802))
* **chat:** split sources into document/tool cards, add page+chunk modal ([3e2b76a](https://github.com/IA-Generative/Muffin/commit/3e2b76aaf270f84300e8e7ee086342336e59c6a3))
* **ci:** add helm chart linting and release pipelines ([6a08243](https://github.com/IA-Generative/Muffin/commit/6a08243adbcc71dc2c031873f143dd7de0ffcfca))
* deep-linkable document modal, two-column layout, backend-proxied screenshots ([960ad86](https://github.com/IA-Generative/Muffin/commit/960ad867367178e496b7bf7b62fcadf879828843))
* document detail modal - summary, tags, paginated pages, QA, entities ([35a4cd7](https://github.com/IA-Generative/Muffin/commit/35a4cd708b7ec9dd521a816ab54842510110fda5))
* **frontend:** animated loading dots and French step labels while a run is in progress ([fd1ceef](https://github.com/IA-Generative/Muffin/commit/fd1ceef60a1b87fcec02ad1af721d97985e69a08))
* **frontend:** collapsible sidebar and conversation title tooltip ([360e287](https://github.com/IA-Generative/Muffin/commit/360e287c131ecf8e3feb4b63e1a23200ec548e90))
* **frontend:** paginate the conversation sidebar (infinite scroll) ([cf8ac7e](https://github.com/IA-Generative/Muffin/commit/cf8ac7ee108e01622805cc45eef1e636a2da47fb))
* **frontend:** rename and delete conversations from the sidebar ([0854225](https://github.com/IA-Generative/Muffin/commit/085422577a645a473bb5d96f34212cae36830a07))
* **frontend:** show a run's step-by-step execution detail alongside sources ([cf5794f](https://github.com/IA-Generative/Muffin/commit/cf5794ffb4a6b380bbbca67b8aed210e2b009d93))
* **frontend:** show elapsed time next to the pending-run indicator ([dd81ad6](https://github.com/IA-Generative/Muffin/commit/dd81ad6bad15ee6c5293c8838a682120638ce2eb))
* **frontend:** wire the chat UI to the real research-agent run API ([09173ba](https://github.com/IA-Generative/Muffin/commit/09173badd24f428a72863b9337f89fd7b4b486e5))
* **helm:** add chart dependencies ([44ab153](https://github.com/IA-Generative/Muffin/commit/44ab1536027a1331375325ed1fda6728bd7d1a53))
* **helm:** add helm charts ([a393cd3](https://github.com/IA-Generative/Muffin/commit/a393cd3abdde59541aaf049466ae2a9aeb83d38d))
* **helm:** replace servicename placeholder with actual components ([d9b26c5](https://github.com/IA-Generative/Muffin/commit/d9b26c536f40b530c820337cb68213d58eb134d8))
* **research-agent:** add knowledge-base introspection tools to the graph ([096f30a](https://github.com/IA-Generative/Muffin/commit/096f30a19fe3f007a3eceb7c8fc6cd2f53f399f1))
* **research-agent:** auto-generate the conversation title from the first Q&A ([f6cdbea](https://github.com/IA-Generative/Muffin/commit/f6cdbea88ae733ecee039983230c8c5f5c571345))
* **research-agent:** implement Run/RunEvent persistence and the LangGraph research DAG ([b44609f](https://github.com/IA-Generative/Muffin/commit/b44609f3f1480f2319f0508c4d47078debd1e0ec))
* **research-agent:** let users pin collections to search from the chat composer ([adad5c0](https://github.com/IA-Generative/Muffin/commit/adad5c068a981b5233bcc3fc6ab47d1b395ad395))
* **research-agent:** persist conversation history and restore it in the frontend ([e5fbd68](https://github.com/IA-Generative/Muffin/commit/e5fbd68f9c311958c02d3efb6791b4fea2fe710c))
* **research-agent:** replace full-text chunk search with Qdrant vector search ([231916f](https://github.com/IA-Generative/Muffin/commit/231916f352d724ef1fa8542d9145db4d8003b786))
* **research-agent:** search qa cache, then summaries, then chunks ([9bff92a](https://github.com/IA-Generative/Muffin/commit/9bff92a423c81672753d2bfef54c85556fbdaa4b))
* **research-agent:** wire HITL end-to-end (resume API, frontend, durable checkpointer) ([ccedddc](https://github.com/IA-Generative/Muffin/commit/ccedddcce8b251ac47071d3a7f51372f33fa1dcc))
* scope entities/relations to the document they were extracted from ([1cd81bc](https://github.com/IA-Generative/Muffin/commit/1cd81bcc429f36050b531f86e7a04210402a6748))


### Bug Fixes

* **backend:** resolve a working embedding model for new collections ([ca0d7f5](https://github.com/IA-Generative/Muffin/commit/ca0d7f5d1b19e8c46b83156c88d1251053928d7b))
* **ci:** gitlab kaniko jobs pointed at a different project's Dockerfiles ([e6d52e6](https://github.com/IA-Generative/Muffin/commit/e6d52e62d2d29a365a946122d69928b07c433c85))
* **ci:** prefix gitlab image tags with muffin- ([9fe2d3a](https://github.com/IA-Generative/Muffin/commit/9fe2d3a7ff9c8e17bb431d8d04bca8cb5e08d782))
* **execution-detail:** 422 on GET /runs/{id}/events emptied the panel every time ([da60d46](https://github.com/IA-Generative/Muffin/commit/da60d468e6488516df4960932b5fb6a22a26822c))
* **execution-detail:** timeline groups frozen at mount, never updated ([9b59184](https://github.com/IA-Generative/Muffin/commit/9b5918463171ce4b99e085f1d12353d7689cf47f))
* **frontend:** conversation menu got clipped on the first row and didn't close reliably ([797de83](https://github.com/IA-Generative/Muffin/commit/797de8347d22e208bd479ca513a903ed40c0db91))
* **frontend:** fix TS build errors breaking the frontend Docker build ([61637b7](https://github.com/IA-Generative/Muffin/commit/61637b72a969cebbed62badcb5089cdef51559dc))
* **frontend:** render citation footnotes instead of raw evidence uuids ([91117a5](https://github.com/IA-Generative/Muffin/commit/91117a5818559d6a47e9d3375025ea28a53f811e))
* **frontend:** resolve aliased conversation id before renaming ([7f21e5a](https://github.com/IA-Generative/Muffin/commit/7f21e5a9811e7a36cceb008e0ab8a3ee036fb327))
* **frontend:** sync the URL to the real conversation id after the first run ([ff39c8e](https://github.com/IA-Generative/Muffin/commit/ff39c8ec9d861ad1d2eed9545f70a6a3dda00ce2))
* **research-agent:** resolve follow-up questions against conversation history ([e0b984a](https://github.com/IA-Generative/Muffin/commit/e0b984a5d9ca36e8ccc318d0d90750d261dbdc4c))
* **research-agent:** restore per-node current_activity updates during a run ([08182e9](https://github.com/IA-Generative/Muffin/commit/08182e958b3a0386f069860e1bfa5cbe9b0c2434))
* **research-agent:** restored messages weren't citation-processed, and unmatched ids leaked raw ([1009945](https://github.com/IA-Generative/Muffin/commit/1009945f15a50aa04e09a8bd5e030cb536d8bcb8))
* **research-agent:** three bugs found testing "how many collections do I have" live ([9e1cbe1](https://github.com/IA-Generative/Muffin/commit/9e1cbe14240b2413c3e5cfe1b3b1ca9a397c3ae0))


### Performance Improvements

* **research-agent:** cap conversation history threaded into a new run ([4fe760b](https://github.com/IA-Generative/Muffin/commit/4fe760b6216a003240488653b78b3934888ba657))
* **research-agent:** fetch the chat model once per run instead of once per node ([064ec1e](https://github.com/IA-Generative/Muffin/commit/064ec1e44494dd0a31f2471e3af87fce760045bb))
* **research-agent:** skip the grounding check for simple/meta answers ([91a3427](https://github.com/IA-Generative/Muffin/commit/91a3427a103fffa90e0ee59b17f71d514a2678d3))

## [0.3.0-rc.1](https://github.com/IA-Generative/Muffin/compare/v0.3.0-rc...v0.3.0-rc.1) (2026-09-18)


### Features

* **chat:** let users attach collections to search via a "+" composer picker ([9d8c5d5](https://github.com/IA-Generative/Muffin/commit/9d8c5d59acd0d646d640c2a3fef442df770bf8a5))
* **chat:** split sources into document/tool cards, add page+chunk modal ([0d335c8](https://github.com/IA-Generative/Muffin/commit/0d335c8f8388082d9104aef95abc22f1c623a6e3))
* deep-linkable document modal, two-column layout, backend-proxied screenshots ([99692a7](https://github.com/IA-Generative/Muffin/commit/99692a708f9d2519ac3eee66ccf82610e0814dcd))
* document detail modal - summary, tags, paginated pages, QA, entities ([cbdc0a5](https://github.com/IA-Generative/Muffin/commit/cbdc0a588eda0c3e33633615ea7a975876bb4dee))
* **frontend:** animated loading dots and French step labels while a run is in progress ([9172117](https://github.com/IA-Generative/Muffin/commit/9172117f4f07a0332b0a8050f0323296eec2deea))
* **frontend:** collapsible sidebar and conversation title tooltip ([51203b2](https://github.com/IA-Generative/Muffin/commit/51203b23b71bbe2a40ad2dc6bb7d7b54356b5ba4))
* **frontend:** paginate the conversation sidebar (infinite scroll) ([c8159d1](https://github.com/IA-Generative/Muffin/commit/c8159d195b129e9f6c2b86ad0d573d2d3f912458))
* **frontend:** rename and delete conversations from the sidebar ([58d4626](https://github.com/IA-Generative/Muffin/commit/58d4626a2dade342c80683a81a26fa3d5cbc29ea))
* **frontend:** show a run's step-by-step execution detail alongside sources ([c3f473a](https://github.com/IA-Generative/Muffin/commit/c3f473af45730cf9f88ecd72fbf7eae6d6a53f2e))
* **frontend:** show elapsed time next to the pending-run indicator ([95f7d0d](https://github.com/IA-Generative/Muffin/commit/95f7d0d53228bf6208dd678da87728c3d12b8d83))
* **frontend:** wire the chat UI to the real research-agent run API ([12f2201](https://github.com/IA-Generative/Muffin/commit/12f2201345fa60801b5fb1abf3aa606bb21b7805))
* **research-agent:** add knowledge-base introspection tools to the graph ([33c8088](https://github.com/IA-Generative/Muffin/commit/33c808853d2e53e48319675bd0056321afc52a10))
* **research-agent:** auto-generate the conversation title from the first Q&A ([14b82b0](https://github.com/IA-Generative/Muffin/commit/14b82b0d7240669502296276f4174436ed765888))
* **research-agent:** implement Run/RunEvent persistence and the LangGraph research DAG ([2f277aa](https://github.com/IA-Generative/Muffin/commit/2f277aa2189018ff5c8bec14bff3e9190ad67721))
* **research-agent:** let users pin collections to search from the chat composer ([658628d](https://github.com/IA-Generative/Muffin/commit/658628d1547722d42d683cad3db05eb5f2b55840))
* **research-agent:** persist conversation history and restore it in the frontend ([f25ce53](https://github.com/IA-Generative/Muffin/commit/f25ce530920fab1e331bf1fdb8303ee1b3b60ba9))
* **research-agent:** replace full-text chunk search with Qdrant vector search ([6c86a58](https://github.com/IA-Generative/Muffin/commit/6c86a58d6c2ab954b093f04bbabd3d31fdebdefb))
* **research-agent:** search qa cache, then summaries, then chunks ([5f92a66](https://github.com/IA-Generative/Muffin/commit/5f92a66114be3f0781ba9faac22c4c77b6560ce5))
* **research-agent:** wire HITL end-to-end (resume API, frontend, durable checkpointer) ([c23232a](https://github.com/IA-Generative/Muffin/commit/c23232afb6710e73663adc261e857a2277168556))
* scope entities/relations to the document they were extracted from ([8941227](https://github.com/IA-Generative/Muffin/commit/8941227e47b485e525cd5e1de7bc04cc92126aa1))


### Bug Fixes

* **backend:** resolve a working embedding model for new collections ([fbdeeae](https://github.com/IA-Generative/Muffin/commit/fbdeeae1a18f175856fb3c766f1a486e6dd6eee6))
* **ci:** gitlab kaniko jobs pointed at a different project's Dockerfiles ([168d2eb](https://github.com/IA-Generative/Muffin/commit/168d2ebcbc72dc0a3cd2f599fe785239fa1062a0))
* **ci:** prefix gitlab image tags with muffin- ([c3522eb](https://github.com/IA-Generative/Muffin/commit/c3522eb855e105ed7f76ada0fdde31f6abb50e91))
* **execution-detail:** 422 on GET /runs/{id}/events emptied the panel every time ([c2e8c89](https://github.com/IA-Generative/Muffin/commit/c2e8c8933deef7b648393feea2b600caf1280fe5))
* **execution-detail:** timeline groups frozen at mount, never updated ([2f42f26](https://github.com/IA-Generative/Muffin/commit/2f42f26d07cc10dbb33acf371bd66a9e1dcaa2e7))
* **frontend:** conversation menu got clipped on the first row and didn't close reliably ([4aeb60d](https://github.com/IA-Generative/Muffin/commit/4aeb60d83e6faedf8bf4fe96f78da1a0ce376c01))
* **frontend:** fix TS build errors breaking the frontend Docker build ([e99caf0](https://github.com/IA-Generative/Muffin/commit/e99caf0d9312105949c6d26a0e24265e17583967))
* **frontend:** render citation footnotes instead of raw evidence uuids ([9dfe2c5](https://github.com/IA-Generative/Muffin/commit/9dfe2c5ddae3b49ab9917fb7f5970b5904af7b86))
* **frontend:** resolve aliased conversation id before renaming ([1edf89a](https://github.com/IA-Generative/Muffin/commit/1edf89a569254083742960f6ba7f3db08def9b69))
* **frontend:** sync the URL to the real conversation id after the first run ([81f1aef](https://github.com/IA-Generative/Muffin/commit/81f1aef354f1a27cd9880e9644c5f842e540920c))
* **research-agent:** resolve follow-up questions against conversation history ([7ac9131](https://github.com/IA-Generative/Muffin/commit/7ac9131d7c5e48aa5fc728fa85aeb0eed36cee44))
* **research-agent:** restore per-node current_activity updates during a run ([2ff4a2c](https://github.com/IA-Generative/Muffin/commit/2ff4a2ca42bfbac1b1c5cb5d1f322ac225a55163))
* **research-agent:** restored messages weren't citation-processed, and unmatched ids leaked raw ([e6f8e87](https://github.com/IA-Generative/Muffin/commit/e6f8e8734563235de2818109428951a0a81a641b))
* **research-agent:** three bugs found testing "how many collections do I have" live ([f193cd4](https://github.com/IA-Generative/Muffin/commit/f193cd4ae3ca0192769c1d10a64b5b25717e2c76))


### Performance Improvements

* **research-agent:** cap conversation history threaded into a new run ([8e78387](https://github.com/IA-Generative/Muffin/commit/8e7838736cf7449e15252c8da5ed82767e7704b7))
* **research-agent:** fetch the chat model once per run instead of once per node ([78ce5c5](https://github.com/IA-Generative/Muffin/commit/78ce5c553f6c3269d626e227c2a216f5f9367c94))
* **research-agent:** skip the grounding check for simple/meta answers ([8083fc7](https://github.com/IA-Generative/Muffin/commit/8083fc76524a55a547b36b1b3695fad1fda463ca))

## [0.3.0-rc](https://github.com/IA-Generative/Muffin/compare/v0.2.0...v0.3.0-rc) (2026-09-17)


### Features

* **ci:** add helm chart linting and release pipelines ([57bb5c9](https://github.com/IA-Generative/Muffin/commit/57bb5c9ce5f05e857c675e926aac5907baae9b96))
* **helm:** add chart dependencies ([28a4059](https://github.com/IA-Generative/Muffin/commit/28a4059d6cf2c5b7033dec04c6b6dba241e07254))
* **helm:** add helm charts ([2eb8bca](https://github.com/IA-Generative/Muffin/commit/2eb8bca0b8735f6d19e038e03a0f63c3d2071eb2))
* **helm:** replace servicename placeholder with actual components ([9de47ed](https://github.com/IA-Generative/Muffin/commit/9de47edb25a05454da6e5a83367f0e4f0494bb5b))

## [0.2.0](https://github.com/IA-Generative/Muffin/compare/v0.1.0...v0.2.0) (2026-09-17)


### Features

* add backend service with Redis and Keycloak integration ([951cd40](https://github.com/IA-Generative/Muffin/commit/951cd402da360090d014669ba1d910ad8a4d8b41))
* add chat functionality with message handling and sources display ([7f8b6bf](https://github.com/IA-Generative/Muffin/commit/7f8b6bf1ae732fe5cee28fea768cad805915c70e))
* add qa into front ([0ae35f8](https://github.com/IA-Generative/Muffin/commit/0ae35f88858e20c809525c3ae2e7d4637730b8c4))
* admini collections ([478ac2f](https://github.com/IA-Generative/Muffin/commit/478ac2ff9a301dc8f689a7203c7f766f63e15180))
* **backend:** add collections CRUD, repository/service layers, and generic pagination ([b24684c](https://github.com/IA-Generative/Muffin/commit/b24684cc1b8cef04670b75163febbc530e180009))
* **backend:** add kecloak integration ([1c200bf](https://github.com/IA-Generative/Muffin/commit/1c200bf8f56edcd79eb6d9355822195997454827))
* **backend:** add worker-facing internal API (API key auth) for document ingestion ([55a9564](https://github.com/IA-Generative/Muffin/commit/55a9564fb83e4a57fa3d5474b5eeac190f842f57))
* **bakend:** add models choice ([1d96b93](https://github.com/IA-Generative/Muffin/commit/1d96b9379fdc0b0aad6d9a565231f772d3438e6a))
* **ci:** add initial configuration files for release management and CI/CD ([d2e4908](https://github.com/IA-Generative/Muffin/commit/d2e4908e65d56b9ba84f0c21a51f359391004d42))
* **collections:** persist chunking/embedding/instructions settings, add per-step model pickers ([d03f364](https://github.com/IA-Generative/Muffin/commit/d03f3648dfcf7705bd0457fc390b8855feba37ee))
* **collections:** sliding-window params per pipeline step, new Résumé section, modern card layout ([32ee12f](https://github.com/IA-Generative/Muffin/commit/32ee12fdae6de3efd5a256a2aafe67221bf931e6))
* **documents:** real upload/delete/reindex wired end-to-end, plus type-to-confirm delete ([0b6d6af](https://github.com/IA-Generative/Muffin/commit/0b6d6af321163859487638b00dc8afacb9bba7a0))
* enhance collections management with detailed views, pagination, and search functionality ([c4a7b7b](https://github.com/IA-Generative/Muffin/commit/c4a7b7b0310e40b8a36acaca6a8abd144c28142e))
* **frontend:** add vue-router for conversation and collection URLs ([6bd5e83](https://github.com/IA-Generative/Muffin/commit/6bd5e834176b6139dbf666615cf623edfd87983b))
* **frontend:** connect collections to the backend, embedding-model picker, settings tab first ([9f7b10e](https://github.com/IA-Generative/Muffin/commit/9f7b10e0bd0013c29bc93997e39288685d6aab31))
* **frontend:** require a name and confirmed settings before using a collection ([f4d8e39](https://github.com/IA-Generative/Muffin/commit/f4d8e390c42342ae5df8813c5d368c3b6a857b00))
* task integration ([e3249b7](https://github.com/IA-Generative/Muffin/commit/e3249b7066409cb9d975986c8768d9349f7f215a))
* **worker:** add document_process Celery worker (liteparse + scrapling + RustFS) ([b5dceb4](https://github.com/IA-Generative/Muffin/commit/b5dceb4dbe83f2101f1426846154bce9392399c1))


### Bug Fixes

* **ci:** specify pnpm version via frontend/package.json for lint-frontend ([49b8dfc](https://github.com/IA-Generative/Muffin/commit/49b8dfcffa973b80fcebf415c6bf0f65aa669aba))
* **docker:** backend had no RUSTFS_* env vars, so uploads failed silently ([195eaa2](https://github.com/IA-Generative/Muffin/commit/195eaa25dd7ba92cebb4fa8cbd0390ffe4765b18))
* **docker:** make backend FRONTEND_URL overridable via .env ([b0d5960](https://github.com/IA-Generative/Muffin/commit/b0d5960f31ec84f7a5de067f80d39f14458d8bdf))
* **frontend:** stop the file picker from reopening after choosing a file ([2b401b7](https://github.com/IA-Generative/Muffin/commit/2b401b76aeb6c7ea14849aa75ff619889c621aa5))
* **release:** bump backend version with the release manifest ([abdf53c](https://github.com/IA-Generative/Muffin/commit/abdf53c12250f4c205165937b8ce03111dd0bd3c))
* **release:** bump frontend version alongside the release manifest ([6353338](https://github.com/IA-Generative/Muffin/commit/63533380989efc836dad8625e4ac4921354c04fd))

## [0.2.0-rc](https://github.com/IA-Generative/Muffin/compare/v0.1.0...v0.2.0-rc) (2026-09-17)


### Features

* add backend service with Redis and Keycloak integration ([2dac2be](https://github.com/IA-Generative/Muffin/commit/2dac2beee78e80e512eca13d9a3bea20226c1cf2))
* add chat functionality with message handling and sources display ([55e772a](https://github.com/IA-Generative/Muffin/commit/55e772a25b1e773263d8c7955413cee531010f5d))
* add qa into front ([792e8e4](https://github.com/IA-Generative/Muffin/commit/792e8e47e6b868a04d8468ef210db2e4329e6a81))
* admini collections ([ad8d9f6](https://github.com/IA-Generative/Muffin/commit/ad8d9f607615231a2b820d75c529b414be1cade6))
* backend connection ([25ad92a](https://github.com/IA-Generative/Muffin/commit/25ad92af0f98f9498d1bde52b7589e7dd711ad0c))
* **backend:** add collections CRUD, repository/service layers, and generic pagination ([fb38db2](https://github.com/IA-Generative/Muffin/commit/fb38db2611aebe8ce7c35ded693bb003de90f7a2))
* **backend:** add kecloak integration ([e2ae294](https://github.com/IA-Generative/Muffin/commit/e2ae294893bc1c173e536175b127911bd0af3c60))
* **backend:** add worker-facing internal API (API key auth) for document ingestion ([7354c91](https://github.com/IA-Generative/Muffin/commit/7354c91371d417a2933f7d5c190ee8652df811ee))
* **bakend:** add models choice ([87c0129](https://github.com/IA-Generative/Muffin/commit/87c01294768b4b013b5d23b5d58364541bc3a064))
* **ci:** add initial configuration files for release management and CI/CD ([f577e10](https://github.com/IA-Generative/Muffin/commit/f577e1015f5c11ce9c338ab1b39e65cb6b352c7a))
* **collections:** persist chunking/embedding/instructions settings, add per-step model pickers ([6844705](https://github.com/IA-Generative/Muffin/commit/684470527226b5d933ee8c3c60874bda4e8496f4))
* **collections:** sliding-window params per pipeline step, new Résumé section, modern card layout ([f75c904](https://github.com/IA-Generative/Muffin/commit/f75c904c8a8c43cbfcd9bba1a9d1851b8647b70b))
* **documents:** real upload/delete/reindex wired end-to-end, plus type-to-confirm delete ([f247892](https://github.com/IA-Generative/Muffin/commit/f2478927b7434a6679dd666ee4836682bf898e87))
* enhance collections management with detailed views, pagination, and search functionality ([342cddd](https://github.com/IA-Generative/Muffin/commit/342cdddcca872c582da3a81595836437e34d5019))
* **frontend:** add vue-router for conversation and collection URLs ([3f0daeb](https://github.com/IA-Generative/Muffin/commit/3f0daeb62929ee26f6fbac1e474605d354cd0f2c))
* **frontend:** connect collections to the backend, embedding-model picker, settings tab first ([de82dff](https://github.com/IA-Generative/Muffin/commit/de82dfff300fdae79f17887bf498992395525bb5))
* **frontend:** require a name and confirmed settings before using a collection ([a9c2776](https://github.com/IA-Generative/Muffin/commit/a9c2776723a4a2df47a3b6f41369f388529a1b3b))
* task integration ([5209fc7](https://github.com/IA-Generative/Muffin/commit/5209fc7d65e50c530109b96f4dfcda6ef806b6b9))
* **worker:** add document_process Celery worker (liteparse + scrapling + RustFS) ([84ee957](https://github.com/IA-Generative/Muffin/commit/84ee957947d439ba7161246f99ea899427ba2d78))


### Bug Fixes

* **ci:** specify pnpm version via frontend/package.json for lint-frontend ([aa3a2e4](https://github.com/IA-Generative/Muffin/commit/aa3a2e47b26ecdd28879a9d838e1072a7dcfc0ee))
* **docker:** backend had no RUSTFS_* env vars, so uploads failed silently ([78fe758](https://github.com/IA-Generative/Muffin/commit/78fe7586c94d5241d199be85610e95b403d8d958))
* **docker:** make backend FRONTEND_URL overridable via .env ([a851e86](https://github.com/IA-Generative/Muffin/commit/a851e86215821e6dcd990a9dacac8306a9b8ea6d))
* **frontend:** stop the file picker from reopening after choosing a file ([5e83852](https://github.com/IA-Generative/Muffin/commit/5e838522cccda086f066cbfca5bf041a0b2692d7))
* **release:** bump backend version with the release manifest ([6c1f537](https://github.com/IA-Generative/Muffin/commit/6c1f537ad677f66e10959dc559a92665de5dc3d1))
* **release:** bump frontend version alongside the release manifest ([ac809c7](https://github.com/IA-Generative/Muffin/commit/ac809c7ff87c76fcce2ffddfad455841a65dd45b))
