const T = {
  stages: { scan: "Analysing layout", ocr: "Reading scanned pages", translate: "Translating",
            render: "Building pages", "": "Waiting for a free worker" },
  bookInfo: (name, n) => name + " — " + n + " pages",
  estimateOther: "Billed by the provider to your key; see their pricing.",
  estimate: (n, usd) => n + " pages ≈ US$" + usd + " (billed to your key; estimate)",
  uploadFailed: "Upload failed", networkError: "Network error",
  tickBox: "Please tick the confirmation box.",
  done: "Done", donePreview: "Preview ready",
  failed: "Failed. Progress is saved, you can run again.",
};
