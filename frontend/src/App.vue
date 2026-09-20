<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <div v-if="auth.token" class="app-shell">
          <AppSidebar />
          <main class="app-main">
            <router-view />
          </main>
        </div>
        <router-view v-else />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { zhCN, dateZhCN } from 'naive-ui'
import { useAuthStore } from './stores/auth'
import AppSidebar from './components/AppSidebar.vue'

const auth = useAuthStore()
</script>
