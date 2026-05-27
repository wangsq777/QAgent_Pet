---
name: markitdown
description: Convert files (PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON, XML, images, audio, etc.) to Markdown using Microsoft's markitdown. Use when user says "convert to markdown", "markitdown", "read this pdf", "extract text", "转markdown", "转换文件", or wants to convert any document to readable Markdown text.
argument-hint: <file-path-or-url> [options]
allowed-tools: Bash(*), Read, Write, Glob
---

# MarkItDown - File to Markdown Converter

Convert file to Markdown: $ARGUMENTS

## Prerequisites

`markitdown` CLI must be installed. If not found, install it:

```bash
# Preferred (fastest, no conflicts)
uv tool install 'markitdown[all]'

# Alternatives
pipx install 'markitdown[all]'
pip install --user 'markitdown[all]'
```

## Supported Formats

| Format | Extensions | Notes |
|--------|-----------|-------|
| PDF | `.pdf` | Text extraction with layout preservation |
| Word | `.docx` | Headings, tables, lists preserved |
| PowerPoint | `.pptx` | Slide-by-slide with headers |
| Excel | `.xlsx`, `.xls` | Sheet-by-sheet tables |
| HTML | `.html`, `.htm` | Full structure conversion |
| CSV | `.csv` | Converted to Markdown tables |
| JSON | `.json` | Formatted output |
| XML | `.xml` | Formatted output |
| Images | `.jpg`, `.png`, `.gif`, `.webp` | EXIF metadata extraction |
| Audio | `.mp3`, `.wav` | Transcription (requires ffmpeg) |
| Email | `.msg` | Outlook message extraction |
| eBook | `.epub` | Full text extraction |
| Archives | `.zip` | Lists contents, converts supported files inside |
| URLs | `http://...` | Fetches and converts web pages |

## Workflow

### Step 1: Parse Arguments

Parse `$ARGUMENTS` to identify:

- **Target**: file path, glob pattern, directory, or URL
- **Output option**: `-o output.md` to save, or print to stdout
- **Batch mode**: if target is a directory or glob pattern

If no arguments given, ask the user what file they want to convert.

### Step 2: Validate Target

```bash
# Check if file exists
ls -la "$TARGET"

# Check markitdown is available
markitdown --version
```

If markitdown is not installed, install it with:
```bash
uv tool install 'markitdown[all]'
```

### Step 3: Convert

**Single file:**
```bash
markitdown "$FILE_PATH"
```

**Save to file:**
```bash
markitdown "$FILE_PATH" -o "$OUTPUT_PATH"
```

**From URL:**
```bash
markitdown "$URL"
```

**Batch convert (directory):**
```bash
for f in "$DIR"/*.{pdf,docx,pptx,xlsx,html,csv}; do
    [ -f "$f" ] && markitdown "$f" -o "${f%.*}.md"
done
```

**From stdin with extension hint:**
```bash
cat "$FILE" | markitdown -x .html
```

### Step 4: Present Results

- For short output (< 200 lines): display directly in the conversation
- For long output: save to a `.md` file and report the path
- For batch conversions: report summary of converted files

### Step 5: Post-Processing (Optional)

If the user asks, you can:

1. **Summarize**: Read the converted markdown and provide a summary
2. **Extract specific info**: Parse the markdown for tables, headings, key data
3. **Clean up**: Remove artifacts, fix formatting issues
4. **Translate**: The markdown is now clean text that can be translated
5. **Split**: Break large documents into sections

## Examples

```
/markitdown report.pdf
/markitdown slides.pptx -o slides.md
/markitdown data.xlsx
/markitdown https://example.com/page.html
/markitdown ./documents/              # batch convert all supported files
/markitdown *.pdf                     # convert all PDFs in current directory
```

## Error Handling

| Error | Fix |
|-------|-----|
| `markitdown: command not found` | Run: `uv tool install 'markitdown[all]'` |
| `No such file or directory` | Check the file path with `ls` |
| Audio transcription fails | Install ffmpeg: `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux) |
| PDF extraction is empty | The PDF may be image-only; suggest using OCR tools |
| Encoding issues | Try: `markitdown -c UTF-8 "$FILE"` |
