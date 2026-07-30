# ALANIS Data Processing Pipeline

## Overview

This repository contains the tools, parsers, and supporting data used to process railroad bulletin messages, extract location information, match messages to track locations, generate a location database, and import the resulting data into ALANIS.

In addition, the repository contains utilities for generating rail map JSON files, train information datasets, and DART integration support.

---

# Processing Workflow

The standard processing pipeline is:

```text
bulletin_parser
    └── uses byte_decode
            ↓
parsed_messages.json
            ↓
extract_locations.py
            ↓
location_extraction.jsonl
            ↓
sudivs/Program.C
            ↓
matched_tracks.jsonl
            ↓
formatter.py
            ↓
location_database.jsonl
            ↓
ALANIS
```

---

# Step 1 – Parse Bulletin Messages

## Primary Parser

Run:

```bash
bulletin_parser
```

`bulletin_parser` is the primary entry point for processing bulletin messages. Internally, it uses the decoding logic contained in `byte_decode` to decode and parse raw message data.

### Output

```text
parsed_messages.json
```

### BNSF Messages

For BNSF-specific messages, a standalone parser is available:

```bash
bnsf_decode
```

This parser can be used independently when processing BNSF message formats.

---

# Step 2 – Extract Location Information

Run:

```bash
extract_locations.py
```

### Input

```text
parsed_messages.json
```

### Output

```text
location_extraction.jsonl
```

This step extracts subdivision, milepost, station, and other location information from the parsed bulletin messages.

---

# Step 3 – Match Messages to Track Locations

The track matching logic is located in:

```text
sudivs/Program.C
```

### Input

```text
location_extraction.py
```

### Output

```text
matched_tracks.jsonl
```

This step maps extracted locations to known track geometry and subdivision data.

---

# Step 4 – Generate the ALANIS Location Database

Run:

```bash
formatter.py
```

### Input

```text
matched_tracks.jsonl
```

### Output

```text
location_database.jsonl
```

This formats the matched track data into the structure required by ALANIS.

---

# Step 5 – Import Into ALANIS

Load the generated:

```text
location_database
```

into ALANIS.

This database serves as the final output of the processing pipeline and provides the location information used by the application.

---

# Workflow Summary

```text
bulletin_parser
    └── uses byte_decode
            ↓
parsed_messages.json
            ↓
location_extractor
            ↓
messages_with_locations
            ↓
sudivs/Program.C
            ↓
matched_tracks
            ↓
formatter.py
            ↓
location_database
            ↓
ALANIS
```

---

# Track JSON Generation

Rail map and track data can be converted into JSON using the **TrackStore GUI**.

## Steps

1. Launch the TrackStore GUI.
2. Load the desired track files.
3. The application will automatically generate the corresponding JSON output.

---

## Changing the Output JSON Location

The output path is configured in:

```text
TrackStore/Examples/TrackStore GUI/MainWindow.xaml.cs
```

Locate the following code:

```csharp
RailMapExporter.Export(
    TrackStore,
    @"C:\Users\mahee.shah\Desktop\railmap_csx.json"
);
```

Modify the output path as needed.

---

## Rail Map Export Logic

The export functionality is implemented in:

```text
RailExporter.cs
```

within the TrackStore project.

---

# Train Information

Train information is stored in:

```text
csxTrainInfo
```

This dataset was originally provided by Alex and has been converted to JSON format for use by the application.

---

# DART Integration

DART data is accessed through the **DART Proxy**.

> **Important:** The DART Proxy must be running before starting the application and must remain open while the application is running.

When the proxy starts, a message will appear in the terminal containing a URL similar to:

```text
http://localhost:8010/posl?ctl=1&age=1200&g=3
```

Open the generated link in a browser to verify that the proxy is functioning correctly.

If the DART Proxy is not running, DART-related functionality will not be available.

---

# Repository Components

## Parsers

- `bulletin_parser` – Primary bulletin message parser and entry point to the processing pipeline.
- `byte_decode` – Core decoding logic used by `bulletin_parser`.
- `bnsf_decode` – Standalone parser for BNSF message formats.

## Processing Tools

- `location_extractor` – Extracts location information from parsed messages.
- `sudivs/Program.C` – Matches extracted locations to track data.
- `formatter.py` – Generates the ALANIS location database.

## Rail Network Utilities

- `TrackStore GUI` – Generates rail map JSON files.
- `RailExporter.cs` – Rail map export implementation.

## Supporting Data

- `csxTrainInfo` – Train information dataset in JSON format.

## External Dependencies

- `DART Proxy` – Required for DART connectivity and related application features.

---

# Quick Start

```text
1. Run bulletin_parser

2. Generate:
   parsed_messages.json

3. Run location_extractor

4. Generate:
   messages_with_locations

5. Run sudivs/Program.C

6. Generate:
   matched_tracks

7. Run formatter.py

8. Generate:
   location_database

9. Import location_database into ALANIS
```

---

# Notes

- `bulletin_parser` is the primary parser and should be the starting point for message processing.
- `byte_decode` contains the underlying decoding logic used by `bulletin_parser`.
- `bnsf_decode` may be used independently for BNSF-specific data.
- Each stage of the pipeline produces the input required by the next stage.
- Ensure the DART Proxy is running before using any DART-dependent functionality.
- TrackStore automatically generates rail map JSON output after track files are loaded.