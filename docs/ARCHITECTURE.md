# Architecture

The system is divided into four layers.

```
Portfolio Source
        │
        ▼
    Ingestion
        │
        ▼
 Normalized Dataset
        │
        ▼
     Analysis
        │
        ▼
      Reports
```

## Portfolio Sources

Sources provide access to a photographer's portfolio.

Examples:

- SmugMug
- Lightroom
- Flickr
- Local Folder

Sources should expose a common interface and should never contain analysis logic.

## Ingestion

Responsible for:

- discovering galleries
- indexing assets
- extracting metadata
- preparing images for analysis

Ingestion should never perform analysis.

## Normalized Dataset

All analysis operates on a common representation regardless of the original source.

The normalized dataset is the contract between ingestion and analysis.

## Analysis

Analyzers are independent modules.

Each analyzer answers one question.

Examples:

- Equipment Habits
- Color Signature
- Subject Placement
- Time of Day
- Visual Complexity

Analyzers should not depend on the original portfolio source.

## Reports

Reports transform findings into something meaningful for photographers.

The goal is insight, not statistics for their own sake.