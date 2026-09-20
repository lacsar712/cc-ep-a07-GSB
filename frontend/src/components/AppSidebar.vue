<template>
  <aside class="sidebar">
    <div class="brand">科学实验溯源工作台</div>

    <nav class="side-nav">
      <router-link to="/runs" class="side-link">Run 列表</router-link>
      <router-link v-if="auth.role === 'researcher'" to="/runs/new" class="side-link">
        新建 Run
      </router-link>
    </nav>

    <div class="export-box">
      <div class="export-title">导出溯源报告</div>
      <p class="muted export-hint">选定一条 Run，由后端生成文件</p>
      <n-select
        v-model:value="selectedRunId"
        :options="runOptions"
        :loading="loadingRuns"
        filterable
        size="small"
        placeholder="选择 Run…"
      />
      <div class="export-buttons">
        <n-button
          size="small"
          type="primary"
          :disabled="!selectedRunId"
          :loading="downloading === 'csv'"
          @click="doDownload('csv')"
        >
          下载 CSV
        </n-button>
        <n-button
          size="small"
          :disabled="!selectedRunId"
          :loading="downloading === 'txt'"
          @click="doDownload('txt')"
        >
          下载 TXT
        </n-button>
      </div>
      <p v-if="auth.role === 'auditor'" class="muted export-hint">
        审计员可下载报告，仅只读。
      </p>
    </div>

    <div class="side-footer">
      <div class="muted" style="margin-bottom: 6px">
        {{ auth.username }}（{{ roleLabel }}）
      </div>
      <n-button size="small" quaternary @click="logout">退出</n-button>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { downloadRunReport, listRuns, saveBlob } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const message = useMessage()

const runs = ref([])
const loadingRuns = ref(false)
const selectedRunId = ref(null)
const downloading = ref(null)

const roleLabel = computed(() => (auth.role === 'researcher' ? '研究员' : '审计员'))

const statusText = { running: '进行中', completed: '已完成', aborted: '已中止' }

const runOptions = computed(() =>
  runs.value.map((r) => ({
    label: `${r.project} / ${r.name}（${statusText[r.status] || r.status}）`,
    value: r.id,
  })),
)

async function refreshRuns() {
  loadingRuns.value = true
  try {
    runs.value = await listRuns()
  } catch (e) {
    message.error(e.message || 'Run 列表加载失败')
  } finally {
    loadingRuns.value = false
  }
}

async function doDownload(format) {
  if (!selectedRunId.value) {
    message.warning('请先选择一条 Run')
    return
  }
  downloading.value = format
  try {
    const { blob, filename } = await downloadRunReport(selectedRunId.value, format)
    saveBlob(blob, filename)
    message.success(`报告已下载：${filename}`)
  } catch (e) {
    message.error(e.message || '报告下载失败')
  } finally {
    downloading.value = null
  }
}

function logout() {
  auth.logout()
  router.push('/login')
}

onMounted(refreshRuns)
// 路由切换（如新建/操作完返回）后刷新选择器，保证可导出最新 Run
watch(() => route.fullPath, refreshRuns)
</script>
