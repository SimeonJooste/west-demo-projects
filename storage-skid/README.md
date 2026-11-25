# Storage skid demo site

A single-page demo site for the WEST containerised storage skid, with an interactive 3D model, the Envoy module specs and a string builder.

## What's in here

| File | What it is |
| --- | --- |
| `index.html` | The whole site: layout, styles and scripts in one file |
| `skid.json` | The skid's 3D model, simplified for the web (see below) |
| `vercel.json` | Vercel settings; tells search engines not to index the demo |
| `tools/stl_to_web.py` | Converts a new CAD export (STL) into `skid.json` |

There's no build step. Three.js r147 and the Montserrat font load from public CDNs.

## Preview locally

The page fetches `skid.json`, so open it through a local server rather than double-clicking the file:

```bash
cd storage-skid && python3 -m http.server 8000
# then open http://localhost:8000
```

## Deploy on Vercel

1. In Vercel, choose **Add New → Project** and import this GitHub repo.
2. Set **Root Directory** to `storage-skid`, and leave **Framework Preset** on **Other** with no build command.
3. Deploy. Every push to `main` redeploys the site; pushes to other branches get preview links.

To let search engines index the site once it's no longer a demo, delete `vercel.json`.

## Updating the 3D model

Export the skid from CAD as a **binary STL** (units in millimetres), then:

```bash
pip install -r storage-skid/tools/requirements.txt
cd storage-skid && python3 tools/stl_to_web.py path/to/0900-00046_rev_2.STL skid.json --html index.html
```

The script prints the model's bounding box. If the dimensions change, update the figures in the hero (`Length`, `Width`, `Height`), the `Footprint` line, and the `L`, `W`, `H` constants in the viewer script. Keep the STL itself out of the repo; it's too large for GitHub.

## Content sources

- WEST Product & Skid Reference Guide, 13 Nov 2026
- WEST Envoy datasheet, 10 Sep 2026
- WEST Summit and WEST Alpine datasheets, 31 Aug 2026
- Skid CAD model 0900-00046 rev 1
