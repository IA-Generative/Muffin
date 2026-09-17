# Changelog

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
