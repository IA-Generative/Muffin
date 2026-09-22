import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat-index', component: () => import('../components/ChatView.vue') },
    { path: '/c/:id', name: 'chat-conversation', component: () => import('../components/ChatView.vue') },
    { path: '/collections', name: 'collections', component: () => import('../components/CollectionsView.vue') },
    {
      path: '/collections/:id/documents/:documentId',
      name: 'collection-document',
      component: () => import('../components/CollectionsView.vue'),
    },
    {
      path: '/collections/:id/:tab?',
      name: 'collection-detail',
      component: () => import('../components/CollectionsView.vue'),
    },
    { path: '/tasks', name: 'tasks', component: () => import('../components/TasksView.vue') },
    { path: '/filing', name: 'filing', component: () => import('../components/FilingReviewView.vue') },
    { path: '/quality', name: 'quality', component: () => import('../components/QualityDashboardView.vue') },
    { path: '/admin', name: 'admin', component: () => import('../components/AdminIndexView.vue') },
    { path: '/admin/settings', name: 'admin-settings', component: () => import('../components/AdminSettingsView.vue') },
    { path: '/admin/prompts', name: 'admin-prompts', component: () => import('../components/AdminPromptsView.vue') },
    { path: '/admin/cgu', name: 'admin-cgu', component: () => import('../components/AdminCguView.vue') },
    { path: '/admin/reports', name: 'admin-reports', component: () => import('../components/AdminReportsView.vue') },
  ],
})
