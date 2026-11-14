# booktrans 模块依赖图

由 `ast` 静态扫描 `booktrans/` 生成（模块级导入，含函数内的延迟导入）。箭头表示"导入"。
`glossary ↔ translate` 是唯一的循环依赖（`glossary.py:164` 的延迟导入），见 [refactoring-plan.md](refactoring-plan.md) 的 R3。
不含 JS 页面和 `miniprogram/`，也不是函数级调用图。

```mermaid
flowchart LR
  booktrans["booktrans"]
  booktrans___main__["__main__"]
  booktrans_backends["backends"]
  booktrans_backends_anthropic_api["backends.anthropic_api"]
  booktrans_backends_base["backends.base"]
  booktrans_backends_claude_cli["backends.claude_cli"]
  booktrans_backends_openai_compat["backends.openai_compat"]
  booktrans_cli["cli"]
  booktrans_desktop["desktop"]
  booktrans_desktop___main__["desktop.__main__"]
  booktrans_desktop_shell["desktop.shell"]
  booktrans_figures["figures"]
  booktrans_fsutil["fsutil"]
  booktrans_glossary["glossary"]
  booktrans_languages["languages"]
  booktrans_layout["layout"]
  booktrans_ocr["ocr"]
  booktrans_pipeline["pipeline"]
  booktrans_prompts["prompts"]
  booktrans_readers["readers"]
  booktrans_spend["spend"]
  booktrans_textclean["textclean"]
  booktrans_translate["translate"]
  booktrans_usage["usage"]
  booktrans_web["web"]
  booktrans_web___main__["web.__main__"]
  booktrans_web_app["web.app"]
  booktrans_web_auth["web.auth"]
  booktrans_web_jobs["web.jobs"]
  booktrans_web_mailer["web.mailer"]
  booktrans_web_wxcloud["web.wxcloud"]
  booktrans_writer["writer"]
  booktrans___main__ --> booktrans_cli
  booktrans_backends --> booktrans_backends_anthropic_api
  booktrans_backends --> booktrans_backends_base
  booktrans_backends --> booktrans_backends_claude_cli
  booktrans_backends --> booktrans_backends_openai_compat
  booktrans_backends_anthropic_api --> booktrans_backends_base
  booktrans_backends_base --> booktrans_usage
  booktrans_backends_claude_cli --> booktrans_backends_base
  booktrans_backends_openai_compat --> booktrans_backends_base
  booktrans_cli --> booktrans_backends
  booktrans_cli --> booktrans_backends_base
  booktrans_cli --> booktrans_glossary
  booktrans_cli --> booktrans_languages
  booktrans_cli --> booktrans_pipeline
  booktrans_cli --> booktrans_readers
  booktrans_cli --> booktrans_spend
  booktrans_cli --> booktrans_usage
  booktrans_desktop___main__ --> booktrans_backends_base
  booktrans_desktop___main__ --> booktrans_spend
  booktrans_desktop___main__ --> booktrans_web_app
  booktrans_desktop_shell --> booktrans_desktop___main__
  booktrans_glossary --> booktrans_backends_base
  booktrans_glossary --> booktrans_fsutil
  booktrans_glossary --> booktrans_prompts
  booktrans_glossary --> booktrans_translate
  booktrans_layout --> booktrans_figures
  booktrans_layout --> booktrans_languages
  booktrans_layout --> booktrans_textclean
  booktrans_ocr --> booktrans_prompts
  booktrans_ocr --> booktrans_translate
  booktrans_pipeline --> booktrans_glossary
  booktrans_pipeline --> booktrans_languages
  booktrans_pipeline --> booktrans_layout
  booktrans_pipeline --> booktrans_ocr
  booktrans_pipeline --> booktrans_readers
  booktrans_pipeline --> booktrans_spend
  booktrans_pipeline --> booktrans_translate
  booktrans_pipeline --> booktrans_writer
  booktrans_prompts --> booktrans_languages
  booktrans_spend --> booktrans_backends
  booktrans_spend --> booktrans_backends_base
  booktrans_spend --> booktrans_fsutil
  booktrans_translate --> booktrans_backends_base
  booktrans_translate --> booktrans_fsutil
  booktrans_translate --> booktrans_glossary
  booktrans_translate --> booktrans_languages
  booktrans_translate --> booktrans_layout
  booktrans_translate --> booktrans_prompts
  booktrans_web___main__ --> booktrans_web_app
  booktrans_web_app --> booktrans_backends
  booktrans_web_app --> booktrans_backends_base
  booktrans_web_app --> booktrans_glossary
  booktrans_web_app --> booktrans_languages
  booktrans_web_app --> booktrans_pipeline
  booktrans_web_app --> booktrans_readers
  booktrans_web_app --> booktrans_spend
  booktrans_web_app --> booktrans_web
  booktrans_web_app --> booktrans_web_auth
  booktrans_web_app --> booktrans_web_jobs
  booktrans_web_app --> booktrans_web_mailer
  booktrans_web_app --> booktrans_web_wxcloud
  booktrans_web_jobs --> booktrans_backends
  booktrans_web_jobs --> booktrans_backends_base
  booktrans_web_jobs --> booktrans_languages
  booktrans_web_jobs --> booktrans_pipeline
  booktrans_web_jobs --> booktrans_readers
  booktrans_web_jobs --> booktrans_spend
  booktrans_writer --> booktrans_languages
  booktrans_writer --> booktrans_textclean
```
