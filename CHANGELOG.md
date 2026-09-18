# Changelog

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
