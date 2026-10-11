# ModelAnvil Dataset Bank requirements

PRD supporting specification | 8 October 2026 | Incorporated into PRD version 0.2

## Purpose

Let a team choose an openly licensed source or task preset, download a reproducible snapshot, prepare it, and use it in a compatible training or evaluation workflow. The first curated task preset is SVG work. The catalog is extensible to other modalities and custom sources.

The PRD includes requirements BANK01 through BANK07 and the source list by intended output. This supporting specification expands the data contract and demonstration. Exact connector coverage is settled during qualification.

## Requirements

**BANK01 Search and discover.** Provide searchable source cards and task bundles with task, modality, type, declared license, obligations, source URL, review date, size, and compatibility. Acceptance: searching SVG returns the curated icon and emoji candidates, while sources with missing or restricted licenses cannot appear as eligible downloads.

**BANK02 Reproducible download.** Resolve mutable references to immutable snapshots, preserve source and license evidence, and create a durable import job with resumable transfers and checksums. Acceptance: repeated downloads of the same source revision yield matching content manifests; interrupted and cancelled transfers do not produce ready datasets.

**BANK03 Preview and scope.** Let users preview and choose sources, sample limits, subsets, splits, and authorized storage. Acceptance: the launch screen distinguishes measured sizes from unknown estimates and validates storage and budget limits before transfer. Runtime downloads happen on authorized workers, never by silently routing private data through hosted services.

**BANK04 Open content policy.** Exclude noncommercial-only, no-derivatives, research-only, and unclear asset licensing. Retain attribution and applicable notices. Make share-alike material an explicit project policy choice. Acceptance: Lucide retains its ISC and MIT notices; Twemoji graphics use their graphics license; OpenMoji is not silently included in the default preset; unknown licenses fail eligibility validation.

**BANK05 Preparation and leakage checks.** Attach versioned preparation recipes to presets. Acceptance: the SVG recipe preserves source code, renders isolated images, records available label quality, validates unsupported constructs, deduplicates across libraries, and groups icon variants before splitting. Synthetic descriptions remain distinguishable from human-reviewed labels.

**BANK06 Versioning and tenancy.** Respect organization/project permissions for downloads, previews, caches, prepared datasets, and exports. Acceptance: a source update creates a new version and never changes completed runs; unauthorized organizations cannot access another organization's import artifacts or derived datasets.

**BANK07 Catalog extensions and maintenance.** Allow authorized maintainers to add public or organization-private source manifests through a validated schema. Acceptance: publishing requires license evidence, connector fixtures, a pinned snapshot, and sample validation; changed source terms suspend new downloads until requalification. Catalog entries and preparation recipes have independent versions.

## Data contract

Each source record includes stable ID, publisher, source kind, homepage, modality, tasks, asset/dataset license expression, evidence URLs, review date, review revision, source revision strategy, connector kind, include/exclude paths, split policy, measured sizes, preparation recipe, readiness, and obligations. Each completed acquisition adds resolved revision or release identifier, timestamps, hashes, byte counts, license snapshots, exceptions, and validation outcomes.

Provider-specific connectors can use Git snapshots, Hugging Face data-file snapshots, or direct HTTP archives. Executable dataset scripts and repository scripts are disabled by default. The sample catalog is a research draft and must pass qualification before download is enabled.

## Acceptance demonstration

1. Search SVG, inspect two source cards, and choose a bounded starter sample.
2. Download to an authorized worker/storage destination, interrupt transfer, and resume.
3. Validate one known-good SVG, reject an external-resource fixture, and preserve rejection reasons.
4. Create image/SVG pairs and show how filename-derived labels differ from reviewed captions.
5. Verify that a shared icon and its variants stay in one split across Lucide and Feather.
6. Export dataset and attribution manifests and load the selected view into a compatible training recipe.
7. Block an unknown-license source and an unauthorized cross-organization cache read.
8. Reimport the same revision without changing an existing dataset or duplicating committed downloads.

## Initial milestones

First qualify the Git SVG connector and starter preset. Then qualify Hugging Face conversation/preference imports and HTTP audio archives. Add per-source fixtures before expanding the visible downloadable catalog. The UI must advertise only qualified sources; research candidates remain clearly labeled.
