# TLMC ETL

This repository contains code that transforms TLMC music archives* from a less structured format into a structured, machine-readable, and relational format that can be used to build a music hosting backend.

\* Only applicable to Conner_CZ's Touhou Music Archive at https://nyaa.si/view/1792784. This will not work for https://www.tlmc.eu/.

## Related Projects

### TLMC Player Backend: https://github.com/sqz269/tlmc-player
A backend that processes the structured output from the ETL and serves it through a RESTful API.

### TLMC Player Frontend: https://github.com/sqz269/tlmc-player-vue

A frontend that utilizes data from the backend to create a web-accessible music app.

## ETL Components

For detailed instructions on how to use each script, see this [README](Docs/STEPS.md).

### Preprocess

A collection of scripts to process TLMC archive (.rar) files, including extracting files and creating snapshots of the archives for later processing.

### Processor

The core component of the ETL process, responsible for scanning, parsing, and reorganizing loosely structured album folders into structured albums and tracks with correct metadata. The processed data is stored in SQLite databases.

### Post-Processor

Includes scripts that convert music files to web-ready formats (HLS, fMP4, DASH, etc.) and commit the processed data into a production-ready PostgreSQL database.

### External Data Collection

A set of scripts that utilize additional Touhou wikis to document albums in the archive and tag each track/album with metadata not directly available in the downloaded files (e.g., original Touhou track information, artist details, lyrics, etc.).

#### Thwiki.cc

Usage: [Thwiki](Docs/ExternalDataSource/Thwiki.md)
