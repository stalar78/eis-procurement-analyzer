# Pre-Push Checklist

Run these commands before publishing or pushing this repository. They are safe PowerShell checks and do not create a remote repository.

## Verify Ignore Rules

```powershell
git check-ignore -v .venv candidate_details candidate_analysis_v22 candidate_details.zip all_web_tenders_classified.xlsx PUBLICATION_AUDIT.md
```

## Preview Repository Contents

If the repository has already been initialized locally:

```powershell
git status --short --untracked-files=all
git ls-files --others --exclude-standard
```

If `.git` does not exist yet, use a manual preview of public candidates:

```powershell
Get-ChildItem -Force | Where-Object {
  $_.Name -notmatch '^(\.venv|\.pytest_cache|__pycache__|candidate_details.*|candidate_analysis.*|data|debug|logs)$' -and
  $_.Name -notmatch '\.(zip|rar|7z|xlsx|xls|docx|doc|pdf|html|htm|log|tmp|bak)$' -and
  $_.Name -ne 'PUBLICATION_AUDIT.md'
}
```

## Find Large Files

```powershell
Get-ChildItem -File -Recurse | Where-Object {
  $_.FullName -notlike '*\.venv\*' -and $_.Length -gt 1MB
} | Sort-Object Length -Descending | Select-Object FullName,Length
```

## Search For Secrets And Local Paths

```powershell
rg -n -i "token|api_key|api-key|secret|password|passwd|authorization|bearer|cookie|session|private key|BEGIN RSA|BEGIN OPENSSH|VK_TOKEN|GITHUB_TOKEN|NODE_OPTIONS|localhost|C:\\Users\\|stala|OneDrive" -g "!.venv/**" -g "!candidate_details/**" -g "!candidate_details*/**" -g "!candidate_analysis/**" -g "!candidate_analysis*/**" -g "!data/**" -g "!logs/**" -g "!debug/**"
```

## Compile And Test

```powershell
.\.venv\Scripts\python.exe -m py_compile .\collect_results.py .\collect_candidate_details.py .\analyze_candidate_documents.py .\score_results.py
.\.venv\Scripts\python.exe -m pytest -q
```

## Review Changes

```powershell
git diff -- . ':!PUBLICATION_AUDIT.md'
git status --short --untracked-files=all
```

Do not push generated procurement data, downloaded documents, archives, logs, browser state, cookies, tokens, or private local paths.
