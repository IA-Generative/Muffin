import { createApp } from 'vue'
import '@gouvfr/dsfr/dist/dsfr.min.css'
import '@gouvminint/vue-dsfr/dist/vue-dsfr.css'
import VueDsfr from '@gouvminint/vue-dsfr'
import App from './App.vue'
import { router } from './router'

createApp(App).use(VueDsfr).use(router).mount('#app')
