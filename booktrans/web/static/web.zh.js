const T = {
  stages: { scan: "分析版面", ocr: "识别扫描页", translate: "翻译中",
            render: "生成页面", "": "排队等待空闲处理器" },
  bookInfo: (name, n) => name + " — 共 " + n + " 页",
  estimateOther: "费用按你的 API key 在该供应商处计费，请查看其价格。",
  estimate: (n, usd) => n + " 页 ≈ US$" + usd + "（按你的 API key 计费；估计值）",
  uploadFailed: "上传失败", networkError: "网络错误",
  tickBox: "请先勾选确认框。",
  done: "完成", donePreview: "试译完成",
  failed: "失败。进度已保存，可再试一次。",
};
