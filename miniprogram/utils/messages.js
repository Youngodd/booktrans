// The server answers in English; show known messages in Chinese, anything else as it is.
const RULES = [
  [/^Unknown job/, '找不到该任务（可能已被删除）。'],
  [/^Upload a \.pdf/, '请上传 .pdf、.epub 或 .txt 文件。'],
  [/^The file is larger than (\d+) MB/, '文件超过 $1 MB 上限。'],
  [/could not be read as a book/, '无法把该文件识别为图书。'],
  [/already running/, '该任务正在运行。'],
  [/^Unknown provider/, '未知的模型供应商。'],
  [/^Enter your API key/, '请填写所选供应商的 API 密钥。'],
  [/email address does not look right/, '邮箱地址格式不正确。'],
  [/outside the book/, '页码范围超出了这本书。'],
  [/^At most (\d+) pages/, '每个任务最多 $1 页，请缩小页码范围。'],
  [/not finished/, '翻译还没有完成。'],
  [/^Wait for the job/, '请等任务结束后再删除。'],
  [/^Invalid page range/, '页码范围格式不正确（例如 5 或 1-20）。'],
  [/API key was rejected/, 'API 密钥被拒绝。请检查密钥是否正确、是否有余额、是否可使用该模型。'],
  [/returned no answer/, '模型没有返回结果，请重试。'],
  [/^WeChat login is not configured/, '服务器尚未配置微信登录。'],
  [/Could not reach WeChat/, '无法连接微信验证登录。'],
  [/WeChat rejected/, '微信拒绝了本次登录。'],
  [/Too many glossary entries/, '术语太多了（最多 500 条）。'],
  [/glossary entry is empty or too long/, '术语不能为空，且不能超过 80 个字。'],
  [/Wait for the job to finish first/, '请等任务结束后再修改术语表。'],
  [/Something went wrong/, '翻译过程中出现错误，请稍后重试。'],
]

function zh(msg) {
  for (const [re, out] of RULES) {
    if (re.test(msg)) return msg.replace(re, out)
  }
  return msg
}

module.exports = { zh }
