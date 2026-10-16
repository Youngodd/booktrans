// Talks to the book-translator server.
//  - Cloud Hosting mode (config.ENV set): calls go through wx.cloud.callContainer, books travel
//    through cloud storage, and WeChat tells the server who the user is.
//  - HTTP mode (config.ENV empty): plain requests to BASE_URL with a login token. For local
//    testing run `python -m booktrans.web` with BOOKTRANS_DEV_LOGIN=1 and turn off
//    "verify legal domain" in WeChat DevTools.
const { ENV, SERVICE, BASE_URL } = require('./config')
const { zh } = require('./messages')

const CLOUD = !!ENV
let token = ''

function login() {
  if (CLOUD) return request('GET', '/api/config')
  return new Promise((resolve, reject) => {
    wx.login({
      success: ({ code }) => wx.request({
        url: BASE_URL + '/api/login', method: 'POST', data: { code },
        success: (r) => {
          if (r.statusCode !== 200) return reject(new Error(zh(r.data.detail || '登录失败')))
          token = r.data.token
          resolve(r.data)
        },
        fail: () => reject(new Error('无法连接服务器')),
      }),
      fail: () => reject(new Error('微信登录失败')),
    })
  })
}

// Runs fn with the token; if the server says the token is no longer valid, log in again once.
async function authed(fn) {
  if (!CLOUD && !token) await login()
  let r = await fn()
  if (!CLOUD && (r.statusCode === 404 || r.statusCode === 401)) {
    // 404 can also mean a deleted job; a fresh login is harmless in that case
    await login()
    r = await fn()
  }
  if (r.statusCode >= 400) {
    let detail = ''
    try { detail = (typeof r.data === 'string' ? JSON.parse(r.data) : r.data).detail } catch (e) {}
    throw new Error(zh(detail || '请求失败（' + r.statusCode + '）'))
  }
  return typeof r.data === 'string' ? JSON.parse(r.data) : r.data
}

const header = () => ({ Authorization: 'Bearer ' + token })

function send(method, path, data) {
  if (CLOUD) {
    return wx.cloud.callContainer({
      config: { env: ENV }, path, method, data, header: { 'X-WX-SERVICE': SERVICE },
    }).catch(() => { throw new Error('无法连接服务器') })
  }
  return new Promise((resolve, reject) => wx.request({
    url: BASE_URL + path, method, data, header: header(),
    success: resolve, fail: () => reject(new Error('无法连接服务器')),
  }))
}

function request(method, path, data) {
  return authed(() => send(method, path, data))
}

function upload(filePath, name) {
  if (CLOUD) {
    const ext = (name.match(/\.[A-Za-z0-9]+$/) || [''])[0].toLowerCase()
    const cloudPath = 'books/' + Date.now() + '-' + Math.random().toString(36).slice(2) + ext
    return wx.cloud.uploadFile({ cloudPath, filePath })
      .catch(() => { throw new Error('上传失败') })
      .then((res) => request('POST', '/api/jobs/from-storage', { file_id: res.fileID, filename: name }))
  }
  return authed(() => new Promise((resolve, reject) => wx.uploadFile({
    url: BASE_URL + '/api/jobs', filePath, name: 'file', header: header(),
    success: resolve, fail: () => reject(new Error('上传失败')),
  })))
}

// Downloads the finished PDF to a temporary file and returns its path.
async function download(jobId) {
  if (CLOUD) {
    const { file_id } = await request('GET', '/api/jobs/' + jobId + '/result')
    try {
      return (await wx.cloud.downloadFile({ fileID: file_id })).tempFilePath
    } catch (e) {
      throw new Error('下载失败')
    }
  }
  return new Promise((resolve, reject) => wx.downloadFile({
    url: BASE_URL + '/api/jobs/' + jobId + '/download', header: header(),
    success: (r) => r.statusCode === 200 ? resolve(r.tempFilePath) : reject(new Error('下载失败')),
    fail: () => reject(new Error('下载失败')),
  }))
}

module.exports = {
  login,
  upload,
  download,
  getJob: (id) => request('GET', '/api/jobs/' + id),
  startJob: (id, body) => request('POST', '/api/jobs/' + id + '/start', body),
  deleteJob: (id) => request('DELETE', '/api/jobs/' + id),
}
