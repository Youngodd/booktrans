// Talks to the book-translator server. For local testing run `python -m booktrans.web`
// with BOOKTRANS_DEV_LOGIN=1 and turn off "verify legal domain" in WeChat DevTools.
// For real devices use your HTTPS domain, and add it under
// MP console -> Development settings -> Server domain (request, uploadFile, downloadFile).
const BASE_URL = 'http://127.0.0.1:8000'

let token = ''

function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: ({ code }) => wx.request({
        url: BASE_URL + '/api/login', method: 'POST', data: { code },
        success: (r) => {
          if (r.statusCode !== 200) return reject(new Error(r.data.detail || 'Login failed'))
          token = r.data.token
          resolve(r.data)
        },
        fail: () => reject(new Error('Cannot reach the server')),
      }),
      fail: () => reject(new Error('WeChat login failed')),
    })
  })
}

// Runs fn with the token; if the server says the token is no longer valid, log in again once.
async function authed(fn) {
  if (!token) await login()
  let r = await fn()
  if (r.statusCode === 404 || r.statusCode === 401) {
    // 404 can also mean a deleted job; a fresh login is harmless in that case
    await login()
    r = await fn()
  }
  if (r.statusCode >= 400) {
    let detail = ''
    try { detail = (typeof r.data === 'string' ? JSON.parse(r.data) : r.data).detail } catch (e) {}
    throw new Error(detail || 'Request failed (' + r.statusCode + ')')
  }
  return typeof r.data === 'string' ? JSON.parse(r.data) : r.data
}

const header = () => ({ Authorization: 'Bearer ' + token })

function request(method, path, data) {
  return authed(() => new Promise((resolve, reject) => wx.request({
    url: BASE_URL + path, method, data, header: header(),
    success: resolve, fail: () => reject(new Error('Cannot reach the server')),
  })))
}

function upload(filePath, name) {
  return authed(() => new Promise((resolve, reject) => wx.uploadFile({
    url: BASE_URL + '/api/jobs', filePath, name: 'file', header: header(),
    success: resolve, fail: () => reject(new Error('Upload failed')),
  })))
}

// Downloads the finished PDF to a temporary file and returns its path.
function download(jobId) {
  return new Promise((resolve, reject) => wx.downloadFile({
    url: BASE_URL + '/api/jobs/' + jobId + '/download', header: header(),
    success: (r) => r.statusCode === 200 ? resolve(r.tempFilePath) : reject(new Error('Download failed')),
    fail: () => reject(new Error('Download failed')),
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
