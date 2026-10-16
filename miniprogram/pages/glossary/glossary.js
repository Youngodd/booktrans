const api = require('../../utils/api')
const { zh } = require('../../utils/messages')

Page({
  data: { state: '', error: '', entries: [], newTerm: '', newZh: '', busy: false },

  onLoad(q) {
    this.id = q.id
    this.edited = {} // term -> new rendering, only what the user changed or added
    this.poll()
  },
  onUnload() { clearTimeout(this.timer); this.gone = true },

  async poll() {
    try {
      const g = await api.getGlossary(this.id)
      if (g.state === 'building' || g.state === '') {
        if (!this.gone) this.timer = setTimeout(() => this.poll(), 2000)
        this.setData({ state: g.state })
      } else {
        this.setData({ state: g.state, error: zh(g.error || ''), entries: g.entries })
      }
    } catch (e) {
      this.setData({ state: 'failed', error: e.message })
    }
  },

  onEdit(e) {
    const { term, index } = e.currentTarget.dataset
    this.edited[term] = e.detail.value
    this.setData({ ['entries[' + index + '].zh']: e.detail.value })
  },
  onNewTerm(e) { this.setData({ newTerm: e.detail.value }) },
  onNewZh(e) { this.setData({ newZh: e.detail.value }) },

  add() {
    const term = this.data.newTerm.trim()
    const value = this.data.newZh.trim()
    if (!term || !value) return this.setData({ error: '请把英文原文和中文译名都填上。' })
    this.edited[term] = value
    const entries = this.data.entries.filter((x) => x.term !== term)
    entries.push({ term, zh: value })
    this.setData({ entries, newTerm: '', newZh: '', error: '' })
  },

  async save() {
    this.setData({ busy: true, error: '' })
    try {
      if (Object.keys(this.edited).length) await api.saveGlossary(this.id, this.edited)
      wx.navigateBack()
    } catch (e) {
      this.setData({ error: e.message })
    } finally {
      this.setData({ busy: false })
    }
  },

  back() { wx.navigateBack() },
})
