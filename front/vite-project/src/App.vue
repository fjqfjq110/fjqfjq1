<template>
  <div class="lof-app">
    <div class="header">
      <div class="title">
        <h2>LOF 基金实时溢价监控</h2>
        <span class="update-time">数据更新时间：{{ lastUpdateTime }}</span>
      </div>
      <div class="tool-bar">
        <div class="refresh">
          <el-button @click="manualRefresh" :loading="loading" type="primary" :icon="Refresh">
            手动刷新
          </el-button>
        </div>
        <div class="sort">
          <span class="sort-label">排序依据</span>
          <el-button @click="toggleSortField" :disabled="loading" size="small">
            {{ sortField === 'premiumRate' ? '按昨日净值溢价' : '按实时估算溢价' }}
          </el-button>
          <el-button @click="toggleSort" :disabled="loading" size="small">
            {{ sortType === 'desc' ? '▼ 从高到低' : '▲ 从低到高' }}
          </el-button>
        </div>
      </div>
    </div>

    <div class="filter-bar">
      <el-input v-model="searchCode" placeholder="基金代码" clearable style="width: 160px;" />
      <el-input v-model="searchName" placeholder="基金名称" clearable style="width: 200px;" />
      <el-select v-model="filterStatus" placeholder="申购状态" clearable style="width: 140px;">
        <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
      </el-select>
      <el-button @click="resetFilter" :icon="RefreshRight">重置</el-button>
    </div>

    <el-table :data="displayList" v-loading="loading" height="700" border>
      <el-table-column prop="fundCode" label="基金代码" align="center" />
      <el-table-column prop="fundName" label="基金名称" align="center" />
      <el-table-column prop="tradePrice" label="场内价格" align="center" />
      <el-table-column prop="netValue" label="场外净值(昨日)" align="center" />
      <el-table-column prop="estimateValue" label="估算净值(实时)" align="center" />
      <el-table-column label="涨跌幅" align="center">
        <template #default="{ row }">
          <span :class="getRateClass(row.increaseRate)">
            {{ row.increaseRate }}%
          </span>
        </template>
      </el-table-column>
      <el-table-column label="溢价率(昨日)" align="center">
        <template #default="{ row }">
          <span :class="getRateClass(row.premiumRate)">
            {{ row.premiumRate }}%
          </span>
        </template>
      </el-table-column>
      <el-table-column label="溢价率(实时)" align="center">
        <template #default="{ row }">
          <span :class="getRateClass(row.estimatePremiumRate)">
            {{ row.estimatePremiumRate }}%
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="purchaseLimit" label="日限额" align="center" />
      <el-table-column label="申购状态" align="center" width="120">
        <template #default="{ row }">
          <el-tag :type="row.purchaseStatus === '暂停申购' ? 'danger' : row.purchaseStatus === '开放申购' ? 'success' : 'info'" size="small" style="white-space: nowrap;">
            {{ row.purchaseStatus }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="fundSize" label="基金规模" align="center" />
      <el-table-column prop="turnover" label="成交额" align="center" />
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh, RefreshRight } from '@element-plus/icons-vue'

// 后端接口地址
const API_URL = 'http://127.0.0.1:8000/api/lof'

const fundList = ref([])
const loading = ref(false)
const sortType = ref('desc')
const sortField = ref('premiumRate')
const searchCode = ref('')
const searchName = ref('')
const filterStatus = ref('')
const lastUpdateTime = ref('')

function formatTime(date) {
  const pad = n => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

// 申购状态选项
const statusOptions = computed(() => {
  const set = new Set(fundList.value.map(i => i.purchaseStatus).filter(Boolean))
  return Array.from(set).sort()
})

// 筛选 + 排序
const displayList = computed(() => {
  let list = [...fundList.value]
  if (searchCode.value) {
    list = list.filter(i => String(i.fundCode).includes(searchCode.value.trim()))
  }
  if (searchName.value) {
    list = list.filter(i => String(i.fundName).includes(searchName.value.trim()))
  }
  if (filterStatus.value) {
    list = list.filter(i => i.purchaseStatus === filterStatus.value)
  }
  list.sort((a, b) => {
    const field = sortField.value
    const pa = parseFloat(a[field]) || 0
    const pb = parseFloat(b[field]) || 0
    return sortType.value === 'desc' ? pb - pa : pa - pb
  })
  return list
})

function resetFilter() {
  searchCode.value = ''
  searchName.value = ''
  filterStatus.value = ''
}

// 获取数据
async function fetchData() {
  if (loading.value) return
  loading.value = true
  try {
    const res = await axios.get(API_URL)
    if (res.data.code === 200) {
      fundList.value = res.data.data
      lastUpdateTime.value = formatTime(new Date())
    } else {
      ElMessage.error(res.data.msg || '数据获取失败')
    }
  } catch (err) {
    ElMessage.error('请求失败：请确认 Python 后端已启动')
  } finally {
    loading.value = false
  }
}

// 手动刷新
function manualRefresh() {
  fetchData()
}

// 切换排序
function toggleSort() {
  sortType.value = sortType.value === 'desc' ? 'asc' : 'desc'
}

function toggleSortField() {
  sortField.value = sortField.value === 'premiumRate' ? 'estimatePremiumRate' : 'premiumRate'
}

// 颜色样式
function getRateClass(rate) {
  const num = parseFloat(rate) || 0
  if (num > 0) return 'rate-up'
  if (num < 0) return 'rate-down'
  return 'rate-zero'
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.lof-app {
  max-width: 100%;
  /* margin: 20px auto; */
  padding: 24px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.update-time {
  font-size: 13px;
  color: #999;
  text-align: left;
}
.tool-bar {
  display: flex;
  gap: 12px;
}
button {
  padding: 4px 10px;
  cursor: pointer;
  border-radius: 4px;
  border: 1px solid #ccc;
}
.sort {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sort-label {
  font-size: 13px;
  color: #666;
  white-space: nowrap;
}
.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.rate-up {
  color: #f53f3f;
  font-weight: bold;
}
.rate-down {
  color: #009944;
  font-weight: bold;
}
.rate-zero {
  color: #666;
}
</style>