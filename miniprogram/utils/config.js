// Cloud Hosting (WeChat cloud run): fill in the environment ID and service name and the app
// talks to your container through wx.cloud, with no domain or login code needed.
// Leave ENV empty to use the plain HTTP server at BASE_URL instead (local testing).
module.exports = {
  ENV: 'book-translator-d8fiwkctd17eb186',
  SERVICE: 'book-translator',
  BASE_URL: 'http://127.0.0.1:8000',
}
