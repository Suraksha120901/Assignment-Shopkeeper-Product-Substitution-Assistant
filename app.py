# app.py
import streamlit as st
import json
import networkx as nx
from collections import deque, defaultdict
from pathlib import Path

# ---------------------------
# Utilities: load KG from JSON
# ---------------------------
def load_kg(path="kg.json"):
    data = json.loads(Path(path).read_text())
    G = nx.DiGraph()
    # Add nodes
    for n in data["nodes"]:
        G.add_node(n["id"], **n["props"])
    # Add edges (typed)
    for e in data["edges"]:
        G.add_edge(e["source"], e["target"], type=e.get("type","RELATED"))
    return G

# ---------------------------
# Helper accessors
# ---------------------------
def is_product(node, G):
    return G.nodes[node].get("type") == "product"

def get_price(node, G):
    return G.nodes[node].get("price")

def in_stock(node, G):
    return G.nodes[node].get("in_stock", False)

def get_brand(node, G):
    return G.nodes[node].get("brand")

def get_tags(node, G):
    return set(G.nodes[node].get("tags", []))

def get_category(node, G):
    return G.nodes[node].get("category")

# ---------------------------
# Search / Ranking
# ---------------------------
def find_alternatives(G, requested_product_id, max_price=None, required_tags=None, optional_brand=None, max_results=3):
    required_tags = set(required_tags or [])
    if requested_product_id not in G:
        return {"error": "Requested product not found in KG."}
    # If requested product is available and matches constraints, return it
    if is_product(requested_product_id, G) and in_stock(requested_product_id, G):
        price_ok = (max_price is None) or (get_price(requested_product_id, G) <= max_price)
        tags_ok = required_tags.issubset(get_tags(requested_product_id, G))
        brand_ok = (optional_brand is None) or (get_brand(requested_product_id, G) == optional_brand)
        if price_ok and tags_ok and brand_ok:
            return {"exact_match": requested_product_id}

    # Graph-based BFS from the requested node
    # We look for other product nodes reachable via:
    # product -> category -> other products (IS_A edges), or SIMILAR_TO edges between categories
    # We'll perform BFS on the graph treating all edges equally, but track path and distances.
    queue = deque()
    visited = set([requested_product_id])
    queue.append((requested_product_id, 0, [requested_product_id]))
    candidates = []

    while queue:
        node, dist, path = queue.popleft()
        # Consider neighbors (outgoing and incoming) to traverse graph as undirected
        neighbors = list(G.successors(node)) + list(G.predecessors(node))
        for nbr in neighbors:
            if nbr in visited:
                continue
            visited.add(nbr)
            new_path = path + [nbr]
            # If neighbor is a product candidate (and not the requested product)
            if is_product(nbr, G) and nbr != requested_product_id:
                # Filter by in-stock and price and tags and optional brand
                if not in_stock(nbr):
                    pass
                else:
                    price_ok = (max_price is None) or (get_price(nbr, G) <= max_price)
                    tags_ok = required_tags.issubset(get_tags(nbr, G))
                    brand_ok = (optional_brand is None) or (get_brand(nbr, G) == optional_brand)
                    if price_ok and tags_ok and brand_ok:
                        # Score: prefer same category (0 distance to category), brand match, more tag overlap, cheaper price
                        score, reasons = score_candidate(G, requested_product_id, nbr, required_tags, optional_brand)
                        candidates.append({"product": nbr, "score": score, "reasons": reasons, "path": new_path})
            # Continue BFS
            if dist + 1 <= 4:  # limit depth to 4
                queue.append((nbr, dist+1, new_path))

    # Sort candidates by score desc then price asc
    candidates = sorted(candidates, key=lambda x: (-x["score"], get_price(x["product"], G)))
    top = candidates[:max_results]
    return {"alternatives": top}

# ---------------------------
# Scoring & Rule Explanations
# ---------------------------
def score_candidate(G, requested, candidate, required_tags, optional_brand):
    score = 0.0
    reasons = []

    req_cat = get_category(requested, G)
    cand_cat = get_category(candidate, G)
    # Rule: same_category -> strong boost
    if req_cat and cand_cat and req_cat == cand_cat:
        score += 3.0
        reasons.append("same_category")
    else:
        # Check if categories are connected via SIMILAR_TO or shared parent in KG
        if categories_are_similar(G, req_cat, cand_cat):
            score += 1.5
            reasons.append("related_category")

    # Brand preference
    if optional_brand:
        if get_brand(candidate, G) == optional_brand:
            score += 1.0
            reasons.append("brand_match")
        else:
            reasons.append("different_brand")
    else:
        # if same brand as requested, small boost
        if get_brand(candidate, G) == get_brand(requested, G):
            score += 0.5
            reasons.append("same_brand")

    # Tag coverage: each required tag matched gives +1
    cand_tags = get_tags(candidate, G)
    matched_tags = required_tags.intersection(cand_tags)
    if required_tags:
        if matched_tags == required_tags:
            score += 2.0
            reasons.append("all_required_tags_matched")
        else:
            missing = required_tags - matched_tags
            # allow partial but penalize
            score += 0.5 * len(matched_tags)
            reasons.append(f"missing_tags:{','.join(sorted(missing))}")

    # Price: cheaper than requested gives boost
    try:
        req_price = get_price(requested, G)
        cand_price = get_price(candidate, G)
        if req_price is not None and cand_price is not None:
            if cand_price <= req_price:
                score += 1.0
                reasons.append("cheaper_or_equal_price")
            else:
                # small penalty for being more expensive
                score -= 0.5 * ((cand_price - req_price) / max(1.0, req_price))
                reasons.append("more_expensive")
    except Exception:
        pass

    return score, reasons

def categories_are_similar(G, cat_a, cat_b):
    if not cat_a or not cat_b:
        return False
    if cat_a == cat_b:
        return True
    # Look for SIMILAR_TO edges between categories
    if G.has_edge(cat_a, cat_b):
        for e in G.get_edge_data(cat_a, cat_b).values():
            if e.get("type") == "SIMILAR_TO":
                return True
    if G.has_edge(cat_b, cat_a):
        for e in G.get_edge_data(cat_b, cat_a).values():
            if e.get("type") == "SIMILAR_TO":
                return True
    return False

# ---------------------------
# Human-readable explanation generator
# ---------------------------
def human_explanation(G, requested, candidate_entry):
    candidate = candidate_entry["product"]
    reasons = candidate_entry["reasons"]
    expl = []
    node = G.nodes[candidate]
    title = node.get("name", candidate)
    # Rule-based mapping
    if "same_category" in reasons and "same_brand" in reasons:
        expl.append(f"{title} is from the same category and same brand as requested.")
    elif "same_category" in reasons and "brand_match" in reasons:
        expl.append(f"{title} is in the same category and matches the preferred brand.")
    elif "same_category" in reasons:
        expl.append(f"{title} is in the same category as the requested product.")
    elif any(r.startswith("related_category") for r in reasons):
        expl.append(f"{title} is from a related category (closely related product).")
    # Tags
    for r in reasons:
        if r.startswith("all_required_tags_matched"):
            expl.append("Matches all required tags.")
        if r.startswith("missing_tags"):
            missing = r.split(":",1)[1]
            expl.append(f"Missing required tags: {missing}.")
    # Price hints
    if "cheaper_or_equal_price" in reasons:
        expl.append("Cheaper or equal in price compared to requested product.")
    if "more_expensive" in reasons:
        expl.append("Slightly more expensive than requested product.")
    # Brand hints
    if "brand_match" in reasons:
        expl.append("Matches the preferred brand you requested.")
    if "different_brand" in reasons:
        expl.append("Different brand (but meets other constraints).")
    # Always include price and stock info
    expl.append(f"Price: ₹{get_price(candidate, G)}; In stock: {in_stock(candidate, G)}; Brand: {get_brand(candidate, G)}")
    return " ".join(expl)

# ---------------------------
# Streamlit UI
# ---------------------------
def main():
    st.set_page_config(page_title="Shopkeeper Product Substitution Assistant", layout="centered")
    st.title("Shopkeeper Product Substitution Assistant (KG + Rule-based)")

    # Load KG
    G = load_kg("kg.json")

    # Prepare product list for selection
    product_nodes = [n for n in G.nodes if is_product(n, G)]
    product_display = {n: G.nodes[n].get("name", n) for n in product_nodes}

    requested = st.selectbox("Select requested product", options=product_nodes, format_func=lambda x: product_display[x])
    cols = st.columns(3)
    max_price = cols[0].number_input("Max price (₹)", min_value=0.0, value=0.0)
    if max_price == 0.0:
        max_price = None
    tags_input = cols[1].text_input("Required tags (comma-separated)", value="")
    required_tags = [t.strip() for t in tags_input.split(",") if t.strip()]
    optional_brand = cols[2].text_input("Preferred brand (optional)", value="").strip() or None

    if st.button("Find Alternatives"):
        with st.spinner("Searching KG..."):
            res = find_alternatives(G, requested, max_price=max_price, required_tags=required_tags, optional_brand=optional_brand, max_results=3)
        if "error" in res:
            st.error(res["error"])
            return
        if res.get("exact_match"):
            st.success("Exact product available that matches your constraints:")
            pid = res["exact_match"]
            p = G.nodes[pid]
            st.write(f"**{p.get('name')}** — ₹{p.get('price')} — Brand: {p.get('brand')} — Tags: {', '.join(p.get('tags',[]))} — In stock: {p.get('in_stock')}")
            return
        alts = res.get("alternatives", [])
        if not alts:
            st.info("No alternative found that satisfies all constraints.")
            return
        st.subheader("Suggested alternatives")
        for alt in alts:
            pid = alt["product"]
            node = G.nodes[pid]
            st.markdown(f"**{node.get('name')}** — ₹{node.get('price')} — Brand: {node.get('brand')}")
            expl = human_explanation(G, requested, alt)
            st.write(f"**Explanation (rule-derived):** {expl}")
            st.write("---")

if __name__ == "__main__":
    main()
