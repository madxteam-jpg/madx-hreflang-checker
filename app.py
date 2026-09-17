from urllib.parse import urljoin
import io
import BeautifulSoup
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

    # Pick key columns for the summary image table
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

    # Truncate long URLs for rendering neatly
    summary_df["Source URL"] = summary_df["Source URL"].apply(
        lambda x: x[:35] + "..." if len(x) > 35 else x
    )

    table_data = [summary_df.columns.values.tolist()] + summary_df.values.tolist()

    table = ax.table(
        cellText=table_data, colLabels=None, cellLoc="center", loc="center"
    )

    table.auto_set_font_size(False)
    table.set_font_size(9)
    table.scale(1.2, 1.8)

    # Styling colors
    header_color = "#1E3A8A"
    for i in range(len(summary_df.columns)):
        cell = table[0, i]
        cell.set_facecolor(header_color)
        cell.set_text_props(color="white", weight="bold")

    # Save to BytesIO buffer
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.2)
    buffer.seek(0)
    plt.close(fig)
    return buffer


def audit_cluster(urls):
    cluster_data = {}
    master_targets = {}

    # Crawl & parse
    for url in urls:
        try:
            res = requests.get(
                url, headers={"User-Agent": user_agent}, timeout=timeout
            )
            soup = BeautifulSoup(res.text, "html.parser")
            canonical_tag = soup.find("link", rel="canonical")

            hreflangs = {}
            for link in soup.find_all("link", rel="alternate"):
                lang = link.get("hreflang")
                href = link.get("href")
                if lang and href:
                    clean_lang = lang.lower().strip()
                    full_href = urljoin(url, href.strip())
                    hreflangs[clean_lang] = full_href
                    if clean_lang not in master_targets:
                        master_targets[clean_lang] = full_href

            cluster_data[url] = {
                "status_code": res.status_code,
                "final_url": res.url,
                "is_redirected": res.url != url,
                "canonical": canonical_tag.get("href")
                if canonical_tag
                else None,
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

    # Evaluate issues
    rows = []
    for url in urls:
        d = cluster_data[url]
        if d["error"]:
            rows.append({
                "Source URL": url,
                "Status Code": "ERR",
                "Self Reference": "FAIL",
                "Canonical Match": "N/A",
                "Total Locales": 0,
                "Missing Locales": len(master_targets),
                "Non-Reciprocal": 0,
                "Audit Summary": d["error"],
                "Overall Health": "CRITICAL",
            })
            continue

        has_self = url in set(d["hreflangs"].values())
        canonical_ok = (d["canonical"] == url) if d["canonical"] else True
        missing = [
            lang for lang in master_targets if lang not in d["hreflangs"]
        ]

        non_reciprocal = 0
        for lang, target in d["hreflangs"].items():
            if target in cluster_data and cluster_data[target]["hreflangs"]:
                if url not in cluster_data[target]["hreflangs"].values():
                    non_reciprocal += 1

        issues = []
        if not has_self:
            issues.append("Missing Self-Reference")
        if d["status_code"] != 200:
            issues.append(f"HTTP {d['status_code']}")
        if d["is_redirected"]:
            issues.append("Redirected")
        if not canonical_ok:
            issues.append("Canonical Mismatch")
        if missing:
            issues.append(f"Missing {len(missing)} Locales")
        if non_reciprocal > 0:
            issues.append(f"{non_reciprocal} Non-Reciprocal")

        health = (
            "PASS"
            if not issues
            else (
                "CRITICAL"
                if any(
                    k in " ".join(issues)
                    for k in ["HTTP", "Canonical", "Self-Reference"]
                )
                else "WARNING"
            )
        )

        rows.append({
            "Source URL": url,
            "Status Code": d["status_code"],
            "Self Reference": "PASS" if has_self else "FAIL",
            "Canonical Match": "PASS" if canonical_ok else "FAIL",
            "Total Locales": len(d["hreflangs"]),
            "Missing Locales": len(missing),
            "Non-Reciprocal": non_reciprocal,
            "Audit Summary": "; ".join(issues)
            if issues
            else "Fully Reciprocal",
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
