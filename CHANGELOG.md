# Changelog

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
