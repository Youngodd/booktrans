const { ENV } = require('./utils/config')

App({
  onLaunch() {
    if (ENV) wx.cloud.init({ env: ENV })
  },
})
