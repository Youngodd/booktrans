const api = require('../../utils/api')

// Suppliers the server accepts (bring your own key).
const PROVIDERS = [
  { id: 'qwen', name: '通义千问 Qwen（国内）', hint: 'sk-...' },
  { id: 'deepseek', name: 'DeepSeek', hint: 'sk-...' },
  { id: 'qwen-intl', name: '通义千问 Qwen（国际版）', hint: 'sk-...' },
  { id: 'api', name: 'Claude（Anthropic）', hint: 'sk-ant-...' },
]

Page({
  data: {
    providers: PROVIDERS, providerIndex: 0, apiKey: '', pages: '', email: '',
    preview: false, ocr: false, job: null, busy: false, error: '', emailEnabled: false,
  },

  onProvider(e) { this.setData({ providerIndex: Number(e.detail.value) }) },
  onKey(e) { this.setData({ apiKey: e.detail.value }) },
  onPages(e) { this.setData({ pages: e.detail.value }) },
  onEmail(e) { this.setData({ email: e.detail.value }) },
  onPreview(e) { this.setData({ preview: e.detail.value }) },
  onOcr(e) { this.setData({ ocr: e.detail.value }) },

  async pickFile() {
    try {
      const { tempFiles } = await wx.chooseMessageFile({
        count: 1, type: 'file', extension: ['pdf', 'epub', 'txt'],
      })
      this.setData({ busy: true, error: '' })
      wx.showLoading({ title: '上传中...' })
      const login = await api.login()
      const job = await api.upload(tempFiles[0].path, tempFiles[0].name)
      this.setData({ job, emailEnabled: login.email_enabled })
    } catch (e) {
      if (!/cancel/.test(e.errMsg || '')) this.setData({ error: e.message || '无法添加该文件' })
    } finally {
      wx.hideLoading()
      this.setData({ busy: false })
    }
  },

  async start() {
    const d = this.data
    this.setData({ busy: true, error: '' })
    try {
      await api.startJob(d.job.id, {
        api_key: d.apiKey, provider: PROVIDERS[d.providerIndex].id, pages: d.pages,
        preview: d.preview, ocr: d.ocr, email: d.email,
      })
      wx.navigateTo({ url: '/pages/job/job?id=' + d.job.id })
    } catch (e) {
      this.setData({ error: e.message })
    } finally {
      this.setData({ busy: false })
    }
  },
})
