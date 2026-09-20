import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    let detail = err.response?.data?.detail
    // blob 请求（如报告下载）的错误体也是 Blob，需要读出 JSON
    if (detail && typeof detail.text === 'function') {
      try {
        detail = JSON.parse(await detail.text()).detail
      } catch {
        detail = undefined
      }
    }
    if (typeof detail === 'string') {
      err.message = detail
    } else if (Array.isArray(detail)) {
      err.message = detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    }
    return Promise.reject(err)
  },
)

export async function login(username, password) {
  const { data } = await api.post('/auth/login', { username, password })
  return data
}

export async function listRuns(params = {}) {
  const { data } = await api.get('/runs', { params })
  return data
}

export async function getRun(id) {
  const { data } = await api.get(`/runs/${id}`)
  return data
}

export async function createRun(body) {
  const { data } = await api.post('/runs', body)
  return data
}

export async function recordMetric(id, body) {
  const { data } = await api.post(`/runs/${id}/metrics`, body)
  return data
}

export async function attachArtifact(id, body) {
  const { data } = await api.post(`/runs/${id}/artifacts`, body)
  return data
}

export async function completeRun(id, body) {
  const { data } = await api.post(`/runs/${id}/complete`, body)
  return data
}

export async function abortRun(id, body) {
  const { data } = await api.post(`/runs/${id}/abort`, body)
  return data
}

export async function getEvents(id) {
  const { data } = await api.get(`/runs/${id}/events`)
  return data
}

export async function getLineage(id) {
  const { data } = await api.get(`/runs/${id}/lineage`)
  return data
}

/**
 * 下载后端生成的单 Run 溯源报告（CSV / TXT）。
 * 文件内容完全由后端产出，前端只负责请求与保存，不拼接任何字段。
 * 返回 { blob, filename }。
 */
export async function downloadRunReport(id, format = 'txt') {
  const res = await api.get(`/runs/${id}/report`, {
    params: { format },
    responseType: 'blob',
  })
  const disposition = res.headers['content-disposition'] || ''
  const match = disposition.match(/filename="?([^"]+)"?/) || disposition.match(/filename\*=UTF-8''([^;]+)/)
  const filename = match ? decodeURIComponent(match[1]) : `run-report-${id}.${format}`
  return { blob: res.data, filename }
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default api
