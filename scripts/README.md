# Roadmap Issue Creation Script

`Create-RoadmapIssues.ps1` creates the initial GitHub labels and roadmap issues.

## Requirements

- GitHub CLI (`gh`)
- An authenticated GitHub session with permission to create labels and issues

```powershell
gh auth login
gh auth status
```

## Run

From the repository root:

```powershell
.\scripts\Create-RoadmapIssues.ps1
```

To target another repository:

```powershell
.\scripts\Create-RoadmapIssues.ps1 -Repository "owner/repository"
```

The script skips issues whose exact titles already exist. To intentionally create duplicates:

```powershell
.\scripts\Create-RoadmapIssues.ps1 -Force
```

If PowerShell blocks local scripts for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\Create-RoadmapIssues.ps1
```
