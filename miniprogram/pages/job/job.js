const api = require('../../utils/api')
const { zh } = require('../../utils/messages')

const STAGES = { scan: '正在读取图书', ocr: '正在识别扫描页', glossary: '正在整理人名术语', translate: '正在翻译', render: '正在生成 PDF', done: '已完成' }

Page({
  data: { job: {}, percent: 0, stageText: '', busy: false, error: '', ready: false },

  onLoad(q) {
    this.id = q.id
    this.poll()
  },
  onUnload() { clearTimeout(this.timer); this.gone = true },

  async poll() {
    try {
      const job = await api.getJob(this.id)
      const percent = job.total ? Math.round((100 * job.done) / job.total) : 0
      job.error = zh(job.error || '')
      this.setData({ job, percent, stageText: STAGES[job.stage] || '排队等待中' })
      if (job.state === 'queued' || job.state === 'running') {
        if (!this.gone) this.timer = setTimeout(() => this.poll(), 3000)
      } else if (job.state === 'done' && !this.filePath) {
        this.prefetch()
      }
    } catch (e) {
      this.setData({ error: e.message })
    }
  },

  // Fetch the PDF as soon as it is done: sharing must run directly inside a tap,
  // so the file has to be on the phone before the user presses the button.
  async prefetch() {
    this.setData({ busy: true, error: '' })
    try {
      this.filePath = await api.download(this.id)
      this.setData({ ready: true })
    } catch (e) {
      this.setData({ error: e.message })
    } finally {
      this.setData({ busy: false })
    }
  },

  retry() { this.prefetch() },

  open() {
    wx.openDocument({
      filePath: this.filePath, fileType: 'pdf', showMenu: true,
      fail: () => wx.showToast({ title: '无法打开 PDF', icon: 'none' }),
    })
  },

  share() {
    const stem = (this.data.job.filename || 'book').replace(/\.[^.]+$/, '')
    wx.shareFileMessage({
      filePath: this.filePath, fileName: stem + '_bilingual.pdf',
      fail: (e) => {
        if (!/cancel/.test(e.errMsg || '')) wx.showToast({ title: '发送失败，请改用“打开 PDF”后转发', icon: 'none', duration: 3000 })
      },
    })
  },

  async remove() {
    try {
      await api.deleteJob(this.id)
      wx.navigateBack()
    } catch (e) {
      this.setData({ error: e.message })
    }
  },

  back() { wx.navigateBack() },
})
