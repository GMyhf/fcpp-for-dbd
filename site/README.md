# site/ — 静态站点构建

把仓库根目录的 LaTeX 书稿转换成 [mdBook](https://rust-lang.github.io/mdBook/)
静态站点，并顺带产出可下载的 PDF。

**这个目录不修改任何书稿文件。** `chapters/`、`images/`、`main.tex`、
`preamble.tex` 全部只读，转换所需的改写都在内存里完成（见 `tools/preprocess.py`），
因此 `git pull` 同步上游时不会产生冲突。

## 本地构建

```bash
site/build.sh            # 图 + PDF + Markdown + mdBook，产物在 site/book/
site/build.sh --no-pdf   # 跳过 LaTeX 编译，改站点样式时用这个（约 5 秒）
mdbook serve site        # 本地预览，改 src/ 自动刷新
```

需要的工具：`pandoc`（≥ 3.0）、`mdbook`、`xelatex` + `latexmk`、`pdftocairo`
（poppler-utils）、`pygmentize`（minted 代码高亮）。

## 流水线

| 步骤 | 脚本 | 说明 |
| --- | --- | --- |
| 1 | `tools/figures.sh` | `images/*.tex`（standalone TikZ）→ `build/figures/*.svg` |
| 2 | `tools/build_pdf.sh` | `latexmk -xelatex -shell-escape` → `build/pdf/main.pdf` |
| 3 | `tools/build_md.py` | 每章 pandoc 转换、按 `\section` 切页、生成 `SUMMARY.md` → `src/` |
| 4 | `mdbook build` | `src/` → `book/` |

`src/`、`book/`、`build/` 都是生成物，已在 `.gitignore` 中。

## 转换是怎么做的

`tools/preprocess.py` 先把书稿改写成 pandoc 能忠实读懂的形式：

- 展开 `\input`，让一章作为一个整体转换（`cppguide3` 由三个文件拼成）；
- `\begin{example}{标题}{标签}` 等 tcolorbox 定理环境 → `\begin{fcppexample}` +
  `\fcppboxhead{}`，标签补上 `ex:`／`thm:` 等 cleveref 前缀；
- `\includestandalone{images/x}` → `\includegraphics{figures/x.svg}`；
- `\begin{subtable}` 提升为独立 `table`（否则 pandoc 会把外层 float 的标签盖到
  每一张子表上，三张表拿到同一个 id）；
- `\cref`／`\nameref`／`\ref` 统一改写成 `\ref{<种类>--<标签>}`，把引用方式带给过滤器。

`tools/filters/fcpp.lua` 在 AST 上完成其余工作：编号图、表和定理框（章内连续编号）、
把定理框输出成带样式的 `<div>`、为每个 LaTeX 标签补一个显式 HTML 锚点（gfm 会丢掉
标题 id）、把行内公式换成 MathJax 认的 `\(…\)`，并把所有交叉引用留成占位符。
占位符要等切页之后才知道目标在哪一页，所以由 `build_md.py` 最后统一解析——
解析不了会在构建日志里报 `! unresolved`。

样式在 `theme/custom.css`（定理框配色沿用 `preamble.tex` 里的设定，并有深色主题变体）。

## 中文搜索

mdBook 自带的 elasticlunr 索引按空格分词，中文整句会变成一个 token，搜「智能指针」
搜不到东西。`theme/zh-search.js` 只在查询包含中日韩字符时接管
`elasticlunr.Index.prototype.search`，改为在正文里做子串匹配；纯英文查询仍走原逻辑，
出错会自动回退。结果列表、摘要、点击后的高亮都还是 mdBook 自己的。

## 发布

`.github/workflows/deploy.yml` 在推送到 `main` 时构建并发布到 GitHub Pages。
首次使用需要在仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
