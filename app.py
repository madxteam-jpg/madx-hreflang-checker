from urllib.parse import urljoin
import io
import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="Hreflang Cluster Auditor", layout="wide", page_icon="🌐"
)

st.title("🌐 Hreflang Cluster Auditor & Summary Generator")
st.markdown(
    "Audit homepage clusters for reciprocity, self-references, canonical alignment, and missing market locales."
)

# Sidebar settings
st.sidebar.header("Audit Settings")
user_agent = st.sidebar.text_input(
    "User-Agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HreflangAuditor/1.0",
)
timeout = st.sidebar.slider("Timeout (seconds)", 3, 30, 10)

urls_input = st.text_area(
    "Enter Homepage URLs (one per line):",
    height=150,
    placeholder="https://example.com/en/\nhttps://example.com/ru/\nhttps://example.com/es/",
)


def generate_png_summary(df):
    """Generates a styled PNG image summary of the audit results using Matplotlib."""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
    ax.axis("tight")
    ax.axis("off")

    summary_df = df[
        [
            "Source URL",
            "Status Code",
            "Self Reference",
            "Missing Locales",
            "Non-Reciprocal",
            "Overall Health",
        ]
    ].copy()

    summary_df["Source URL"] = summary_df["Source URL"].apply(
        lambda x: x[:35] + "..." if len(x) > 35 else x
    )

    table_data = [summary_df.columns.values.tolist()] + summary_df.values.tolist()

    table = ax.table(
        cellText=table_data, colLabels=None, cellLoc="center", loc="center"
    )

    # ✅ FIX: Use auto_set_font_size(False) and set_fontsize(9)
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    header_color = "#1E3A8A"
    for i in range(len(summary_df.columns)):
        cell = table[0, i]
        cell.set_facecolor(header_color)
        cell.set_text_props(color="white", weight="bold")

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.2)
    buffer.seek(0)
    plt.close(fig)
    return buffer


from urllib.parse import urljoin
from bs4 import BeautifulSoup
import pandas as pd
import requests


def audit_cluster(urls, user_agent=None, timeout=10):
    """Crawls a list of homepage URLs, extracts declared hreflang tags, and audits

    the cluster for reciprocity, canonical alignment, self-references, and missing
    locales.
    """
    # Real desktop browser headers to prevent WAF / Cloudflare 403 Forbidden blocks
    headers = {
        "User-Agent": user_agent
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    cluster_data = {}
    master_targets = {}

    # Step 1: Crawl each URL and extract declared hreflang tags and metadata
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=timeout)
            soup = BeautifulSoup(res.text, "html.parser")

            # Extract Canonical URL
            canonical_tag = soup.find("link", rel="canonical")
            canonical_url = (
                canonical_tag.get("href").strip() if canonical_tag else None
            )

            # Extract Hreflang Tags
            hreflangs = {}
            for link in soup.find_all("link", rel="alternate"):
                lang = link.get("hreflang")
                href = link.get("href")
                if lang and href:
                    clean_lang = lang.lower().strip()
                    full_href = urljoin(url, href.strip())
                    hreflangs[clean_lang] = full_href

                    # Track global set of expected locales across the entire cluster
                    if clean_lang not in master_targets:
                        master_targets[clean_lang] = full_href

            cluster_data[url] = {
                "status_code": res.status_code,
                "final_url": res.url,
                "is_redirected": res.url.rstrip("/") != url.rstrip("/"),
                "canonical": canonical_url,
                "hreflangs": hreflangs,
                "error": None,
            }
        except Exception as e:
            cluster_data[url] = {
                "status_code": None,
                "final_url": None,
                "is_redirected": False,
                "canonical": None,
                "hreflangs": {},
                "error": str(e),
            }

    # Step 2: Analyze reciprocity, missing variants, and canonical alignment
    rows = []
    for url in urls:
        d = cluster_data[url]

        # Handle failed requests
        if d["error"]:
            rows.append({
                "Source URL": url,
                "Status Code": "ERR",
                "Self Reference": "FAIL",
                "Canonical Match": "N/A",
                "Total Locales": 0,
                "Missing Locales": len(master_targets),
                "Non-Reciprocal": 0,
                "Audit Summary": f"Request Error: {d['error']}",
                "Overall Health": "CRITICAL",
            })
            continue

        # Rule Checks
        declared_urls = set(d["hreflangs"].values())
        has_self_ref = url.rstrip("/") in [
            target.rstrip("/") for target in declared_urls
        ]

        canonical_ok = True
        if d["canonical"]:
            canonical_ok = d["canonical"].rstrip("/") == url.rstrip("/")

        missing_locales = [
            lang for lang in master_targets if lang not in d["hreflangs"]
        ]

        # Reciprocity Check (Ensure target pages link back to source URL)
        non_reciprocal_count = 0
        for lang, target_url in d["hreflangs"].items():
            if (
                target_url in cluster_data
                and cluster_data[target_url]["hreflangs"]
            ):
                target_declared_urls = [
                    u.rstrip("/")
                    for u in cluster_data[target_url]["hreflangs"].values()
                ]
                if url.rstrip("/") not in target_declared_urls:
                    non_reciprocal_count += 1

        # Summary flags
        issues = []
        if d["status_code"] != 200:
            issues.append(f"HTTP {d['status_code']}")
        if not has_self_ref:
            issues.append("Missing Self-Reference")
        if d["is_redirected"]:
            issues.append(f"Redirects to {d['final_url']}")
        if not canonical_ok:
            issues.append(f"Canonical mismatch ({d['canonical']})")
        if missing_locales:
            issues.append(
                f"Missing {len(missing_locales)} locale(s): {', '.join(missing_locales)}"
            )
        if non_reciprocal_count > 0:
            issues.append(
                f"{non_reciprocal_count} non-reciprocal return link(s)"
            )

        # Health Grading
        if d["status_code"] != 200 or not canonical_ok or not has_self_ref:
            health = "CRITICAL"
        elif issues:
            health = "WARNING"
        else:
            health = "PASS"

        rows.append({
            "Source URL": url,
            "Status Code": d["status_code"],
            "Self Reference": "PASS" if has_self_ref else "FAIL",
            "Canonical Match": "PASS" if canonical_ok else "FAIL",
            "Total Locales": len(d["hreflangs"]),
            "Missing Locales": len(missing_locales),
            "Non-Reciprocal": non_reciprocal_count,
            "Audit Summary": "; ".join(issues)
            if issues
            else "Fully Reciprocal & Complete",
            "Overall Health": health,
        })

    return pd.DataFrame(rows), cluster_data


if st.button("🚀 Run Hreflang Audit", type="primary"):
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]
    if not urls:
        st.warning("Please enter at least one URL.")
    else:
        with st.spinner("Auditing hreflang cluster..."):
            df, cluster_data = audit_cluster(urls)

        st.subheader("📊 Audit Overview")
        st.dataframe(df, use_container_width=True)

        st.markdown("### 📥 Download Audit Reports")
        col_csv, col_png = st.columns(2)

        # 1. Download CSV
        csv_data = df.to_csv(index=False).encode("utf-8")
        col_csv.download_button(
            label="📄 Download Report (CSV)",
            data=csv_data,
            file_name="hreflang_audit_report.csv",
            mime="text/csv",
        )

        # 2. Download PNG
        png_buffer = generate_png_summary(df)
        col_png.download_button(
            label="🖼️ Download Summary Table (PNG)",
            data=png_buffer.getvalue(),
            file_name="hreflang_audit_summary.png",
            mime="image/png",
        )

        # Show inline image preview
        with st.expander("👁️ Preview PNG Graphic"):
            st.image(png_buffer, caption="Generated Audit Summary Graphic")
