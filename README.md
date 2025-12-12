# Assignment-Shopkeeper-Product-Substitution-Assistant

A Streamlit app that suggests alternative products when a requested item is out of stock. Backend uses a Knowledge Graph + graph traversal and deterministic rule-based explanations (no ML/LLMs).

## Demo
(Place your deployed Streamlit link here)

## Repo layout
- app.py               # Streamlit app (main)
- kg.json              # Knowledge Graph data (nodes + edges)
- README.md            # This file
- requirements.txt     # python packages

## How to run locally
1. Clone repo
2. Create a venv and activate:
   python -m venv .venv
   source .venv/bin/activate  # or .venv\\Scripts\\activate on Windows
3. Install:
   pip install -r requirements.txt
   (requirements: streamlit, networkx)
4. Run:
   streamlit run app.py

## KG design (nodes + edges)
Nodes:
- product: contains `name`, `price`, `brand`, `category`, `tags` (list), `in_stock` (bool)
- category: `name`
- brand: `name`

Edges (typed):
- IS_A: product -> category
- HAS_BRAND: product <-> brand (or brand -> product)
- SIMILAR_TO: category <-> category (optional)
- Other relations can be added (e.g., SUBCATEGORY_OF)

The KG is stored as JSON with two lists: `nodes` and `edges`.

## Search method used
- The system performs a BFS-style traversal from the requested product across the KG (treating edges as bidirectional for traversal).
- Candidate products are collected when encountered within a limited depth.
- Candidates are filtered:
  - Must be in-stock.
  - Must respect `max_price` if provided.
  - Must include all required tags (or be filtered out if missing).
  - If `optional_brand` provided, brand must match.
- Candidate scoring considers:
  - Category closeness (same category >> related category).
  - Brand match (preferred brand or same brand as requested).
  - Tag coverage (all required tags matched is strong).
  - Price (cheaper gets boost).
- Final ranking: score desc, price asc.

## Explanation rule mechanism
- Rules are deterministic and derived from node & edge properties:
  - `same_category` — candidate shares the exact category node.
  - `related_category` — candidate belongs to a category connected via `SIMILAR_TO`.
  - `brand_match` / `same_brand` — candidate brand equals preferred or requested brand.
  - `all_required_tags_matched` — candidate's tag set covers required tags.
  - `cheaper_or_equal_price` — candidate price ≤ requested price.
- Explanations are assembled from the triggered rules (no free-text generation).

## Example rules -> human explanation mapping
- `same_category` + `same_brand` -> "Same category and same brand."
- `same_category` + `all_required_tags_matched` -> "Same category and matches required tags."
- `related_category` -> "From a related category (e.g., plant-based milk when dairy milk not available)."

## Deployment
### Streamlit Cloud (recommended)
1. Create a GitHub repo and push files.
2. Log in to https://streamlit.io/cloud and create a new app linked to your repo.
3. Set the main file as `app.py`.
4. Add `kg.json` in the repo root.
5. Deploy.

### Alternative: Docker / VPS
- Use `streamlit run app.py` or build a small Docker image.

## Notes & extensions
- The KG JSON provided is small sample data. In production, load from DB or a graph DB (Neo4j, RDF store).
- You can extend KG with nutritional facts or hierarchical categories and improve scoring weights.
