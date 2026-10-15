const api = require('../../utils/api')

const STAGES = { scan: 'Reading the book', ocr: 'Recognising scanned pages', translate: 'Translating', render: 'Building the PDF', done: 'Done' }

Page({
  data: { job: {}, percent: 0, stageText: '', busy: false, error: '' },

  onLoad(q) {
    this.id = q.id
    this.poll()
  },
  onUnload() { clearTimeout(this.timer); this.gone = true },

  async poll() {
    try {
      const job = await api.getJob(this.id)
      const percent = job.total ? Math.round((100 * job.done) / job.total) : 0
      this.setData({ job, percent, stageText: STAGES[job.stage] || 'Waiting in the queue' })
      if (job.state === 'queued' || job.state === 'running') {
        if (!this.gone) this.timer = setTimeout(() => this.poll(), 3000)
      }
    } catch (e) {
      this.setData({ error: e.message })
    }
  },

  async fetchPdf() {
    this.setData({ busy: true, error: '' })
    try {
      return await api.download(this.id)
    } catch (e) {
      this.setData({ error: e.message })
    } finally {
      this.setData({ busy: false })
    }
  },

  async open() {
    const filePath = await this.fetchPdf()
    if (filePath) wx.openDocument({ filePath, fileType: 'pdf', showMenu: true })
  },

  async share() {
    const filePath = await this.fetchPdf()
    if (!filePath) return
    const stem = (this.data.job.filename || 'book').replace(/\.[^.]+$/, '')
    wx.shareFileMessage({ filePath, fileName: stem + '_bilingual.pdf' })
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
