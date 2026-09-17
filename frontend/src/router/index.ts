import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'chat-index', component: () => import('../components/ChatView.vue') },
    { path: '/c/:id', name: 'chat-conversation', component: () => import('../components/ChatView.vue') },
    { path: '/collections', name: 'collections', component: () => import('../components/CollectionsView.vue') },
    {
      path: '/collections/:id',
      name: 'collection-detail',
      component: () => import('../components/CollectionsView.vue'),
    },
    { path: '/tasks', name: 'tasks', component: () => import('../components/TasksView.vue') },
  ],
})
