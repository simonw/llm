# Cleanup

Consolidates the archive — moves loose files into the right places, closes completed URs, organizes legacy items. Runs automatically at the end of every work loop, or manually on demand.

## What it does

Four passes, in order:

### Pass 1: Sweep finished queue items
Moves terminal-status REQs (`completed`, `failed`, `done`) from the queue root and `working/` into `archive/`.

### Pass 2: Close completed User Requests
When all REQs for a UR are archived, moves the entire UR folder from `user-requests/` into `archive/UR-NNN/`.

### Pass 3: Consolidate loose REQ files
Moves REQ files sitting in `archive/` root into their UR folders (`archive/UR-NNN/`). REQs without a UR reference go to `archive/legacy/`.

### Pass 4: Fix misplaced directories
Detects `do-work/` directories accidentally created in subdirectories and relocates them. Catches UR folders nested under `archive/user-requests/` and moves them up.

## Result

```
do-work/
├── archive/
│   ├── UR-001/              # Self-contained: input.md + completed REQs
│   │   ├── input.md
│   │   ├── REQ-001-done.md
│   │   └── REQ-002-done.md
│   ├── UR-002/
│   └── legacy/              # Standalone REQs without UR references
│       └── REQ-010-done.md
├── user-requests/            # Only open URs remain here
└── (pending REQs)            # Only active queue items remain here
```

## Key rules

- Deletes nothing — only moves files
- No content modification except normalizing non-standard statuses (`done` → `completed`)
- Skips active queue items (`pending`, `claimed`)

## Usage

```
do work cleanup
do work tidy
do work consolidate
```
