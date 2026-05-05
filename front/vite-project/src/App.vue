<template>
  <div class="lof-app">
    <div class="header">
      <h2>LOF 基金实时溢价监控</h2>
      <div class="tool-bar">
        <div class="refresh">
          <button @click="manualRefresh" :disabled="loading">
            手动刷新
          </button>
        </div>
        <div class="sort">
          <button @click="toggleSort" :disabled="loading">
            溢价率 {{ sortType === 'desc' ? '从高到低' : '从低到高' }}
          </button>
        </div>
      </div>
    </div>

    <div class="filter-bar">
      <el-input v-model="searchCode" placeholder="基金代码" clearable style="width: 160px;" />
      <el-input v-model="searchName" placeholder="基金名称" clearable style="width: 200px;" />
      <el-select v-model="filterStatus" placeholder="申购状态" clearable style="width: 140px;">
        <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
      </el-select>
      <el-button @click="resetFilter">重置</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon style="margin-bottom: 12px;" />
    <el-table :data="displayList" v-loading="loading" height="700" border>
      <el-table-column prop="fundCode" label="基金代码" align="center" />
      <el-table-column prop="fundName" label="基金名称" align="center" />
      <el-table-column prop="tradePrice" label="场内价格" align="center" />
      <el-table-column prop="netValue" label="场外净值" align="center" />
      <el-table-column label="涨跌幅" align="center">
        <template #default="{ row }">
          <span :class="getRateClass(row.increaseRate)">
            {{ row.increaseRate }}%
          </span>
        </template>
      </el-table-column>
      <el-table-column label="溢价率" align="center">
        <template #default="{ row }">
          <span :class="getRateClass(row.premiumRate)">
            {{ row.premiumRate }}%
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="purchaseLimit" label="日限额" align="center" />
      <el-table-column label="申购状态" align="center">
        <template #default="{ row }">
          <el-tag :type="row.purchaseStatus === '暂停申购' ? 'danger' : row.purchaseStatus === '开放申购' ? 'success' : 'info'" size="small">
            {{ row.purchaseStatus }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import axios from 'axios'

// 后端接口地址
const API_URL = 'http://127.0.0.1:8000/api/lof'

const fundList = ref([])
const loading = ref(false)
const error = ref('')
const sortType = ref('desc')
const searchCode = ref('')
const searchName = ref('')
const filterStatus = ref('')

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
    const pa = parseFloat(a.premiumRate) || 0
    const pb = parseFloat(b.premiumRate) || 0
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
  error.value = ''
  try {
    const res = await axios.get(API_URL)
    if (res.data.code === 200) {
      fundList.value = res.data.data
    } else {
      error.value = res.data.msg
    }
  } catch (err) {
    error.value = '请求失败：请确认 Python 后端已启动'
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
  padding: 0 24px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
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
.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.loading, .error {
  padding: 20px;
  text-align: center;
}
.error {
  color: #f53f3f;
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